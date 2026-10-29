// Discrete rotations and visual datum anchors. Backend inspection remains
// the authority for the transformed STL, dimensions and machining setup.
import {roundPolygon} from './region_shapes.js';
const IDENTITY=[[1,0,0],[0,1,0],[0,0,1]];
const QUARTER={x:[[1,0,0],[0,0,-1],[0,1,0]],y:[[0,0,1],[0,1,0],[-1,0,0]],z:[[0,-1,0],[1,0,0],[0,0,1]]};
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const vector=(m,v)=>m.map(row=>dot(row,v));
const transpose=m=>m[0].map((_,i)=>m.map(row=>row[i]));
const multiply=(a,b)=>a.map(row=>transpose(b).map(column=>dot(row,column)));
const add=(a,b)=>a.map((v,i)=>v+b[i]);
const subtract=(a,b)=>a.map((v,i)=>v-b[i]);
const anchor=(low,high,fraction)=>low+(high-low)*fraction;
const nearZero=value=>Math.abs(value)<1e-6;
export const ORIGIN_REFERENCES={
 left:{label:'Esquerda',anchor:[0,.5],description:'X mínimo · Y central'},
 right:{label:'Direita',anchor:[1,.5],description:'X máximo · Y central'},
 front:{label:'Frente',anchor:[.5,0],description:'X central · Y mínimo'},
 back:{label:'Trás',anchor:[.5,1],description:'X central · Y máximo'},
 center:{label:'Centro',anchor:[.5,.5],description:'X central · Y central'}
};
export function originReferences(bounds){
 if(!bounds||!Array.isArray(bounds.minimum)||!Array.isArray(bounds.maximum)
   ||bounds.minimum.length!==3||bounds.maximum.length!==3
   ||![...bounds.minimum,...bounds.maximum].every(Number.isFinite)
   ||bounds.minimum.some((v,i)=>v>bounds.maximum[i]))throw Error('Limites da peça indisponíveis.');
 return Object.entries(ORIGIN_REFERENCES).map(([id,r])=>({id,...r,anchor:[...r.anchor],
  point_mm:r.anchor.map((f,i)=>anchor(bounds.minimum[i],bounds.maximum[i],f))}));
}
export function originReferenceId(bounds){
 if(!bounds)return null;
 return originReferences(bounds).find(r=>r.point_mm.every(nearZero))?.id??null;
}

export function placementOrigin(bounds){
 if(!bounds)return {xy:null,z:null};
 const {minimum:lo,maximum:hi}=bounds;
 const fractions=[.5,0,1];
 const u=fractions.find(f=>nearZero(anchor(lo[0],hi[0],f)));
 const v=fractions.find(f=>nearZero(anchor(lo[1],hi[1],f)));
 const z=nearZero(hi[2])?'top':nearZero(lo[2])?'bottom':nearZero((lo[2]+hi[2])/2)?'center':null;
 return {xy:u===undefined||v===undefined?null:[u,v],z};
}

