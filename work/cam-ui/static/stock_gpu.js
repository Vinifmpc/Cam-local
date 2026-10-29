/*
 * MIT License
 * Copyright (c) 2026 CAM Local contributors
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
 * of the Software, and to permit persons to whom the Software is furnished to do
 * so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 * Original implementation. Removal follows StockModel's swept flat disk, not a
 * projected closest-point approximation. No code from GPL CAM viewers is used.
 *
 * createGpuStock(renderer, config, moves)
 * config: StockModel fields plus optional physical_bottom (default: bottom),
 * gpu_resolution (longest side, or [nx,ny], default 2048; hard cap 2048/axis),
 * gpu_memory_mb (default 96, 16..256), gpu_color (Three Color representation).
 * object: add to the scene; transforms of it or its parents are supported.
 * seek(index + fraction): synchronous command submission, never gl.finish().
 * prepareFinal(): optional separate final cache; never changes the current view.
 * sample(points): gathers and reads 1..64 cells; intentionally synchronizes GPU.
 * ready means the latest target's commands were submitted, not a GPU fence.
 * Full prefix replay on uncached seeks is deliberate: min cannot undo a cut.
 * 2.5D columns cannot represent undercuts, loose-part physics or suspended stock.
 */
import * as THREE from 'three';

const RAPIDS=new Set(['travel','retract','clearance_adjust','approach_rapid']);
const MAX_SIDE=2048,MAX_MOVES=1000000,SAMPLE_LIMIT=64;
let nextGeneration=1;
const now=()=>globalThis.performance?.now?.()??Date.now();
const fail=message=>{throw Error('Simulação GPU: '+message);};
const finite=value=>typeof value==='number'&&Number.isFinite(value);

// Exported pure helpers are also useful for numerical tests without a GL/DOM.
export function gpuStockGrid(config,maxTextureSize=MAX_SIDE){
 if(!config||!['x0','y0','x1','y1','top','bottom','diameter'].every(k=>finite(config[k]))||config.x1<=config.x0||config.y1<=config.y0||config.top<=config.bottom||config.diameter<=0)fail('bruto ou diâmetro inválido.');
 const physical=config.physical_bottom??config.bottom;
 if(!finite(physical)||physical<config.bottom||physical>=config.top)fail('o fundo físico deve ficar entre o limite inferior da simulação e o topo.');
 const limit=Math.min(MAX_SIDE,Math.floor(maxTextureSize));
 if(limit<2)fail('limite de textura insuficiente.');
 const requested=config.gpu_resolution??MAX_SIDE,width=config.x1-config.x0,height=config.y1-config.y0;
 let nx,ny;
 if(Array.isArray(requested)){
  if(requested.length!==2||!requested.every(v=>Number.isInteger(v)&&v>=2&&v<=limit))fail(`gpu_resolution deve conter dois inteiros entre 2 e ${limit}.`);
  [nx,ny]=requested;
 }else{
  if(!Number.isInteger(requested)||requested<2||requested>MAX_SIDE)fail('gpu_resolution deve ser um inteiro entre 2 e 2048.');
  const side=Math.min(requested,limit),span=Math.max(width,height);
  nx=Math.max(2,Math.ceil(side*width/span));ny=Math.max(2,Math.ceil(side*height/span));
 }
 return {nx,ny,dx:width/nx,dy:height/ny,width,height,physicalBottom:physical};
}
export function gpuStockBudget(nx,ny,cuttingMoves,budgetMb=96){
 if(!Number.isInteger(nx)||!Number.isInteger(ny)||nx<2||ny<2||nx>MAX_SIDE||ny>MAX_SIDE||!Number.isInteger(cuttingMoves)||cuttingMoves<0||cuttingMoves>MAX_MOVES)fail('dimensões ou quantidade de segmentos inválida para o orçamento.');
 if(!finite(budgetMb)||budgetMb<16||budgetMb>256)fail('gpu_memory_mb deve ficar entre 16 e 256.');
 const targetBytes=nx*ny*8,attributeBytes=cuttingMoves*28,budgetBytes=budgetMb*1024*1024;
 if(targetBytes+attributeBytes+4096>budgetBytes)fail('o percurso e a textura excedem o orçamento de memória. Reduza gpu_resolution.');
 return {targetBytes,attributeBytes,budgetBytes,canCacheFinal:targetBytes*2+attributeBytes+4096<=budgetBytes};
}
export function gpuSweepMinimum(point,move,radius){
 if(RAPIDS.has(move?.[0]))return null;
 const [x,y]=point,ax=move[1],ay=move[2],az=move[3],bx=move[4],by=move[5],bz=move[6];
 const wx=x-ax,wy=y-ay,dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy,r2=radius*radius;
 if(l2===0)return wx*wx+wy*wy<=r2?Math.min(az,bz):null;
 const t=(wx*dx+wy*dy)/l2,cross=wx*dy-wy*dx,d2=cross*cross/l2;
 if(d2>r2)return null;
 const reach=Math.sqrt(Math.max(0,(r2-d2)/l2)),lo=Math.max(0,t-reach),hi=Math.min(1,t+reach);
 return lo>hi?null:az+(bz-az)*(bz>=az?lo:hi);
}

