// All drawing tools produce the same simple XY polygon consumed by CAM.
export const MAX_REGION_VERTICES=256;
export const SHAPE_NAMES={rectangle:'Retângulo',circle:'Círculo',ellipse:'Elipse',polygon:'Polígono',freehand:'Mão livre'};
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
export function validateRegionPolygon(input){
 if(!Array.isArray(input))throw Error('Informe os vértices da região.');
 const points=[];
 for(const p of input){
  if(!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite))throw Error('Vértice XY inválido.');
  if(!points.length||distance(points.at(-1),p)>1e-8)points.push([...p]);
 }
 if(points.length>1&&distance(points[0],points.at(-1))<=1e-8)points.pop();
 if(points.length<3)throw Error('A região precisa de pelo menos três vértices.');
 if(points.length>MAX_REGION_VERTICES)throw Error(`A região tem muitos detalhes. Use até ${MAX_REGION_VERTICES} vértices ou refaça um traço mais simples.`);
 const intersects=(a,b,c,d)=>{
  if(Math.max(Math.min(a[0],b[0]),Math.min(c[0],d[0]))>Math.min(Math.max(a[0],b[0]),Math.max(c[0],d[0]))||
     Math.max(Math.min(a[1],b[1]),Math.min(c[1],d[1]))>Math.min(Math.max(a[1],b[1]),Math.max(c[1],d[1])))return false;
  return cross(a,b,c)*cross(a,b,d)<=0&&cross(c,d,a)*cross(c,d,b)<=0;
 };
 for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
  if(j===i+1||(i===0&&j===points.length-1))continue;
  if(intersects(points[i],points[(i+1)%points.length],points[j],points[(j+1)%points.length]))throw Error('O contorno cruza a si mesmo. Remova o cruzamento ou redesenhe a região.');
 }
 const origin=points[0];let twiceArea=0;
 for(let i=0;i<points.length;i++)twiceArea+=cross(origin,points[i],points[(i+1)%points.length]);
 if(Math.abs(twiceArea)<1e-6)throw Error('Desenhe uma região com área, em vez de uma linha.');
 return points;
}
export function rectanglePolygon(a,b){
 const [x0,x1]=[a[0],b[0]].sort((x,y)=>x-y),[y0,y1]=[a[1],b[1]].sort((x,y)=>x-y);
 if(x1-x0<.05||y1-y0<.05)throw Error('O retângulo precisa ter largura e altura de pelo menos 0,05 mm.');
 return validateRegionPolygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]]);
}
export function roundPolygon(center,rx,ry=rx,kind='boundary'){
 if(!center.every(Number.isFinite)||!Number.isFinite(rx)||!Number.isFinite(ry)||rx<.05||ry<.05)throw Error('Informe centro e raio válidos; raio mínimo de 0,05 mm.');
 // At most 0.02 mm radial approximation. Keep Out circumscribes the requested
 // curve; Keep In inscribes it, preserving the requested protected boundary.
 const count=Math.max(32,Math.ceil(Math.PI/Math.acos(1/(1+.02/Math.max(rx,ry)))));
 if(count>MAX_REGION_VERTICES)throw Error('Círculo ou elipse grande demais. Use uma região menor.');
 const factor=kind==='keepout'?1/Math.cos(Math.PI/count):1;
 return validateRegionPolygon(Array.from({length:count},(_,i)=>{
  const angle=2*Math.PI*i/count;return [center[0]+Math.cos(angle)*rx*factor,center[1]+Math.sin(angle)*ry*factor];
 }));
}
function segmentDistance(p,a,b){
 const dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
 const t=length?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)):0;
 return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);
}
function simplifyOpen(points,tolerance){
 const keep=new Set([0,points.length-1]),stack=[[0,points.length-1]];
 while(stack.length){
  const [start,end]=stack.pop();let far=tolerance,index=-1;
  for(let i=start+1;i<end;i++){const d=segmentDistance(points[i],points[start],points[end]);if(d>far){far=d;index=i;}}
  if(index>=0){keep.add(index);stack.push([start,index],[index,end]);}
 }
 return [...keep].sort((a,b)=>a-b).map(i=>points[i]);
}
export function freehandPolygon(raw,tolerance=.05){
 const points=[];
 for(const p of raw){if(!p.every(Number.isFinite))throw Error('Traço inválido.');if(!points.length||distance(points.at(-1),p)>.005)points.push([...p]);}
 if(points.length>1&&distance(points[0],points.at(-1))<.05)points.pop();
 if(points.length<3)throw Error('Desenhe um contorno fechado com área.');
 let split=1;for(let i=2;i<points.length;i++)if(distance(points[0],points[i])>distance(points[0],points[split]))split=i;
 const first=simplifyOpen(points.slice(0,split+1),tolerance),second=simplifyOpen([...points.slice(split),points[0]],tolerance);
 return validateRegionPolygon([...first.slice(0,-1),...second.slice(0,-1)]);
}
export function parseRegionVertices(text){
 const lines=text.trim().split(/\r?\n/).filter(line=>line.trim());
 return validateRegionPolygon(lines.map(line=>{
  const tokens=line.trim().split(/[;\s]+/);if(tokens.length!==2)throw Error('Informe X e Y separados por espaço, um vértice por linha.');
  return tokens.map(token=>Number(token.replace(',','.')));
 }));
}
