import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {visualStockConfig} from './static/stock_model.js';
import {normalizeSolidTarget} from './static/stock_solid.js';

const config={x0:-5,y0:-5,x1:15,y1:15,top:0,bottom:-3,diameter:2};
assert.equal(visualStockConfig(config,-10).bottom,-10);
assert.equal(visualStockConfig(config,-10).physical_bottom,-10,'A shallow pocket does not make a through cut');
assert.equal(visualStockConfig({...config,bottom:-12},-10).bottom,-12,'Breakthrough remains separate from physical stock');
assert.equal(visualStockConfig(config,-10,-15).physical_bottom,-15);
assert.throws(()=>visualStockConfig(config,-10,-5));

const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const block=source.slice(source.indexOf('function showStockSurface('),source.indexOf('function clearGroup('));
const labels=new Map(),objects=new Set(),instances=[],workers=[],events=new Map();
const ctx=vm.createContext({Map,Number,Math,visualStockConfig,normalizeSolidTarget,
 setTimeout:()=>1,clearTimeout(){},fmt:value=>String(value),renderer:{domElement:{addEventListener:(name,handler)=>events.set(name,handler)}},
 $:id=>{if(!labels.has(id))labels.set(id,{textContent:'',value:''});return labels.get(id);},
 bounds:()=>({minimum:[0,0,-10]}),smartModeEnabled:()=>false,
 scene:{add:o=>objects.add(o),remove:o=>objects.delete(o)},
 Worker:class{constructor(){this.calls=[];workers.push(this);}postMessage(value){this.calls.push(value);}terminate(){}},
 createGpuStock(renderer,settings,moves){
  const instance={object:{visible:false},config:settings,target:0,disposed:false,prepared:false,
   state(){return {available:!this.disposed,ready:true,target:this.target,resolution:[512,512],dx_mm:.04,final_ready:this.prepared};},
   seek(target){this.target=target;},prepareFinal(){this.prepared=true;},dispose(){this.disposed=true;}};
  instances.push(instance);return instance;
 }});
vm.runInContext(`
let stockGeneration=1,stockReady=false,stockApplied=-1,stockWanted=0,playing=false,busy=false,mode='stock';
let data={},tool={};
let motion={moves:[['cut',0,0,-1,2,0,-1],['cut',2,0,-1,4,0,-1],['retract',4,0,-1,4,0,2]]};
let stockConfig=${JSON.stringify(config)},gpuStock=null,gpuStockGeneration=-1,gpuStockError=null,gpuConfig=null;
let solidWorker=null,solidBusy=false,solidMesh=null,solidIndex=-1,solidGeneration=-1,solidTimer=null,solidFailedIndex=null;
let solidWorkerReady=false,solidWorkerFailed=false,solidActive=null,solidDisplayWanted=null,solidRequestId=0;
let solidCache=new Map(),solidCacheBytes=0,solidMainHits=0,solidFailures=new Map(),solidWorkerStats={builds:0,hits:0,entries:0,bytes:0};
let solidPrefetch={status:'idle',target:null,progress:0};const SOLID_CACHE_BYTES=67108864,SOLID_CACHE_ENTRIES=8;
let stockMesh={visible:true},stockWire={visible:true};
${block}
function seek(target){stockWanted=target;showStockSurface();}
function playback(active){playing=active;showStockSurface();}
function state(){return {gpu:gpuStockState(),prefetch:solidPrefetch,stockMesh,stockWire};}
function nextGeneration(){stockGeneration++;resetSolid();prepareSolidBackground();}
function stop(){playing=false;}
function resetStock(){nextGeneration();}
function updateCursor(){showStockSurface();}
function requestStock(){}
`,ctx);
ctx.prepareSolidBackground();
assert.equal(workers.length,0,'GPU availability avoids launching the CPU boolean reconstruction');
assert.equal(instances[0].prepared,true);assert.equal(instances[0].config.physical_bottom,-10);
assert.equal(ctx.state().gpu.ready,true,'Visual readiness is independent of the pending CPU diagnostics grid');
assert.equal(instances[0].object.visible,true);assert.equal(ctx.state().stockMesh.visible,false);
assert.match(labels.get('surfaceStatus').textContent,/GPU/);
ctx.seek(1.5);assert.equal(instances[0].target,1.5,'Cut fractions remain exact');
ctx.playback(true);assert.equal(instances[0].object.visible,true,'GPU surface remains present during playback');
ctx.seek(3);ctx.seek(.5);assert.equal(instances[0].target,.5,'Rewind never keeps future removal');
ctx.scheduleSolid();assert.equal(workers.length,0);
ctx.nextGeneration();assert.equal(instances[0].disposed,true);assert.equal(objects.has(instances[0].object),false);
assert.equal(ctx.state().gpu.generation,2);assert.equal(instances.length,2);
instances[1].prepared=false;instances[1].prepareFinal=()=>{};ctx.prepareSolidBackground();
assert.equal(ctx.state().prefetch.status,'skipped','A missing final cache must not be reported as prepared');
assert.equal(ctx.state().gpu.ready,true,'Skipped optional caching does not disable current GPU rendering');
vm.runInContext(source.slice(source.indexOf("renderer.domElement.addEventListener('webglcontextlost'"),source.indexOf("$('canvasHost').append(renderer.domElement)")),ctx);
ctx.playback(true);events.get('webglcontextlost')();
assert.equal(instances[1].disposed,true);assert.equal(ctx.state().gpu.available,false);
assert.equal(ctx.state().prefetch.status,'error');assert.match(labels.get('surfaceStatus').textContent,/perdido/);
events.get('webglcontextrestored')();assert.equal(ctx.state().gpu.ready,true);
assert.equal(ctx.state().gpu.generation,3);assert.equal(instances.length,3);
console.log('GPU UI lifecycle: CPU-independent display, fractional chronology/rewind, playback, physical stock, final preparation, skipped cache, context loss/restore and generation disposal passed.');