const sweepVertex=`
precision highp float;
precision highp int;
in vec3 position;
in vec3 moveA;
in vec3 moveB;
in float moveIndex;
uniform vec2 uSize;
uniform float uRadius;
uniform int uFullIndex;
uniform float uFraction;
flat out vec3 vA;
flat out vec3 vB;
void main(){
 int index=int(moveIndex+0.5);
 vA=moveA;vB=index==uFullIndex?mix(moveA,moveB,uFraction):moveB;
 if(index>uFullIndex||(index==uFullIndex&&uFraction<=0.0)){
  gl_Position=vec4(2.0,2.0,0.0,1.0);return;
 }
 vec2 lo=min(vA.xy,vB.xy)-vec2(uRadius),hi=max(vA.xy,vB.xy)+vec2(uRadius);
 vec2 point=mix(lo,hi,position.xy);
 gl_Position=vec4(point/uSize*2.0-1.0,0.0,1.0);
}`;
const sweepFragment=`
precision highp float;
precision highp int;
uniform vec2 uCellSize;
uniform float uRadius;
uniform float uBottom;
uniform float uTop;
flat in vec3 vA;
flat in vec3 vB;
out vec4 outColor;
void main(){
 vec2 w=gl_FragCoord.xy*uCellSize-vA.xy,delta=vB.xy-vA.xy;
 float l2=dot(delta,delta),r2=uRadius*uRadius,z;
 if(l2==0.0){
  if(dot(w,w)>r2)discard;
  z=min(vA.z,vB.z);
 }else{
  float t=dot(w,delta)/l2;
  // Cross product avoids catastrophic cancellation on long, narrow ramps.
  float crossValue=w.x*delta.y-w.y*delta.x;
  float d2=crossValue*crossValue/l2;
  if(d2>r2)discard;
  float reach=sqrt(max(0.0,(r2-d2)/l2));
  float lo=max(0.0,t-reach),hi=min(1.0,t+reach);
  if(lo>hi)discard;
  z=mix(vA.z,vB.z,vB.z>=vA.z?lo:hi);
 }
 gl_FragDepth=clamp((z-uBottom)/(uTop-uBottom),0.0,1.0);
 outColor=vec4(0.0);
}`;

