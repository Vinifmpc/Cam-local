import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import factory from '../ui-runtime/node_modules/manifold-3d/manifold.js';
import {SolidMeshCache,normalizeSolidTarget,buildSolid} from './static/stock_solid.js';

const config={x0:0,y0:0,x1:10,y1:6,top:0,bottom:-3,diameter:2};
const cut=['cut',2,3,-2,7,3,-2,0,'roughing'];
for(const kind of ['travel','retract','clearance_adjust','approach_rapid']){
 const moves=[cut,[kind,7,3,-2,7,3,2,0,'roughing']];
 assert.equal(normalizeSolidTarget(moves,2),1);
 assert.equal(normalizeSolidTarget(moves,1.999985),1,'An incomplete rapid cannot invalidate an already complete solid');
 assert.equal(normalizeSolidTarget(moves,.999985),.999985,'Never round a genuine cut forward');
}
assert.equal(normalizeSolidTarget([cut,cut],-1),0);
assert.equal(normalizeSolidTarget([cut,cut],20),2);
for(const invalid of [NaN,Infinity,-Infinity,'1'])assert.throws(()=>normalizeSolidTarget([cut],invalid));

const module=await factory();module.setup();let builds=0;
const moves=[cut,['retract',7,3,-2,7,3,2,0,'roughing']];
const cache=new SolidMeshCache((...args)=>{builds++;return buildSolid(module,...args);},config,moves);
const final=cache.get(moves.length);
assert.equal(final.cache_hit,false);assert.equal(final.cache_key,1);
assert.ok(final.positions.length>0);assert.equal(final.stats.final_cached,true);
// Worker transfer detaches only the response, never the retained cache buffers.
const copied=structuredClone(final,{transfer:[final.positions.buffer,final.normals.buffer,final.indices.buffer]});
assert.equal(final.positions.length,0);
const returned=cache.get(1.999985);
assert.equal(returned.cache_hit,true);assert.equal(builds,1);
assert.deepEqual(returned.positions,copied.positions);assert.equal(returned.volume,copied.volume);
returned.positions[0]=9999;
assert.notEqual(cache.get(2).positions[0],9999,'A caller cannot mutate retained geometry');
const partial=cache.get(.5),empty=cache.get(0);
assert.equal(partial.cache_hit,false);assert.ok(partial.volume>copied.volume&&partial.volume<empty.volume);
assert.equal(cache.get(.5).cache_hit,true,'Returning to the same fractional cutter position reuses its exact solid');
assert.equal(cache.get(2).volume,copied.volume,'A rewind must not replace or corrupt the pinned final reconstruction');

const fakeMesh=target=>({positions:new Float32Array(9).fill(target),normals:new Float32Array(9),indices:new Uint32Array([0,1,2]),volume:target});
let syntheticBuilds=0;
const synthetic=new SolidMeshCache((_cfg,_moves,target)=>{syntheticBuilds++;return fakeMesh(target);},config,Array(8).fill(cut),{maxEntries:3,maxBytes:252});
synthetic.get(8);synthetic.get(1);synthetic.get(2);synthetic.get(1);synthetic.get(3);
assert.equal(synthetic.stats().entries,3);assert.equal(synthetic.stats().bytes,252);
assert.equal(synthetic.get(8).cache_hit,true,'Final mesh stays pinned while intermediate targets rotate through the LRU');
assert.equal(synthetic.get(2).cache_hit,false,'Least-recently-used unpinned frame was evicted');
assert.ok(synthetic.stats().bytes<=252);assert.ok(synthetic.stats().entries<=3);
const tiny=new SolidMeshCache(()=>fakeMesh(1),config,[cut],{maxEntries:8,maxBytes:80});
assert.equal(tiny.get(1).positions.length,9);assert.equal(tiny.stats().entries,0);
assert.equal(tiny.stats().uncached_builds,1,'An oversized frame is usable without breaking the cache memory budget');

// Failure paths must release every transient WASM object now that the worker
// persists instead of relying on termination to reclaim a failed boolean tree.
for(const failure of ['union','subtract','status']){
 const alive=new Set();
 function object(kind){
  const value={kind,delete(){assert.ok(alive.delete(value),'No duplicate delete');},
   translate(){return object('solid');},subtract(){if(failure==='subtract')throw Error('subtract');return object('next');},
   status(){return failure==='status'?'InvalidConstruction':'NoError';}};
  alive.add(value);return value;
 }
 const failing={Manifold:{cube:()=>object('base'),hull:()=>object('hull'),union(){if(failure==='union')throw Error('union');return object('union');}}};
 assert.throws(()=>buildSolid(failing,config,[cut]),undefined,failure);
 assert.equal(alive.size,0,'Failed boolean reconstruction must not leak live WASM objects: '+failure);
}

// Exercise the real worker protocol, including ownership transfer and dataset
// invalidation, without creating a browser or changing any machine state.
const workerSource=fs.readFileSync(new URL('./static/solid_worker.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
let workerBuilds=0,setups=0;const messages=[];
const worker=vm.createContext({SolidMeshCache,buildSolid:(_module,cfg,_moves,target)=>{workerBuilds++;return fakeMesh(target+cfg.x0);},
 factory:()=>Promise.resolve({setup(){setups++;}}),postMessage:(message,transfer=[])=>messages.push(structuredClone(message,{transfer})),setTimeout,clearTimeout});
vm.runInContext(workerSource,worker);
const send=data=>worker.onmessage({data});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
send({type:'init',generation:1,config,moves});
send({type:'build',generation:1,target:2,request_id:1,purpose:'prefetch'});await flush();
send({type:'build',generation:1,target:1.999985,request_id:2,purpose:'display'});await flush();
let solids=messages.filter(m=>m.type==='solid');
assert.equal(solids.length,2);assert.equal(solids[0].cache_hit,false);assert.equal(solids[1].cache_hit,true);
assert.equal(solids[1].target,1.999985);assert.equal(solids[1].cache_key,1);assert.equal(solids[1].request_id,2);
assert.equal(workerBuilds,1);assert.ok(solids[1].positions.length>0);
send({type:'init',generation:2,config:{...config,x0:100},moves});
send({type:'build',generation:2,target:2,request_id:3});await flush();
solids=messages.filter(m=>m.type==='solid');
assert.equal(solids.at(-1).positions[0],101);assert.equal(solids.at(-1).stats.builds,1);assert.equal(solids.at(-1).stats.hits,0);
assert.equal(workerBuilds,2);assert.equal(setups,1,'Manifold initializes once per persistent worker');
send({type:'build',generation:1,target:2,request_id:4});await flush();
assert.equal(messages.at(-1).type,'error');assert.equal(workerBuilds,2,'A stale generation cannot reuse a current dataset');
send({type:'init',generation:3,config,moves});send({type:'build',generation:3,target:2,request_id:5});
send({type:'init',generation:4,config,moves});await flush();
assert.equal(messages.some(m=>m.type==='solid'&&m.generation===3),false,'An invalidated queued build cannot publish a stale surface');
console.log('Solid cache passed: exact fractional prefix, rapid canonicalization, pinned final/LRU memory budget, transfer ownership, WASM cleanup, persistent worker protocol and generation invalidation.');
