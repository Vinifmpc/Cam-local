import assert from 'node:assert/strict';
import {StockModel,insidePolygon,activeStockBottom,stockGridIndices} from './static/stock_model.js';
const config={x0:0,y0:0,x1:10,y1:4,top:0,bottom:-12,step:1,diameter:2,exclusions:[],boundaries:null};
const model=new StockModel(config);
// At grid sample (5.5,.5), the descending line's disk covers t up to
// (5.5+sqrt(1-.25))/10. Analytic Z minimum is its negative X.
model.apply(['cut',0,0,0,10,0,-10,0]);
assert.ok(Math.abs(model.heights[5]-(-5.5-Math.sqrt(.75)))<1e-6);
assert.equal(model.heights[2*model.nx+5],0);
const before=model.snapshot();model.apply(['travel',0,0,-10,10,0,-10,0]);
assert.deepEqual(model.heights,before.heights);
assert.equal(model.volume,before.volume);
model.reset();assert.equal(model.volume,0);assert.ok(model.heights.every(z=>z===0));
model.apply(['cleared_feed',.5,.5,0,.5,.5,-3,0]);assert.equal(model.heights[0],-3);
assert.ok(insidePolygon(1,1,[[0,0],[2,0],[2,2],[0,2]]));
assert.ok(!insidePolygon(3,1,[[0,0],[2,0],[2,2],[0,2]]));
const guarded=new StockModel({...config,exclusions:[[[0,0],[2,0],[2,2],[0,2]]]});
guarded.apply(['cut',.5,.5,0,.5,.5,-2,0]);assert.ok(guarded.protectedCount>0);
// Keepout alerts do not hide actual simulated removal.
assert.equal(guarded.heights[0],-2);
// Keep In/Out belong only to Rough. A legacy universal-scope preference may
// not produce false protection hits during Cutout or hide its stock removal.
for(const cutoutUseRegions of [false,true]){
 const recut=new StockModel({...config,cutoutUseRegions,exclusions:[[[0,0],[2,0],[2,2],[0,2]]],boundaries:[]});
 recut.apply(['cut',.5,.5,0,.5,.5,-2,0,'cutout']);
 assert.equal(recut.heights[0],-2);assert.equal(recut.protectedCount,0);
 assert.equal(recut.snapshot().config.cutoutUseRegions,false);
 const rough=new StockModel({...config,cutoutUseRegions,exclusions:[[[0,0],[2,0],[2,2],[0,2]]],boundaries:[]});
 rough.apply(['cut',.5,.5,0,.5,.5,-2,0,'roughing']);assert.ok(rough.protectedCount>0);
 const drill=new StockModel({...config,cutoutUseRegions,exclusions:[[[0,0],[2,0],[2,2],[0,2]]],boundaries:[]});
 drill.apply(['cut',.5,.5,0,.5,.5,-2,0,'drill']);
 assert.equal(drill.heights[0],-2);assert.equal(drill.protectedCount,0,'Drill ignores Rough Keep In/Out');
}
assert.throws(()=>new StockModel({...config,step:.0001}),/300.000/);
assert.throws(()=>new StockModel({...config,top:-20}),/inválidos/);
const monotonic=new StockModel(config);monotonic.apply(['cut',0,.5,-2,10,.5,-2,0]);
const volume=monotonic.volume;monotonic.apply(['cut',0,.5,-1,10,.5,-1,0]);assert.equal(monotonic.volume,volume);
console.log('9 stock contracts passed: analytic slope, untouched samples, rapid isolation, reset, vertical feed, polygon, keepout alert without masking, limits, monotonic removal.');
// An inactive operation must not deepen or clip the simulated stock.
assert.equal(activeStockBottom(false,-50,true,-2.1),-2.1);
assert.equal(activeStockBottom(true,-2,false,-50),-2);
assert.equal(activeStockBottom(true,-2,true,-2.1),-2.1);
assert.equal(activeStockBottom(false,null,true,-2.1),-2.1);
assert.equal(activeStockBottom(false,null,false,null,true,-8),-8);
assert.equal(activeStockBottom(true,-2,true,-3,true,-8),-8);
assert.equal(activeStockBottom(true,-2,true,-3,false,-50),-3);
assert.throws(()=>activeStockBottom(false,null,false,null,true,null),/profundidade/);
assert.throws(()=>activeStockBottom(false,null,false,null),/operações ativas/);
// Equal vertex counts with different aspect ratios require different strides.
assert.notDeepEqual(stockGridIndices(3,6),stockGridIndices(6,3));
for(const[nx,ny]of [[3,6],[6,3],[8,4],[4,8]]){
 const indices=stockGridIndices(nx,ny);
 assert.equal(indices.length,6*(nx-1)*(ny-1));
 for(let k=0;k<indices.length;k+=3){
  const points=indices.slice(k,k+3).map(n=>[n%nx,Math.floor(n/nx)]);
  assert.ok(points.every(([x,y])=>x>=0&&x<nx&&y>=0&&y<ny));
  assert.equal(Math.max(...points.map(p=>p[0]))-Math.min(...points.map(p=>p[0])),1);
  assert.equal(Math.max(...points.map(p=>p[1]))-Math.min(...points.map(p=>p[1])),1);
 }
}
console.log('Simulation regressions passed: active operation depth and grid topology after aspect-ratio changes.');