const visualVertex=`
varying vec3 vLocalPosition;
void main(){
 vLocalPosition=position;
 gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);
}`;
function visualFragment(maxSteps){return `
precision highp float;
precision highp int;
uniform highp sampler2D uDepth;
uniform vec2 uSize;
uniform vec2 uCellSize;
uniform ivec2 uResolution;
uniform float uBottom;
uniform float uTop;
uniform float uPhysicalBottom;
uniform float uEmptyEpsilon;
uniform vec3 uBaseColor;
uniform vec3 uCameraLocal;
uniform vec3 uOrthoDirection;
uniform mat4 uInverseModel;
uniform mat4 uModel;
uniform mat4 projectionMatrix;
varying vec3 vLocalPosition;
float heightAt(ivec2 cell){return mix(uBottom,uTop,texelFetch(uDepth,cell,0).r);}
float occupancyAt(ivec2 cell,float z){
 if(any(lessThan(cell,ivec2(0)))||any(greaterThanEqual(cell,uResolution)))return 0.0;
 float height=heightAt(cell);
 return height>uPhysicalBottom+uEmptyEpsilon&&height>=z-uEmptyEpsilon?1.0:0.0;
}
float gaussianWeight(int offset){int distance=abs(offset);return distance==0?6.0:(distance==1?4.0:1.0);}
float derivativeWeight(int offset){return offset==0?0.0:sign(float(offset))*(abs(offset)==1?2.0:1.0);}
vec3 wallLightingNormal(ivec2 cell,float z,vec3 geometricNormal){
 vec2 gradient=vec2(0.0);
 for(int y=-2;y<=2;y++)for(int x=-2;x<=2;x++){
  float occupied=occupancyAt(cell+ivec2(x,y),z);
  gradient.x+=occupied*derivativeWeight(x)*gaussianWeight(y);
  gradient.y+=occupied*derivativeWeight(y)*gaussianWeight(x);
 }
 vec3 outward=vec3(-gradient/uCellSize,0.0);
 if(dot(outward,outward)<1e-12)return geometricNormal;
 outward=normalize(outward);
 // Opposite walls in a narrow slot may cancel or reverse the gradient.
 // Keep each wall's hemisphere; this changes lighting, never a hit or height.
 return dot(outward,geometricNormal)>.35?outward:geometricNormal;
}
bool slab(float origin,float direction,float lo,float hi,inout float enter,inout float leave,inout vec3 normal,vec3 axis){
 if(abs(direction)<1e-12)return origin>=lo&&origin<=hi;
 float a=(lo-origin)/direction,b=(hi-origin)/direction;
 vec3 n=direction>0.0?-axis:axis;
 if(a>b){float swapValue=a;a=b;b=swapValue;}
 if(a>enter){enter=a;normal=n;}
 leave=min(leave,b);return enter<=leave;
}
void main(){
 vec3 direction,origin;
 if(isOrthographic){
  direction=normalize(uOrthoDirection);
  // Every fragment has its own parallel ray; cameraPosition alone is wrong.
  float ahead=length(uSize)+(uTop-uPhysicalBottom)+1.0;
  origin=vLocalPosition-direction*ahead;
 }else{
  origin=uCameraLocal;direction=normalize(vLocalPosition-origin);
 }
 float enter=0.0,leave=1e30;
 vec3 entryNormal=vec3(0.0,0.0,1.0);
 if(!slab(origin.x,direction.x,0.0,uSize.x,enter,leave,entryNormal,vec3(1,0,0))||
    !slab(origin.y,direction.y,0.0,uSize.y,enter,leave,entryNormal,vec3(0,1,0))||
    !slab(origin.z,direction.z,uPhysicalBottom,uTop,enter,leave,entryNormal,vec3(0,0,1)))discard;
 // Clip the ray interval too, rather than clamping a hit before the camera's
 // near plane to gl_FragDepth=0. This also handles cameras close to the stock.
 vec4 rayStartClip=projectionMatrix*viewMatrix*uModel*vec4(origin,1.0);
 vec4 rayStepClip=projectionMatrix*viewMatrix*uModel*vec4(direction,0.0);
 float nearDivisor=rayStepClip.z+rayStepClip.w,farDivisor=rayStepClip.z-rayStepClip.w;
 if(abs(nearDivisor)>1e-20)enter=max(enter,-(rayStartClip.z+rayStartClip.w)/nearDivisor);
 if(abs(farDivisor)>1e-20)leave=min(leave,-(rayStartClip.z-rayStartClip.w)/farDivisor);
 if(enter>leave)discard;
 float entry=max(0.0,enter);
 vec3 p=origin+direction*entry;
 // The directional epsilon chooses the entered cell on an exact grid edge.
 vec2 bias=sign(direction.xy)*uCellSize*1e-5;
 ivec2 cell=clamp(ivec2(floor((p.xy+bias)/uCellSize)),ivec2(0),uResolution-1);
 ivec2 stride=ivec2(sign(direction.xy));
 vec2 stepTime=vec2(1e30),nextTime=vec2(1e30);
 if(abs(direction.x)>1e-12){
  stepTime.x=uCellSize.x/abs(direction.x);
  float border=(float(cell.x)+(direction.x>0.0?1.0:0.0))*uCellSize.x;
  nextTime.x=(border-origin.x)/direction.x;
 }
 if(abs(direction.y)>1e-12){
  stepTime.y=uCellSize.y/abs(direction.y);
  float border=(float(cell.y)+(direction.y>0.0?1.0:0.0))*uCellSize.y;
  nextTime.y=(border-origin.y)/direction.y;
 }
 bool hit=false;
 float hitTime=0.0;
 vec3 hitNormal=entryNormal;
 // A ray crosses at most nx+ny cell boundaries. No arbitrary 128-step cutoff.
 for(int iteration=0;iteration<${maxSteps};iteration++){
  if(any(lessThan(cell,ivec2(0)))||any(greaterThanEqual(cell,uResolution))||entry>leave)break;
  float cellExit=min(leave,min(nextTime.x,nextTime.y));
  float height=heightAt(cell);
  if(height>uPhysicalBottom+uEmptyEpsilon){
   float entryZ=origin.z+direction.z*entry;
   if(entryZ<=height+uEmptyEpsilon){hit=true;hitTime=entry;break;}
   if(direction.z<-1e-12){
    float topTime=(height-origin.z)/direction.z;
    if(topTime>=entry&&topTime<=cellExit){hit=true;hitTime=topTime;hitNormal=vec3(0,0,1);break;}
   }
  }
  if(cellExit>=leave)break;
  // Crossing both axes at a corner must advance both, without phantom cells.
  bool crossX=nextTime.x<=nextTime.y;
  bool crossY=nextTime.y<=nextTime.x;
  entry=cellExit;
  if(crossX){cell.x+=stride.x;nextTime.x+=stepTime.x;hitNormal=vec3(-float(stride.x),0,0);}
  if(crossY){cell.y+=stride.y;nextTime.y+=stepTime.y;hitNormal=vec3(0,-float(stride.y),0);}
 }
 if(!hit)discard;
 vec3 localPoint=origin+direction*hitTime;
 if(abs(hitNormal.z)<0.5)hitNormal=wallLightingNormal(cell,localPoint.z,hitNormal);
 vec4 worldPoint=uModel*vec4(localPoint,1.0);
 vec4 clip=projectionMatrix*viewMatrix*worldPoint;
 if(clip.w<=0.0)discard;
 float ndcDepth=clip.z/clip.w;
 if(ndcDepth < -1.000001||ndcDepth > 1.000001)discard;
 gl_FragDepth=ndcDepth*0.5+0.5;
 // Transform normals correctly even if the display group is scaled.
 vec3 worldNormal=normalize(transpose(mat3(uInverseModel))*hitNormal);
 vec3 key=normalize(vec3(-0.35,-0.55,1.0));
 float light=0.48+0.43*max(dot(worldNormal,key),0.0)+0.09*max(dot(worldNormal,normalize(vec3(0.7,0.3,0.4))),0.0);
 float depthShade=mix(0.86,1.0,clamp((localPoint.z-uPhysicalBottom)/(uTop-uPhysicalBottom),0.0,1.0));
 gl_FragColor=vec4(uBaseColor*light*depthShade,1.0);
 #include <tonemapping_fragment>
 #include <colorspace_fragment>
}`;}

