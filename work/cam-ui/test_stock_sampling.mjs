import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as THREE from '../ui-runtime/node_modules/three/build/three.module.js';
import {StockModel,stockGridIndices,sampleStockGrid} from './static/stock_model.js';
import {smoothWallNormals} from './static/stock_shading.js';

const config={x0:-2,y0:10,x1:3,y1:13.5,top:5,bottom:-7,step:1.75,diameter:1,boundaries:null,exclusions:[]};
const snapshot={config,nx:4,ny:2,dx:1.25,dy:1.75,heights:new Float32Array([5,4,3,2,1,0,-1,-2])};
const points=[[-2,10],[3,13.5],[.5,11.75]],before=JSON.stringify(points),heightsBefore=snapshot.heights.slice();
const result=sampleStockGrid(snapshot,points);
assert.deepEqual(result,{top_mm:5,bottom_mm:-7,dx_mm:1.25,dy_mm:1.75,samples:[
 {requested_mm:[-2,10],center_mm:[-1.375,10.875],z_mm:5,removed_depth_mm:0},
 {requested_mm:[3,13.5],center_mm:[2.375,12.625],z_mm:-2,removed_depth_mm:7},
 {requested_mm:[.5,11.75],center_mm:[1.125,12.625],z_mm:-1,removed_depth_mm:6}]});
assert.equal(JSON.stringify(points),before);assert.deepEqual(snapshot.heights,heightsBefore);
for(const invalid of [null,[],Array.from({length:65},()=>[0,11]),[[0]],[[0,11,2]],[[NaN,11]],[['0',11]]])assert.throws(()=>sampleStockGrid(snapshot,invalid),/1 a 64/);
for(const point of [[-2.000001,10],[3.000001,10],[0,9.99],[0,13.50001]])assert.throws(()=>sampleStockGrid(snapshot,[point]),/fora dos limites/);
assert.equal(sampleStockGrid(snapshot,Array.from({length:64},()=>[0,11])).samples.length,64);
assert.throws(()=>sampleStockGrid({...snapshot,heights:new Float32Array(2)},[[0,11]]),/indisponível/);
assert.throws(()=>sampleStockGrid({...snapshot,dx:0},[[0,11]]),/indisponível/);
assert.throws(()=>sampleStockGrid({...snapshot,heights:new Float32Array([NaN,4,3,2,1,0,-1,-2])},[[-2,10]]),/Altura inválida/);
const stock=new StockModel({...config,step:.25});
stock.apply(['cut',0,11,5,0,11,-3,0,'roughing']);
const removed=sampleStockGrid(stock.snapshot(),[[0,11],[2,13]]);
assert.equal(removed.samples[0].z_mm,-3);assert.equal(removed.samples[1].z_mm,5,'Untouched stock is reported directly, without a new simulation');

// Run the real worker-receive and command handlers with actual Three.js grid
// geometry. Only the worker and DOM boundary are substituted.
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8'),nodes=new Map(),posts=[];
const $=id=>{if(!nodes.has(id))nodes.set(id,{style:{},textContent:'',hidden:false});return nodes.get(id);};
const context=vm.createContext({THREE,$,sampleStockGrid,stockGridIndices,smoothWallNormals,
 worker:{postMessage:value=>posts.push(value)},scene:new THREE.Scene(),mode:'paths',stockMesh:null,stockWire:null,
 stockGeneration:7,stockBusy:true,stockReady:false,stockWanted:10,stockApplied:-1,stockSampleSnapshot:null,
 data:{},tool:{diameter_mm:1},settings:{boundaries_mm:[],exclusions_mm:[]},motion:null,smart:true,
 smartModeEnabled:()=>context.smart,showStockSurface(){},scheduleSolid(){},requestStock(){context.requestCount++;},requestCount:0,
 fmt:value=>String(value),toast(){},cancelSolid(){},solidFailedIndex:null,solidIndex:-1,solidGeneration:-1,solidMesh:null,
 stockLastSent:0,stockConfig:null,readStockSettings:()=>({x0:-2,y0:10,x1:3,y1:13.5,step:1.75}),number:()=>5,simulationBottom:()=>-7});