export function placementAction(current,mesh,triangles,action){
 if(!mesh?.bounds_mm||!mesh.transform||!action||typeof action!=='object')throw Error('Abra uma peça para posicionar.');
 const result={units:current.units,rotation:mesh.transform.rotation.map(row=>[...row]),
  translation_mm:[...mesh.transform.translation_mm],xy_origin:'keep',z_origin:'keep'};
 const {minimum:lo,maximum:hi}=mesh.bounds_mm;
 if(action.kind==='origin_xy'){
  if(!Array.isArray(action.anchor)||action.anchor.length!==2||action.anchor.some(v=>![0,.5,1].includes(v)))throw Error('Escolha um dos nove pontos de origem XY.');
  for(let i=0;i<2;i++)result.translation_mm[i]-=anchor(lo[i],hi[i],action.anchor[i]);
 }else if(action.kind==='origin_point'){
  if(!Array.isArray(action.point_mm)||action.point_mm.length!==3||!action.point_mm.every(Number.isFinite))throw Error('Informe o ponto de referência X, Y e Z em mm.');
  const axes=action.axes??'xyz';if(!['xy','z','xyz'].includes(axes))throw Error('Escolha os eixos xy, z ou xyz.');
  for(const i of axes==='xy'?[0,1]:axes==='z'?[2]:[0,1,2])result.translation_mm[i]-=action.point_mm[i];
 }else if(action.kind==='origin_z'){
  const fractions={top:1,center:.5,bottom:0};
  if(!Object.hasOwn(fractions,action.anchor))throw Error('Origem Z inválida.');
  result.translation_mm[2]-=anchor(lo[2],hi[2],fractions[action.anchor]);
 }else if(action.kind==='translate'){
  if(!Array.isArray(action.delta_mm)||action.delta_mm.length!==3||!action.delta_mm.every(Number.isFinite))throw Error('Informe deslocamentos X, Y e Z finitos em mm.');
  result.translation_mm=add(result.translation_mm,action.delta_mm);
 }else if(['rotate','flip','reset'].includes(action.kind)){
  let rotation;
  if(action.kind==='reset')rotation=transpose(result.rotation);
  else{
   const axis=action.kind==='flip'?'x':action.axis,turns=action.kind==='flip'?2:action.turns;
   if(!Object.hasOwn(QUARTER,axis))throw Error('Escolha o eixo X, Y ou Z.');
   if(action.kind==='rotate'&&action.angle_deg!==undefined){
    if(![-45,45].includes(action.angle_deg)||action.turns!==undefined)throw Error('Informe angle_deg de -45 ou 45, sem turns.');
    const c=Math.SQRT1_2,s=Math.sign(action.angle_deg)*c;
    rotation={x:[[1,0,0],[0,c,-s],[0,s,c]],y:[[c,0,s],[0,1,0],[-s,0,c]],z:[[c,-s,0],[s,c,0],[0,0,1]]}[axis];
   }else{
    if(!Number.isInteger(turns)||Math.abs(turns)>4)throw Error('Use incrementos inteiros de 90° ou angle_deg de -45/45.');
    rotation=IDENTITY;
    for(let i=0;i<((turns%4)+4)%4;i++)rotation=multiply(QUARTER[axis],rotation);
   }
  }
  if(!triangles?.length||triangles.length%3!==0)throw Error('Vértices da peça indisponíveis.');
  const center=lo.map((v,i)=>(v+hi[i])/2);
  const correction=subtract(center,vector(rotation,center));
  result.rotation=multiply(rotation,result.rotation);
  result.translation_mm=add(vector(rotation,result.translation_mm),correction);
  const lower=[Infinity,Infinity,Infinity],upper=[-Infinity,-Infinity,-Infinity];
  for(let i=0;i<triangles.length;i+=3){
   const point=add(vector(rotation,[triangles[i],triangles[i+1],triangles[i+2]]),correction);
   for(let j=0;j<3;j++){lower[j]=Math.min(lower[j],point[j]);upper[j]=Math.max(upper[j],point[j]);}
  }
  const origin=placementOrigin(mesh.bounds_mm);
  const spinOnTable=action.kind==='rotate'&&action.axis==='z'&&action.angle_deg!==undefined;
  if(origin.xy&&!spinOnTable)for(let i=0;i<2;i++)result.translation_mm[i]-=anchor(lower[i],upper[i],origin.xy[i]);
  if(origin.z&&!spinOnTable)result.translation_mm[2]-=anchor(lower[2],upper[2],{top:1,center:.5,bottom:0}[origin.z]);
 }else throw Error('Ação de posicionamento desconhecida.');
 return result;
}

export function nearestOutlinePoint(point,loops){
 if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite))throw Error('Informe X e Y do ponto na vista de topo.');
 let best=null;
 for(let li=0;li<loops.length;li++)for(let i=0;i<loops[li].length;i++){
  const a=loops[li][i],b=loops[li][(i+1)%loops[li].length],d=b.map((v,j)=>v-a[j]),length=d[0]**2+d[1]**2;
  if(!length)continue;
  const t=Math.max(0,Math.min(1,((point[0]-a[0])*d[0]+(point[1]-a[1])*d[1])/length));
  const hit=a.map((v,j)=>v+t*d[j]),distance=Math.hypot(hit[0]-point[0],hit[1]-point[1]);
  if(!best||distance<best.distance_mm)best={point_mm:hit,distance_mm:distance,contour:li,edge:i};
 }
 if(!best)throw Error('O modelo não tem borda projetada disponível. Use as coordenadas ou os nove pontos de referência.');
 return best;
}