const sampleVertex=`
precision highp float;
in vec3 position;
void main(){gl_Position=vec4(position.xy*2.0-1.0,0.0,1.0);}`;
const sampleFragment=`
precision highp float;
precision highp int;
uniform highp sampler2D uDepth;
uniform vec2 uCells[64];
out vec4 outColor;
void main(){
 int index=int(gl_FragCoord.x);
 float depth=texelFetch(uDepth,ivec2(uCells[index]),0).r;
 uint bits=floatBitsToUint(depth);
 uvec4 bytes=uvec4((bits>>24u)&255u,(bits>>16u)&255u,(bits>>8u)&255u,bits&255u);
 outColor=vec4(bytes)/255.0;
}`;

function quadGeometry(instanced=false){
 const geometry=instanced?new THREE.InstancedBufferGeometry():new THREE.BufferGeometry();
 geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0,1,1,0,0,1,0],3));
 geometry.setIndex([0,1,2,0,2,3]);return geometry;
}
function savedRenderer(renderer,gl,action){
 const target=renderer.getRenderTarget(),cube=renderer.getActiveCubeFace?.()??0,mip=renderer.getActiveMipmapLevel?.()??0;
 const viewport=renderer.getCurrentViewport(new THREE.Vector4()),scissor=new THREE.Vector4().fromArray(gl.getParameter(gl.SCISSOR_BOX)),scissorTest=gl.isEnabled(gl.SCISSOR_TEST);
 const color=renderer.getClearColor(new THREE.Color()),alpha=renderer.getClearAlpha(),auto=renderer.autoClear;
 const xr=renderer.xr?.enabled,shadows=renderer.shadowMap?.autoUpdate,clearDepth=gl.getParameter(gl.DEPTH_CLEAR_VALUE);
 const shaderErrors=renderer.debug?.checkShaderErrors,errorHook=renderer.debug?.onShaderError;
 let shaderFailure=null;
 try{
  renderer.autoClear=false;if(renderer.xr)renderer.xr.enabled=false;if(renderer.shadowMap)renderer.shadowMap.autoUpdate=false;
  renderer.state.buffers.depth.setClear(1);
  if(renderer.debug){
   renderer.debug.checkShaderErrors=true;
   renderer.debug.onShaderError=(context,program,vertex,fragment)=>{shaderFailure=[context.getProgramInfoLog(program),context.getShaderInfoLog(vertex),context.getShaderInfoLog(fragment)].filter(Boolean).join('\n');};
  }
  const result=action();if(shaderFailure)fail('falha ao compilar shader. '+shaderFailure);return result;
 }finally{
  renderer.setRenderTarget(target,cube,mip);renderer.state.viewport(viewport);renderer.state.scissor(scissor);renderer.state.setScissorTest(scissorTest);
  renderer.setClearColor(color,alpha);renderer.state.buffers.depth.setClear(clearDepth);renderer.autoClear=auto;
  if(renderer.xr)renderer.xr.enabled=xr;if(renderer.shadowMap)renderer.shadowMap.autoUpdate=shadows;
  if(renderer.debug){renderer.debug.checkShaderErrors=shaderErrors;renderer.debug.onShaderError=errorHook;}
 }
}

