import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {normalizeSolidTarget} from './static/stock_solid.js';

const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const text=source.slice(source.indexOf('function showStockSurface('),source.indexOf('function clearGroup('));
const workers=[],objects=new Set(),timers=new Map(),labels=new Map();let nextTimer=1;
class Geometry{
 setAttribute(){return this;}setIndex(){return this;}computeBoundingSphere(){}
 dispose(){this.disposed=true;}
}
class Material{dispose(){this.disposed=true;}}
class Mesh{constructor(geometry,material){Object.assign(this,{geometry,material,userData:{},visible:false});}}
class Worker{
 constructor(){this.calls=[];this.terminated=false;workers.push(this);}
 postMessage(data){this.calls.push(data);}
 terminate(){this.terminated=true;}
 send(data){this.onmessage({data});}
}
const ctx=vm.createContext({normalizeSolidTarget,Map,Set,Number,Math,Float32Array,Uint32Array,
 THREE:{BufferGeometry:Geometry,BufferAttribute:class{},MeshStandardMaterial:Material,Mesh},Worker,
 scene:{add:o=>objects.add(o),remove:o=>objects.delete(o)},
 $:id=>{if(!labels.has(id))labels.set(id,{textContent:''});return labels.get(id);},
 setTimeout:fn=>{const id=nextTimer++;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
vm.runInContext(`
let stockGeneration=1,stockReady=true,stockApplied=0,stockWanted=0,playing=false,busy=false,mode='paths';
let motion={moves:[['cut',0,0,-1,2,0,-1],['cut',2,0,-1,4,0,-1],['retract',4,0,-1,4,0,2]]};
let solidWorker=null,solidBusy=false,solidMesh=null,solidIndex=-1,solidGeneration=-1,solidTimer=null,stockConfig={},solidFailedIndex=null;
let solidWorkerReady=false,solidWorkerFailed=false,solidActive=null,solidDisplayWanted=null,solidRequestId=0;
let solidCache=new Map(),solidCacheBytes=0,solidMainHits=0,solidFailures=new Map();
let solidWorkerStats={builds:0,hits:0,entries:0,bytes:0};
let solidPrefetch={status:'idle',target:null,progress:0};
let gpuStock=null,gpuStockGeneration=-1,gpuStockError=null,gpuConfig=null;
const SOLID_CACHE_BYTES=64*1024*1024,SOLID_CACHE_ENTRIES=8;
let stockMesh={visible:false},stockWire={visible:false};
${text}
function seek(target){stockWanted=stockApplied=target;scheduleSolid();}
function current(){return {worker:solidWorker,cache:solidCacheState(),prefetch:{...solidPrefetch},solidIndex,solidGeneration,solidMesh,solidBusy,solidActive};}
function configure(values){if(values.mode!==undefined)mode=values.mode;if(values.playing!==undefined)playing=values.playing;if(values.target!==undefined)stockWanted=stockApplied=values.target;}
`,ctx);
function flushTimers(){for(const [id,fn]of [...timers]){timers.delete(id);fn();}}
function jobs(w){return w.calls.filter(c=>c.type==='build');}
function result(w,job,{volume=100}={}){w.send({...job,type:'solid',cache_key:normalizeSolidTarget([["cut"],["cut"],["retract"]],job.target),positions:new Float32Array(9),normals:new Float32Array(9),indices:new Uint32Array([0,1,2]),volume,stats:{builds:jobs(w).length,hits:0,entries:jobs(w).length,bytes:84*jobs(w).length}});}

ctx.prepareSolidBackground();
const first=workers[0];assert.equal(first.calls[0].type,'init');
first.send({type:'ready',generation:1,stats:{builds:0,hits:0,entries:0,bytes:0}});
assert.equal(jobs(first)[0].purpose,'prefetch');assert.equal(jobs(first)[0].target,3,'Final construction starts in path view, at cursor zero');
result(first,jobs(first)[0]);
assert.equal(ctx.current().prefetch.status,'ready');assert.equal(ctx.current().solidMesh,null,'A completed final mesh never replaces the current earlier position');
ctx.configure({mode:'stock'});ctx.seek(3);
assert.equal(ctx.current().solidIndex,3);assert.equal(ctx.current().solidMesh.userData.volume,100);
assert.equal(jobs(first).length,1,'Using the final prefetch needs no second build');
ctx.seek(2.999985);assert.equal(jobs(first).length,1,'A fractional final rapid reuses the full final surface');
assert.equal(ctx.current().solidIndex,2.999985);
ctx.configure({playing:true});ctx.cancelSolid();
assert.equal(first.terminated,false);assert.equal(ctx.current().prefetch.status,'ready');
ctx.configure({playing:false});ctx.seek(.5);flushTimers();
const oldRequest=jobs(first).at(-1);assert.equal(oldRequest.target,.5);
ctx.seek(.25);flushTimers();result(first,oldRequest,{volume:150});
assert.notEqual(ctx.current().solidIndex,.5,'An old-cursor completion is cached but never displayed at the new cursor');
const newRequest=jobs(first).at(-1);assert.equal(newRequest.target,.25);
result(first,newRequest,{volume:175});
assert.equal(ctx.current().solidIndex,.25);assert.equal(ctx.current().solidMesh.userData.volume,175);
const builds=jobs(first).length;ctx.seek(.5);assert.equal(jobs(first).length,builds);assert.equal(ctx.current().solidMesh.userData.volume,150);
ctx.seek(3);assert.equal(jobs(first).length,builds);assert.equal(ctx.current().solidMesh.userData.volume,100);
ctx.configure({mode:'paths'});ctx.cancelSolid();ctx.configure({mode:'stock'});ctx.seek(3);
assert.equal(first.terminated,false);assert.equal(jobs(first).length,builds,'Mode changes, playback and rewinds retain completed reconstructions');
const oldGeometry=ctx.current().solidMesh.geometry;
ctx.resetSolid();assert.equal(first.terminated,true);assert.equal(oldGeometry.disposed,true);assert.equal(ctx.current().cache.main_entries,0);
result(first,oldRequest);assert.equal(ctx.current().cache.main_entries,0,'A completion from an invalidated worker cannot revive cached geometry');
ctx.prepareSolidBackground();const second=workers.at(-1);second.onerror();
assert.equal(ctx.current().prefetch.status,'error','A worker failing before ready must not leave background waiting forever');
assert.equal(ctx.current().solidBusy,false);
console.log('Solid UI lifecycle passed: final background preparation, no future-state display, exact rapid/cache reuse, soft cancellation, stale reply caching, dataset invalidation and startup errors.');
