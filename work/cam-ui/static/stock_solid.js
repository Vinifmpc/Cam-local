// Continuous flat-tip sweeps for display, independent of the diagnostic grid.
// Each sweep is the convex hull of the endpoint disks and their vertical
// extensions above stock. This also models a linear XYZ ramp, not just XY.
const rapid=new Set(['travel','retract','clearance_adjust']);
export function sweptSegments(config,moves,target=moves.length){
 const end=Math.max(0,Math.min(moves.length,target)),groups=new Map();
 for(let i=0;i<Math.ceil(end);i++){
  const m=moves[i];if(rapid.has(m[0]))continue;
  let a=m.slice(1,4),b=m.slice(4,7);
  if(i===Math.floor(end)&&end%1)b=a.map((v,k)=>v+(b[k]-v)*(end%1));
  if(![...a,...b].every(Number.isFinite))throw Error('Movimento não finito.');
  if(Math.min(a[2],b[2])>=config.top)continue;
  if(Math.max(a[0],b[0])+config.diameter/2<config.x0||Math.min(a[0],b[0])-config.diameter/2>config.x1||
     Math.max(a[1],b[1])+config.diameter/2<config.y0||Math.min(a[1],b[1])-config.diameter/2>config.y1)continue;
  // Clip the center line where it enters stock; no future path is credited.
  if(a[2]>config.top){const t=(config.top-a[2])/(b[2]-a[2]);a=a.map((v,k)=>v+t*(b[k]-v));}
  if(b[2]>config.top){const t=(config.top-a[2])/(b[2]-a[2]);b=a.map((v,k)=>v+t*(b[k]-v));}
  if(a[0]>b[0]||(a[0]===b[0]&&a[1]>b[1]))[a,b]=[b,a];
  if(a[0]===b[0]&&a[1]===b[1])a[2]=b[2]=Math.min(a[2],b[2]);
  const key=[a[0],a[1],b[0],b[1]].join(','),prior=groups.get(key)||[];
  if(prior.some(p=>p[0][2]<=a[2]&&p[1][2]<=b[2]))continue;
  groups.set(key,[...prior.filter(p=>!(a[2]<=p[0][2]&&b[2]<=p[1][2])),[a,b]]);
 }
 return [...groups.values()].flat();
}
export function buildSolid(module,config,moves,target=moves.length,onProgress=()=>{}){
 const {Manifold:M}=module,r=config.diameter/2;
 const sides=Math.max(24,Math.min(256,Math.ceil(Math.PI/Math.acos(Math.max(-1,1-.005/r))/4)*4));
 const circle=Array.from({length:sides},(_,i)=>[r*Math.cos(2*Math.PI*i/sides),r*Math.sin(2*Math.PI*i/sides)]);
 const segments=sweptSegments(config,moves,target),batch=[];
 if(segments.length>10000)throw Error('Percurso grande demais para a superfície detalhada nesta versão.');
 const base=M.cube([config.x1-config.x0,config.y1-config.y0,config.top-config.bottom]);
 let solid=base.translate([config.x0,config.y0,config.bottom]);base.delete();
 const flush=()=>{
  if(!batch.length)return;
  const cut=M.union(batch),next=solid.subtract(cut);
  // Evaluate before releasing the operands of the lazy boolean tree.
  if(next.status()!=='NoError')throw Error('Falha ao reconstruir a superfície sólida: '+next.status());
  solid.delete();cut.delete();for(const item of batch)item.delete();batch.length=0;solid=next;
 };
 try{
  for(let i=0;i<segments.length;i++){
   const [a,b]=segments[i],points=[];
   for(const p of [a,b])for(const q of circle){points.push([p[0]+q[0],p[1]+q[1],p[2]],[p[0]+q[0],p[1]+q[1],config.top+1]);}
   batch.push(M.hull(points));
   if(batch.length>=64){flush();onProgress((i+1)/segments.length);}
  }
  flush();
  const normalSolid=solid.calculateNormals(0,35);
  try{
   const raw=normalSolid.getMesh(),positions=new Float32Array(raw.numVert*3),normals=new Float32Array(raw.numVert*3);
   for(let i=0;i<raw.numVert;i++)for(let k=0;k<3;k++){
    positions[i*3+k]=raw.vertProperties[i*raw.numProp+k];
    normals[i*3+k]=raw.vertProperties[i*raw.numProp+3+k];
   }
   return {positions,normals,indices:new Uint32Array(raw.triVerts),volume:solid.volume(),
    segments:segments.length,tool_sides:sides,maximum_radial_chord_error_mm:r*(1-Math.cos(Math.PI/sides))};
  }finally{normalSolid.delete();}
 }finally{solid.delete();for(const item of batch)item.delete();}
}