vm.runInContext(source.slice(source.indexOf('worker.onmessage=({data:s})=>{'),source.indexOf('function setMode(')),context);
const commandCode=source.slice(source.indexOf(" if(action==='simulation.sample'){"),source.indexOf(" if(action==='simulation.set'){"));
vm.runInContext('function sampleCommand(command){const action=command.action;'+commandCode+'}',context);
const state={type:'stock',generation:7,index:10,...snapshot,volume:0,protectedCount:0};
context.worker.onmessage({data:state});
const command={action:'simulation.sample',points};
assert.deepEqual(JSON.parse(JSON.stringify(context.sampleCommand(command))),{index:10,...result});assert.equal(context.stockSampleSnapshot,state);
assert.equal(context.requestCount,0);assert.equal(posts.length,0,'Sampling never seeks or starts another simulation');
const validFlags={stockReady:true,stockBusy:false,stockWanted:10,stockApplied:10,stockSampleSnapshot:state};
for(const patch of [{stockReady:false},{stockBusy:true},{stockWanted:11},{stockSampleSnapshot:null},{stockSampleSnapshot:{...state,generation:6}},{stockSampleSnapshot:{...state,index:9}}]){
 Object.assign(context,validFlags,patch);assert.throws(()=>context.sampleCommand(command),/Aguarde a grade/);
}
Object.assign(context,validFlags);context.stockBusy=true;
context.worker.onmessage({data:{...state,generation:6,index:99}});
assert.equal(context.stockSampleSnapshot,state);assert.equal(context.stockBusy,true,'An old generation cannot unlock current readiness');
context.worker.onmessage({data:{type:'error',generation:7,error:'Falha de teste'}});assert.equal(context.stockReady,false);assert.equal(context.stockSampleSnapshot,null);
assert.throws(()=>context.sampleCommand(command),/Aguarde a grade/);
context.worker.onmessage({data:{...state,index:5}});assert.equal(context.requestCount,1);assert.throws(()=>context.sampleCommand(command),/Aguarde a grade/);
context.worker.onmessage({data:state});assert.equal(context.sampleCommand(command).index,10);

vm.runInContext(source.slice(source.indexOf('function resetStock('),source.indexOf('function requestStock(')),context);
const settingsBefore=JSON.stringify(context.settings);
context.resetStock(false);assert.equal(context.stockReady,false);assert.equal(context.stockSampleSnapshot,null);
assert.equal(posts.at(-1).config.boundaries,null,'Smart empty Keep In is unrestricted for the simulated protection map');
assert.equal(JSON.stringify(context.settings),settingsBefore,'Grid initialization cannot rewrite manual regions');
const autoGrid=new StockModel(posts.at(-1).config);assert.ok(autoGrid.protected.every(value=>value===0));
context.smart=false;context.resetStock(false);assert.deepEqual(posts.at(-1).config.boundaries,[],'Manual empty Keep In keeps its original meaning');
context.readStockSettings=()=>{throw Error('Bruto inválido');};context.stockSampleSnapshot=state;context.stockReady=true;
context.resetStock(false);assert.equal(context.stockReady,false);assert.equal(context.stockSampleSnapshot,null);assert.equal(context.stockBusy,false);
const generation=context.stockGeneration;context.data=null;context.stockSampleSnapshot=state;context.stockReady=true;context.resetStock(false);
assert.equal(context.stockSampleSnapshot,null);assert.equal(context.stockReady,false);assert.equal(context.stockGeneration,generation+1);
context.worker.onmessage({data:{...state,generation}});assert.equal(context.stockSampleSnapshot,null,'A late reply after clearing the model cannot restore an obsolete snapshot');
console.log('Stock sampling: non-square grid centers, exact snapshot heights, boundaries/64-point validation, readonly command, worker generation/index gates, error/reset invalidation and smart empty-region protection passed.');
