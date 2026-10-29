// Continuous flat-tip sweeps for display, independent of the diagnostic grid.
// Each sweep is the convex hull of the endpoint disks and their vertical
// extensions above stock. This also models a linear XYZ ramp, not just XY.
const rapid=new Set(['travel','retract','clearance_adjust','approach_rapid']);
// A partial or completed rapid never removes stock. Canonicalize only these
// trailing moves; a genuine cut fraction must remain exact and chronological.
export function normalizeSolidTarget(moves,target=moves.length){
 if(!Number.isFinite(target))throw Error('Posição da reconstrução inválida.');
 let end=Math.max(0,Math.min(moves.length,target));
 if(end%1&&rapid.has(moves[Math.floor(end)]?.[0]))end=Math.floor(end);
 while(Number.isInteger(end)&&end>0&&rapid.has(moves[end-1]?.[0]))end--;
 return end;
}

export function cloneSolidMesh(mesh){
 return {...mesh,positions:mesh.positions.slice(),normals:mesh.normals.slice(),indices:mesh.indices.slice()};
}

// Cache display meshes, not live WASM solids. Every result owns its buffers,
// so transfer to the UI can never detach a retained reconstruction.
export class SolidMeshCache{
 constructor(build,config,moves,{maxEntries=8,maxBytes=64*1024*1024}={}){
  if(typeof build!=='function'||!config||!Array.isArray(moves))throw Error('Reconstrução sem configuração válida.');
  if(!Number.isInteger(maxEntries)||maxEntries<0||!Number.isFinite(maxBytes)||maxBytes<0)throw Error('Limite do cache de superfície inválido.');
  this.build=build;this.config=config;this.moves=moves;this.maxEntries=maxEntries;this.maxBytes=maxBytes;
  this.finalKey=normalizeSolidTarget(moves,moves.length);this.entries=new Map();this.bytes=0;
  this.builds=0;this.hits=0;this.evictions=0;this.uncachedBuilds=0;
 }
 stats(){return {builds:this.builds,hits:this.hits,entries:this.entries.size,bytes:this.bytes,
  budget_bytes:this.maxBytes,max_entries:this.maxEntries,evictions:this.evictions,
  uncached_builds:this.uncachedBuilds,final_target:this.finalKey,final_cached:this.entries.has(this.finalKey)};}
 _put(key,mesh){
  const size=mesh.positions.byteLength+mesh.normals.byteLength+mesh.indices.byteLength;
  const pinned=this.entries.get(this.finalKey);
  if(!this.maxEntries||size>this.maxBytes||(key!==this.finalKey&&pinned&&
      (this.maxEntries<2||size+pinned.size>this.maxBytes))){this.uncachedBuilds++;return;}
  while(this.entries.size>=this.maxEntries||this.bytes+size>this.maxBytes){
   const victim=[...this.entries.keys()].find(candidate=>candidate!==this.finalKey);
   if(victim===undefined){this.uncachedBuilds++;return;}
   this.bytes-=this.entries.get(victim).size;this.entries.delete(victim);this.evictions++;
  }
  this.entries.set(key,{mesh,size});this.bytes+=size;
 }
 get(target=this.moves.length,onProgress=()=>{}){
  const key=normalizeSolidTarget(this.moves,target);let entry=this.entries.get(key),cacheHit=!!entry;
  if(entry){this.entries.delete(key);this.entries.set(key,entry);this.hits++;}
  else{
   this.builds++;const mesh=this.build(this.config,this.moves,key,onProgress);entry={mesh};this._put(key,mesh);
  }
  return {...cloneSolidMesh(entry.mesh),cache_key:key,cache_hit:cacheHit,stats:this.stats()};
 }
}

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
 let solid;try{solid=base.translate([config.x0,config.y0,config.bottom]);}finally{base.delete();}
 const flush=()=>{
  if(!batch.length)return;
  let cut=null,next=null;
  try{
   cut=M.union(batch);next=solid.subtract(cut);
   // Evaluate before releasing the operands of the lazy boolean tree.
   const status=next.status();if(status!=='NoError')throw Error('Falha ao reconstruir a superfície sólida: '+status);
   const previous=solid;solid=next;next=null;previous.delete();
  }finally{
   next?.delete();cut?.delete();for(const item of batch)item.delete();batch.length=0;
  }
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