export function createGpuStock(renderer,config,moves){
 if(!renderer?.isWebGLRenderer||typeof renderer.getContext!=='function')fail('requer o WebGLRenderer do Three.js.');
 const gl=renderer.getContext();
 if(!gl||typeof gl.texStorage2D!=='function'||typeof gl.drawElementsInstanced!=='function')fail('WebGL2 não está disponível.');
 if(gl.isContextLost())fail('contexto WebGL perdido.');
 if(renderer.capabilities.reversedDepthBuffer||renderer.capabilities.logarithmicDepthBuffer)fail('depth reverso/logarítmico não é compatível com este módulo.');
 if(!Array.isArray(moves)||moves.length>MAX_MOVES)fail(`o percurso deve conter até ${MAX_MOVES.toLocaleString('pt-BR')} movimentos.`);
 const grid=gpuStockGrid(config,gl.getParameter(gl.MAX_TEXTURE_SIZE)),{nx,ny,dx,dy,width,height,physicalBottom}=grid;
 let count=0;
 for(const move of moves){
  if(!Array.isArray(move)||move.length<7)fail('movimento inválido.');
  if(RAPIDS.has(move[0]))continue;
  if(!move.slice(1,7).every(finite))fail('movimento não finito.');
  count++;
 }
 const {targetBytes,attributeBytes,budgetBytes}=gpuStockBudget(nx,ny,count,config.gpu_memory_mb??96);
 const generation=nextGeneration++,object=new THREE.Group();object.name='GPU stock · sampled 2.5D columns';
 const resources=[],targets=[];
 const track=resource=>{resources.push(resource);return resource;};
 let disposed=false,lost=false,released=false,ready=false,error=null,target=0,builds=0,seeks=0,cacheHits=0,lastSeekMs=0,lastBuildMs=0,lastSampleMs=0,finalTarget=null,currentTarget=null;
 const rendererInfo=(()=>{
  const extension=gl.getExtension('WEBGL_debug_renderer_info');
  const name=String(gl.getParameter(extension?.UNMASKED_RENDERER_WEBGL??gl.RENDERER));
  const vendor=String(gl.getParameter(extension?.UNMASKED_VENDOR_WEBGL??gl.VENDOR));
  return {renderer:name,vendor,software_hint:/swiftshader|llvmpipe|software|basic render|\bwarp\b/i.test(name+' '+vendor)};
 })();
 function ensure(){if(disposed)fail('instância encerrada.');if(lost||gl.isContextLost())fail('contexto WebGL perdido; recrie a simulação.');}
 function release(){
  if(released)return;released=true;
  renderer.domElement?.removeEventListener('webglcontextlost',contextLost);
  for(const resource of resources)resource.dispose();
  object.removeFromParent();object.clear();
 }
 function contextLost(){lost=true;ready=false;error='Contexto WebGL perdido; recrie a simulação.';object.visible=false;release();}
 renderer.domElement?.addEventListener('webglcontextlost',contextLost);
 function makeTarget(){
  const depth=track(new THREE.DepthTexture(nx,ny,THREE.FloatType));depth.format=THREE.DepthFormat;depth.minFilter=depth.magFilter=THREE.NearestFilter;depth.generateMipmaps=false;
  const result=track(new THREE.WebGLRenderTarget(nx,ny,{format:THREE.RGBAFormat,type:THREE.UnsignedByteType,minFilter:THREE.NearestFilter,magFilter:THREE.NearestFilter,depthBuffer:true,stencilBuffer:false,depthTexture:depth,generateMipmaps:false}));
  result.texture.colorSpace=THREE.NoColorSpace;targets.push(result);return result;
 }
 try{
  const workTarget=makeTarget();currentTarget=workTarget;
  const geometry=track(quadGeometry(true)),starts=new Float32Array(count*3),ends=new Float32Array(count*3),chronology=new Float32Array(count);
  for(let i=0,k=0;i<moves.length;i++){
   const move=moves[i];if(RAPIDS.has(move[0]))continue;
   starts.set([move[1]-config.x0,move[2]-config.y0,move[3]],k*3);
   ends.set([move[4]-config.x0,move[5]-config.y0,move[6]],k*3);chronology[k]=i;k++;
  }
  geometry.setAttribute('moveA',new THREE.InstancedBufferAttribute(starts,3));
  geometry.setAttribute('moveB',new THREE.InstancedBufferAttribute(ends,3));
  geometry.setAttribute('moveIndex',new THREE.InstancedBufferAttribute(chronology,1));
  const sweepMaterial=track(new THREE.RawShaderMaterial({glslVersion:THREE.GLSL3,vertexShader:sweepVertex,fragmentShader:sweepFragment,uniforms:{uSize:{value:new THREE.Vector2(width,height)},uCellSize:{value:new THREE.Vector2(dx,dy)},uRadius:{value:config.diameter/2},uBottom:{value:config.bottom},uTop:{value:config.top},uFullIndex:{value:0},uFraction:{value:0}},depthTest:true,depthWrite:true,depthFunc:THREE.LessDepth,colorWrite:false,blending:THREE.NoBlending,toneMapped:false}));
  const sweeps=new THREE.Mesh(geometry,sweepMaterial);sweeps.frustumCulled=false;
  const sweepScene=new THREE.Scene();sweepScene.add(sweeps);const passCamera=new THREE.Camera();
  const emptyEpsilon=Math.max((config.top-config.bottom)*2e-7,1e-7);
  const visualMaterial=track(new THREE.ShaderMaterial({vertexShader:visualVertex,fragmentShader:visualFragment(nx+ny+2),uniforms:{uDepth:{value:workTarget.depthTexture},uSize:{value:new THREE.Vector2(width,height)},uCellSize:{value:new THREE.Vector2(dx,dy)},uResolution:{value:new THREE.Vector2(nx,ny)},uBottom:{value:config.bottom},uTop:{value:config.top},uPhysicalBottom:{value:physicalBottom},uEmptyEpsilon:{value:emptyEpsilon},uBaseColor:{value:new THREE.Color(config.gpu_color??0xeadfc8)},uCameraLocal:{value:new THREE.Vector3()},uOrthoDirection:{value:new THREE.Vector3()},uInverseModel:{value:new THREE.Matrix4()},uModel:{value:new THREE.Matrix4()}},side:THREE.BackSide,depthTest:true,depthWrite:true,blending:THREE.NoBlending,toneMapped:true}));
  const box=track(new THREE.BoxGeometry(width,height,config.top-physicalBottom));box.translate(width/2,height/2,(config.top+physicalBottom)/2);
  const visual=new THREE.Mesh(box,visualMaterial);visual.position.set(config.x0,config.y0,0);visual.name='GPU stock raycast';object.add(visual);
  const worldDirection=new THREE.Vector3(),worldCamera=new THREE.Vector3();
  visual.onBeforeRender=(owner,scene,camera)=>{
   const inverse=visualMaterial.uniforms.uInverseModel.value.copy(visual.matrixWorld).invert();
   visualMaterial.uniforms.uModel.value.copy(visual.matrixWorld);
   camera.getWorldPosition(worldCamera);visualMaterial.uniforms.uCameraLocal.value.copy(worldCamera).applyMatrix4(inverse);
   camera.getWorldDirection(worldDirection);visualMaterial.uniforms.uOrthoDirection.value.copy(worldDirection).transformDirection(inverse);
  };
  const sampleTarget=track(new THREE.WebGLRenderTarget(SAMPLE_LIMIT,1,{format:THREE.RGBAFormat,type:THREE.UnsignedByteType,minFilter:THREE.NearestFilter,magFilter:THREE.NearestFilter,depthBuffer:false,stencilBuffer:false}));
  sampleTarget.texture.colorSpace=THREE.NoColorSpace;
  const cells=Array.from({length:SAMPLE_LIMIT},()=>new THREE.Vector2());
  const sampleMaterial=track(new THREE.RawShaderMaterial({glslVersion:THREE.GLSL3,vertexShader:sampleVertex,fragmentShader:sampleFragment,uniforms:{uDepth:{value:workTarget.depthTexture},uCells:{value:cells}},depthTest:false,depthWrite:false,blending:THREE.NoBlending,toneMapped:false}));
  const sampleMesh=new THREE.Mesh(track(quadGeometry()),sampleMaterial);sampleMesh.frustumCulled=false;
  const sampleScene=new THREE.Scene();sampleScene.add(sampleMesh);
  function bind(renderTarget){
   // setViewport() scales by renderer.pixelRatio even with an offscreen target.
   // Target-owned physical-pixel viewports avoid a doubled/subsampled heightmap.
   renderTarget.viewport.set(0,0,renderTarget.width,renderTarget.height);renderTarget.scissorTest=false;
   renderer.setRenderTarget(renderTarget);
   if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)fail('framebuffer de profundidade incompleto neste driver.');
  }
  function draw(renderTarget,value,compileEmpty=false){
   const started=now(),full=Math.floor(value),fraction=value-full;
   let lo=0,hi=count;while(lo<hi){const middle=(lo+hi)>>>1;if(chronology[middle]<full+(fraction>0?1:0))lo=middle+1;else hi=middle;}
   geometry.instanceCount=compileEmpty?Math.min(1,count):lo;
   sweepMaterial.uniforms.uFullIndex.value=full;sweepMaterial.uniforms.uFraction.value=fraction;
   bind(renderTarget);renderer.setClearColor(0,1);renderer.clear(true,true,false);
   if(geometry.instanceCount)renderer.render(sweepScene,passCamera);
   builds++;lastBuildMs=now()-started;
  }
  function state(){
   return {available:!disposed&&!lost&&!gl.isContextLost(),backend:'webgl2-depth-raycast',generation,target,ready:ready&&!disposed&&!lost,resolution:[nx,ny],nx,ny,dx_mm:dx,dy_mm:dy,top_mm:config.top,bottom_mm:config.bottom,physical_bottom_mm:physicalBottom,last_seek_ms:lastSeekMs,last_build_ms:lastBuildMs,last_sample_ms:lastSampleMs,timing_semantics:'CPU command submission; sample includes GPU readback',ready_semantics:'commands_submitted',builds,seeks,cache_hits:cacheHits,final_ready:!!finalTarget,cutting_moves:count,total_moves:moves.length,gpu_memory_bytes:targets.length*targetBytes+attributeBytes+SAMPLE_LIMIT*4,memory_budget_bytes:budgetBytes,dda_max_steps:nx+ny+2,...rendererInfo,error};
  }
  function seek(value){
   ensure();if(!finite(value))fail('target deve ser um número finito.');
   const started=now(),next=Math.max(0,Math.min(moves.length,value));seeks++;
   if(ready&&next===target){cacheHits++;lastSeekMs=now()-started;return state();}
   ready=false;
   try{
    if(next===moves.length&&finalTarget){currentTarget=finalTarget;cacheHits++;}
    else{savedRenderer(renderer,gl,()=>draw(workTarget,next));currentTarget=workTarget;}
    target=next;visualMaterial.uniforms.uDepth.value=currentTarget.depthTexture;ready=true;error=null;
   }catch(failure){error=failure.message;object.visible=false;throw failure;}
   finally{lastSeekMs=now()-started;}
   return state();
  }
  function prepareFinal(){
   ensure();if(finalTarget)return state();
   if(targetBytes*2+attributeBytes+4096>budgetBytes)return {...state(),precompute_skipped:'memory_budget'};
   const candidate=makeTarget();
   savedRenderer(renderer,gl,()=>draw(candidate,moves.length));finalTarget=candidate;
   return state();
  }
  function sample(points){
   ensure();if(!ready)fail('superfície ainda não submetida.');
   if(!Array.isArray(points)||points.length<1||points.length>SAMPLE_LIMIT||points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(finite)))fail('points deve conter de 1 a 64 pares [x, y] finitos, em mm.');
   const started=now();
   const requested=points.map(([x,y],index)=>{
    if(x<config.x0||x>config.x1||y<config.y0||y>config.y1)fail(`ponto [${x}, ${y}] fora dos limites do bruto.`);
    const i=Math.min(nx-1,Math.floor((x-config.x0)/dx)),j=Math.min(ny-1,Math.floor((y-config.y0)/dy));cells[index].set(i,j);
    return {requested_mm:[x,y],center_mm:[config.x0+(i+.5)*dx,config.y0+(j+.5)*dy]};
   });
   const pixels=new Uint8Array(points.length*4);
   savedRenderer(renderer,gl,()=>{
    sampleMaterial.uniforms.uDepth.value=currentTarget.depthTexture;sampleMaterial.uniformsNeedUpdate=true;
    bind(sampleTarget);renderer.render(sampleScene,passCamera);renderer.readRenderTargetPixels(sampleTarget,0,0,points.length,1,pixels);
   });
   const bytes=new DataView(pixels.buffer,pixels.byteOffset,pixels.byteLength);
   const samples=requested.map((record,index)=>{
    const depth=bytes.getFloat32(index*4,false);
    if(!Number.isFinite(depth)||depth<0||depth>1)fail('amostra de profundidade inválida.');
    const z=config.bottom+depth*(config.top-config.bottom);
    return {...record,z_mm:z,removed_depth_mm:Math.max(0,config.top-z)};
   });
   lastSampleMs=now()-started;
   return {top_mm:config.top,bottom_mm:config.bottom,dx_mm:dx,dy_mm:dy,samples};
  }
  // Compile and validate all three programs before reporting this backend ready.
  // Initial visual render targets the tiny diagnostic framebuffer, never screen.
  savedRenderer(renderer,gl,()=>{
   draw(workTarget,0,true);
   const validationScene=new THREE.Scene();validationScene.add(object);
   const span=Math.max(width,height,config.top-physicalBottom),camera=new THREE.OrthographicCamera(-width/2,width/2,height/2,-height/2,.01,span*4+1);
   camera.position.set(config.x0+width/2,config.y0+height/2,config.top+span);camera.lookAt(config.x0+width/2,config.y0+height/2,physicalBottom);camera.updateMatrixWorld();
   bind(sampleTarget);renderer.clear(true,false,false);renderer.render(validationScene,camera);validationScene.remove(object);
   cells[0].set(0,0);sampleMaterial.uniforms.uDepth.value=workTarget.depthTexture;renderer.render(sampleScene,passCamera);
   const check=new Uint8Array(4);renderer.readRenderTargetPixels(sampleTarget,0,0,1,1,check);
   if(new DataView(check.buffer).getFloat32(0,false)!==1)fail('a leitura da textura de profundidade não passou na verificação inicial.');
  });
  ready=true;
  return {object,seek,state,sample,prepareFinal,dispose(){if(disposed)return;disposed=true;ready=false;release();}};
 }catch(failure){error=failure.message;ready=false;release();throw failure;}
}
