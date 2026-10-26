// Right-angle rotations and visual datum anchors. Backend inspection remains
// the authority for the transformed STL, dimensions and machining setup.
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
   if(!Object.hasOwn(QUARTER,axis)||!Number.isInteger(turns)||Math.abs(turns)>4)throw Error('Use X, Y ou Z e incrementos inteiros de 90°.');
   rotation=IDENTITY;
   for(let i=0;i<((turns%4)+4)%4;i++)rotation=multiply(QUARTER[axis],rotation);
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
  if(origin.xy)for(let i=0;i<2;i++)result.translation_mm[i]-=anchor(lower[i],upper[i],origin.xy[i]);
  if(origin.z)result.translation_mm[2]-=anchor(lower[2],upper[2],{top:1,center:.5,bottom:0}[origin.z]);
 }else throw Error('Ação de posicionamento desconhecida.');
 return result;
}

export function samePlacement(candidate,current,mesh){
 return candidate.units===current.units&&candidate.rotation.every((row,i)=>row.every((v,j)=>Math.abs(v-mesh.transform.rotation[i][j])<1e-10))
  &&candidate.translation_mm.every((v,i)=>Math.abs(v-mesh.transform.translation_mm[i])<1e-10);
}
