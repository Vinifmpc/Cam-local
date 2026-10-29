import fs from 'node:fs';
import assert from 'node:assert/strict';
import {StockPlayback} from './static/stock_model.js';

// The browser resolves Three via importmap. Reuse the bundled Node module here
// without changing production imports or adding a second dependency/runtime.
const threeUrl=new URL('../ui-runtime/node_modules/three/build/three.module.js',import.meta.url).href;
const source=fs.readFileSync(new URL('./static/stock_gpu.js',import.meta.url),'utf8');
const translated=source.replace("from 'three'",`from '${threeUrl}'`);
const {gpuStockGrid,gpuStockBudget,gpuSweepMinimum,createGpuStock}=await import('data:text/javascript,'+encodeURIComponent(translated));

const config={x0:-10,y0:-8,x1:10,y1:8,top:0,bottom:-6,physical_bottom:-5,step:.25,diameter:2,gpu_resolution:[80,64]};
assert.deepEqual(gpuStockGrid(config),{nx:80,ny:64,dx:.25,dy:.25,width:20,height:16,physicalBottom:-5});
assert.deepEqual([gpuStockGrid({...config,gpu_resolution:2048},1024).nx,gpuStockGrid({...config,gpu_resolution:2048},1024).ny],[1024,820]);
assert.equal(gpuStockGrid({...config,physical_bottom:undefined}).physicalBottom,config.bottom,'Legacy stock defaults its physical bottom to the simulation limit');
assert.equal(gpuStockGrid({...config,gpu_resolution:undefined}).nx,2048,'The longest default texture side is capped at 2048');
for(const patch of [{physical_bottom:-7},{physical_bottom:0},{physical_bottom:NaN},{diameter:0},{top:-6},{x1:-10},{gpu_resolution:[1,20]},{gpu_resolution:[2049,2]},{gpu_resolution:[2,3,4]},{gpu_resolution:'bad'}])assert.throws(()=>gpuStockGrid({...config,...patch}));
assert.throws(()=>createGpuStock({},config,[]),/WebGLRenderer/);

const budget=gpuStockBudget(2048,2048,1000000);
assert.equal(budget.targetBytes,32*1024*1024,'Float32 depth plus RGBA8 attachment occupy eight bytes per texel');
assert.equal(budget.attributeBytes,28000000);
assert.equal(budget.canCacheFinal,true,'A final cache and a million sweeps fit the default 96 MiB budget');
assert.equal(gpuStockBudget(2048,2048,100000,40).canCacheFinal,false);
for(const memory of [0,15,257,NaN,Infinity,'96'])assert.throws(()=>gpuStockBudget(16,16,1,memory));
assert.throws(()=>gpuStockBudget(2048,2048,1,16),/orçamento/);
for(const args of [[1,16,1],[2049,16,1],[16,16,-1],[16,16,1000001]])assert.throws(()=>gpuStockBudget(...args));

const rapids=['travel','retract','clearance_adjust','approach_rapid'];
const moves=[['cut',-8,0,-2,8,0,-2],['ramp',-8,-3,0,8,-3,-4],['ramp',-8,3,-4,8,3,0],['plunge',0,0,0,0,0,-8],['cut',4,4,-3,4,4,-3],['cut',-9,-7,-2,9,7,-2],...rapids.map(kind=>[kind,-9,-7,-5,9,7,-5]),['cut',100,100,-5,120,100,-5]];
let seed=5028;
const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
for(let i=0;i<60;i++)moves.push(['ramp',random()*24-12,random()*20-10,random()*9-7,random()*24-12,random()*20-10,random()*9-7]);
const playback=new StockPlayback(config,moves);
let checks=0,maxError=0;
const targets=[0,.1,.5,1,1.1,2.8,4,6,10,30.25,moves.length,20.7,0,50.5];
for(const target of targets){
 const snapshot=playback.seek(target),full=Math.floor(target);
 for(let j=0;j<snapshot.ny;j++)for(let i=0;i<snapshot.nx;i++){
  const point=[config.x0+(i+.5)*snapshot.dx,config.y0+(j+.5)*snapshot.dy];
  let z=config.top;
  for(let index=0;index<Math.ceil(target);index++){
   const move=moves[index].slice();
   if(index===full)for(let axis=0;axis<3;axis++)move[axis+4]=move[axis+1]+(target-full)*(move[axis+4]-move[axis+1]);
   const value=gpuSweepMinimum(point,move,config.diameter/2);
   if(value!==null)z=Math.min(z,Math.max(config.bottom,Math.min(config.top,value)));
  }
  const difference=Math.abs(z-snapshot.heights[j*snapshot.nx+i]);maxError=Math.max(maxError,difference);
  assert.ok(difference<6e-7,`${target} ${point}: expected ${snapshot.heights[j*snapshot.nx+i]}, got ${z}`);checks++;
 }
}
assert.equal(checks,71680);
for(const kind of rapids)assert.equal(gpuSweepMinimum([0,0],[kind,-1,0,-4,1,0,-4],1),null);
assert.equal(gpuSweepMinimum([0,0],['ramp',-2,0,-1,2,0,-3],1),-2.5);
assert.equal(gpuSweepMinimum([0,0],['ramp',-2,0,-3,2,0,-1],1),-2.5);

// Cross-product distance must not lose a thin disk in cancellation of two
// ~1e12 squared-distance terms. This case would incorrectly cut an outside point.
const longRamp=['ramp',-1000000,0,-1,1000000,0,-5];
assert.equal(gpuSweepMinimum([0,.002],longRamp,.001),null);
assert.ok(Math.abs(gpuSweepMinimum([0,.0006],longRamp,.001)-(-3.0000000016))<1e-12);
// Production attributes and fragment coordinates are relative to the stock.
// Float32 local coordinates retain submillimeter detail at a large work origin.
const origin=1000000000,offsetMove=['ramp',origin-8,origin,-1,origin+8,origin,-4],point=[origin+.125,origin+.25];
const relativeMove=offsetMove.slice();
for(const axis of [1,2,4,5])relativeMove[axis]=Math.fround(relativeMove[axis]-origin);
const relativePoint=point.map(value=>Math.fround(value-origin));
assert.ok(Math.abs(gpuSweepMinimum(point,offsetMove,1)-gpuSweepMinimum(relativePoint,relativeMove,1))<1e-7);

assert.match(source,/gl_FragDepth=clamp\(\(z-uBottom\)\/\(uTop-uBottom\)/);
assert.match(source,/depthFunc:THREE.LessDepth/);
assert.match(source,/uniform highp sampler2D uDepth/);
assert.doesNotMatch(source.slice(source.indexOf('import *')),/gl\.finish\(/,'Seeking never performs a blocking finish');
assert.match(source,/nx\+ny\+2/,'DDA covers the complete XY traversal');
console.log(`GPU stock pure contract passed: ${checks} CPU-oracle cells, ${targets.length} temporal targets, max Float32 error ${maxError} mm, all rapids, ramp precision, physical floor and memory bounds. Native shader/readback/render tests run separately.`);
