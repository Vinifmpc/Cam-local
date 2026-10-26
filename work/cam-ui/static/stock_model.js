// Discrete 2.5D swept flat-tip stock. Exact segment/disk minimum at each grid
// sample, approximate between samples. Rapids never remove material.
export function activeStockBottom(roughingEnabled,roughBottom,cutoutEnabled,cutoutBottom,drillEnabled=false,drillBottom=null){
 const depths=[];
 if(roughingEnabled)depths.push(roughBottom);
 if(cutoutEnabled)depths.push(cutoutBottom);
 if(drillEnabled)depths.push(drillBottom);
 if(!depths.length||!depths.every(Number.isFinite))throw Error('Defina a profundidade das operações ativas.');
 return Math.min(...depths);
}
// The row stride is part of the mesh topology, even when nx*ny is unchanged.
export function stockGridIndices(nx,ny){
 const indices=[];
 for(let j=0;j<ny-1;j++)for(let i=0;i<nx-1;i++){
  const n=j*nx+i;indices.push(n,n+1,n+nx,n+1,n+nx+1,n+nx);
 }
 return indices;
}
// Read only the requested cells from an already received worker snapshot.
// Report the cell centers explicitly: this is a sampled 2.5D simulation,
// not interpolation or a new material-removal calculation.
export function sampleStockGrid(snapshot,points){
 const {config:c,nx,ny,dx,dy,heights}=snapshot||{};
 if(!c||![c.x0,c.y0,c.x1,c.y1,c.top,c.bottom,dx,dy].every(Number.isFinite)||
   !Number.isInteger(nx)||!Number.isInteger(ny)||nx<1||ny<1||dx<=0||dy<=0||
   c.x1<=c.x0||c.y1<=c.y0||c.top<=c.bottom||heights?.length!==nx*ny)
  throw Error('Grade da simulação indisponível para amostragem.');
 if(!Array.isArray(points)||points.length<1||points.length>64||points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)))
  throw Error('points deve conter de 1 a 64 pares [x, y] finitos, em mm.');
 const samples=points.map(([x,y])=>{
  if(x<c.x0||x>c.x1||y<c.y0||y>c.y1)throw Error(`Ponto [${x}, ${y}] fora dos limites do bruto.`);
  const i=Math.min(nx-1,Math.floor((x-c.x0)/dx)),j=Math.min(ny-1,Math.floor((y-c.y0)/dy));
  const z=heights[j*nx+i];
  if(!Number.isFinite(z))throw Error('Altura inválida na grade da simulação.');
  return {requested_mm:[x,y],center_mm:[c.x0+(i+.5)*dx,c.y0+(j+.5)*dy],z_mm:z,removed_depth_mm:Math.max(0,c.top-z)};
 });
 return {top_mm:c.top,bottom_mm:c.bottom,dx_mm:dx,dy_mm:dy,samples};
}
export function insidePolygon(x,y,polygon){
 let inside=false;
 for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
  const a=polygon[i],b=polygon[j];
  if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;
 }
 return inside;
}
export class StockModel{
 constructor(c){
  if(![c.x0,c.y0,c.x1,c.y1,c.top,c.bottom,c.step,c.diameter].every(Number.isFinite)||
     c.x1<=c.x0||c.y1<=c.y0||c.top<=c.bottom||c.step<=0||c.diameter<=0)throw Error('Bruto, diâmetro ou resolução inválidos.');
  this.c={...c,cutoutUseRegions:false};this.nx=Math.ceil((c.x1-c.x0)/c.step);this.ny=Math.ceil((c.y1-c.y0)/c.step);
  if(this.nx*this.ny>300000)throw Error('Grade maior que 300.000 pontos. Aumente o passo da grade.');
  if(this.nx<2||this.ny<2)throw Error('O bruto precisa ter pelo menos duas amostras por eixo.');
  this.dx=(c.x1-c.x0)/this.nx;this.dy=(c.y1-c.y0)/this.ny;
  this.heights=new Float32Array(this.nx*this.ny);this.protected=new Uint8Array(this.heights.length);
  this.hit=new Uint8Array(this.heights.length);this.volume=0;this.protectedCount=0;this.belowBottom=0;
  for(let j=0;j<this.ny;j++)for(let i=0;i<this.nx;i++){
   const x=c.x0+(i+.5)*this.dx,y=c.y0+(j+.5)*this.dy;
   const allowed=c.boundaries==null||c.boundaries.some(p=>insidePolygon(x,y,p));
   this.protected[j*this.nx+i]=!allowed||(c.exclusions||[]).some(p=>insidePolygon(x,y,p));
  }
  this.reset();
 }
 reset(){this.heights.fill(this.c.top);this.hit.fill(0);this.volume=0;this.protectedCount=0;this.belowBottom=0;}
 apply(m){
  if(['travel','retract','clearance_adjust'].includes(m[0]))return;
  const ax=m[1],ay=m[2],az=m[3],bx=m[4],by=m[5],bz=m[6];
  if(![ax,ay,az,bx,by,bz].every(Number.isFinite))throw Error('Movimento não finito.');
  const r=this.c.diameter/2,r2=r*r,dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy;
  const x0=Math.max(0,Math.floor((Math.min(ax,bx)-r-this.c.x0)/this.dx-.5));
  const x1=Math.min(this.nx-1,Math.ceil((Math.max(ax,bx)+r-this.c.x0)/this.dx-.5));
  const y0=Math.max(0,Math.floor((Math.min(ay,by)-r-this.c.y0)/this.dy-.5));
  const y1=Math.min(this.ny-1,Math.ceil((Math.max(ay,by)+r-this.c.y0)/this.dy-.5));
  for(let j=y0;j<=y1;j++)for(let i=x0;i<=x1;i++){
   const x=this.c.x0+(i+.5)*this.dx-ax,y=this.c.y0+(j+.5)*this.dy-ay;
   let z;
   if(l2===0){if(x*x+y*y>r2)continue;z=Math.min(az,bz);}
   else{
    const t=(x*dx+y*dy)/l2,d2=Math.max(0,x*x+y*y-t*t*l2);
    if(d2>r2)continue;
    const reach=Math.sqrt(Math.max(0,(r2-d2)/l2));
    const lo=Math.max(0,t-reach),hi=Math.min(1,t+reach);if(lo>hi)continue;
    z=az+(bz-az)*(bz>=az?lo:hi);
   }
   const id=j*this.nx+i,old=this.heights[id],floor=Math.max(this.c.bottom,Math.min(this.c.top,z));
   if(floor>=old-1e-7)continue;
   if(z<this.c.bottom-1e-6)this.belowBottom++;
   this.heights[id]=floor;this.volume+=(old-this.heights[id])*this.dx*this.dy;
   if(this.protected[id]&&(m[8]==null||m[8]==='roughing')&&!this.hit[id]){this.hit[id]=1;this.protectedCount++;}
  }
 }
 clone(){const copy=Object.assign(Object.create(StockModel.prototype),this);copy.heights=this.heights.slice();copy.hit=this.hit.slice();return copy;}
 snapshot(){return {nx:this.nx,ny:this.ny,dx:this.dx,dy:this.dy,heights:new Float32Array(this.heights),
  volume:this.volume,protectedCount:this.protectedCount,belowBottom:this.belowBottom,config:this.c};}
}
// Commit only complete segments. A fractional segment is evaluated on a copy,
// so seeking backward never retains material removed by a future position.
export class StockPlayback{
 constructor(config,moves){this.model=new StockModel(config);this.moves=moves;this.applied=0;}
 seek(target){
  target=Math.max(0,Math.min(this.moves.length,target));const full=Math.floor(target),fraction=target-full;
  if(full<this.applied){this.model.reset();this.applied=0;}
  while(this.applied<full)this.model.apply(this.moves[this.applied++]);
  let current=this.model;
  if(fraction>0&&full<this.moves.length){
   current=this.model.clone();const m=this.moves[full].slice();
   for(let i=0;i<3;i++)m[i+4]=m[i+1]+fraction*(m[i+4]-m[i+1]);current.apply(m);
  }
  return current.snapshot();
 }
}