export function magneticOutlinePoint(point,loops,bounds,distance){
 if(!Number.isFinite(distance)||distance<0)throw Error('Distância de atração inválida.');
 const nearest=nearestOutlinePoint(point,loops);
 if(distance===0)return nearest;
 // Only magnetize box references that actually lie on the outer contour.
 // A triangle/L-shaped piece may have a box midpoint outside its material.
 const tolerance=1e-5;
 const candidates=originReferences(bounds).filter(r=>r.id!=='center').map(r=>({...r,
  distance_mm:Math.hypot(point[0]-r.point_mm[0],point[1]-r.point_mm[1])}))
  .filter(r=>r.distance_mm<=distance&&nearestOutlinePoint(r.point_mm,loops).distance_mm<=tolerance)
  .sort((a,b)=>a.distance_mm-b.distance_mm);
 return candidates.length?{...nearest,point_mm:candidates[0].point_mm,distance_mm:candidates[0].distance_mm,anchor_id:candidates[0].id}:nearest;
}

export function shiftWorkFrame(scene,inspected,delta){
 const [dx,dy,dz]=delta,shiftXY=p=>p.map(v=>[v[0]+dx,v[1]+dy]);
 const settings=structuredClone(scene.settings),operations=structuredClone(scene.operations);
 for(const key of ['stock_top_mm','bottom_mm','obstacle_top_mm'])if(settings[key]!=null)settings[key]+=dz;
 // Phase is the Y coordinate in the rotated raster frame, not world Y.
 const angle=(settings.raster_angle_deg??0)*Math.PI/180;
 if(settings.raster_origin_y_mm!=null)settings.raster_origin_y_mm+=-dx*Math.sin(angle)+dy*Math.cos(angle);
 for(const key of ['boundaries_mm','exclusions_mm'])if(settings[key]!=null)settings[key]=settings[key].map(shiftXY);
 for(const key of ['cutout_bottom_mm','drill_bottom_mm','smart_stock_bottom_mm'])if(operations[key]!=null)operations[key]+=dz;
 const stock=scene.stock?{...scene.stock,x0:scene.stock.x0+dx,x1:scene.stock.x1+dx,y0:scene.stock.y0+dy,y1:scene.stock.y1+dy}:null;
 const windows=scene.windows?.map(b=>[b[0]+dx,b[1]+dy,b[2]+dx,b[3]+dy])??null;
 return {...scene,...inspected,settings,operations,stock,windows,motion:null,project_id:null};
}

export function secondSideState(state,fixture){
 if(!fixture||!Number.isFinite(fixture.diameter_mm)||fixture.diameter_mm<.1||!Number.isFinite(fixture.height_mm)||fixture.height_mm<0)throw Error('Informe diâmetro da área protegida (mínimo 0,1 mm) e altura da fixação acima da peça.');
 const b=state.mesh.bounds_mm,center=b.minimum.slice(0,2).map((v,i)=>(v+b.maximum[i])/2);
 const exclusion=roundPolygon(center,fixture.diameter_mm/2,undefined,'keepout');
 const smartReleased=state.operations.machining_mode==='smart'&&state.operations.smart_part_released===true;
 return {...state,settings:{...state.settings,domain_mode:'silhouette',
  exclusions_mm:[exclusion],obstacle_top_mm:state.settings.stock_top_mm+fixture.height_mm},operations:{...state.operations,
  machining_mode:smartReleased?'smart':'manual',smart_part_released:true,roughing_enabled:true,cutout_enabled:smartReleased,drill_enabled:false,
  order:'roughing_then_cutout',operation_sequence:['roughing','drill','cutout'],smart_stock_bottom_mm:smartReleased?state.operations.smart_stock_bottom_mm:null}};
}

export function samePlacement(candidate,current,mesh){
 return candidate.units===current.units&&candidate.rotation.every((row,i)=>row.every((v,j)=>Math.abs(v-mesh.transform.rotation[i][j])<1e-10))
  &&candidate.translation_mm.every((v,i)=>Math.abs(v-mesh.transform.translation_mm[i])<1e-10);
}
