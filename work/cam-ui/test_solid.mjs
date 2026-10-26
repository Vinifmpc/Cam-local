import assert from 'node:assert/strict';
import factory from '../ui-runtime/node_modules/manifold-3d/manifold.js';
import {buildSolid,sweptSegments} from './static/stock_solid.js';
import {StockModel} from './static/stock_model.js';
const module=await factory();module.setup();
const config={x0:0,y0:0,x1:10,y1:6,top:0,bottom:-3,diameter:2};
const fullVolume=180;
const removed=(moves,target)=>fullVolume-buildSolid(module,config,moves,target).volume;
const plunge=['cut',3,3,0,3,3,-2,0,'roughing'];
assert.ok(Math.abs(removed([plunge])-2*Math.PI)<.05);
assert.equal(removed([['plunge',...plunge.slice(1)]]),removed([plunge]),'Certified plunge moves remove the same cylindrical stock as any vertical cutting move');
assert.equal(removed([['plunge',...plunge.slice(1)]],.5),removed([plunge],.5));
const cut=['cut',3,3,-2,7,3,-2,0,'cutout'];
assert.ok(Math.abs(removed([cut])-2*(8+Math.PI))<.05);
assert.equal(removed([['travel',...cut.slice(1)]]),0);
assert.equal(removed([cut],0),0);
const partial=buildSolid(module,config,[cut],.5);
assert.ok(Math.abs(fullVolume-partial.volume-2*(4+Math.PI))<.05);
for(let i=0;i<partial.positions.length;i+=3){
 assert.ok([...partial.positions.slice(i,i+3),...partial.normals.slice(i,i+3)].every(Number.isFinite));
 if(Math.abs(partial.positions[i+2]+2)<1e-6)assert.ok(partial.positions[i]<=6.00001);
}
// Deepest identical sweep dominates only when both endpoint floors do.
const shallower=['cut',3,3,-1,7,3,-1,0,'roughing'];
assert.equal(sweptSegments(config,[shallower,cut]).length,1);
assert.equal(removed([shallower,cut]),removed([cut]));
const down=['ramp',3,3,-.5,7,3,-2.5,0,'roughing'];
const up=['ramp',3,3,-2.5,7,3,-.5,0,'roughing'];
assert.equal(sweptSegments(config,[down,up]).length,2);
// Independent analytic grid sweep confirms the sloping bottom of a ramp.
const grid=new StockModel({...config,step:.025,boundaries:null,exclusions:[]});grid.apply(down);
assert.ok(Math.abs(removed([down])-grid.volume)/grid.volume<.01);
// Crossing the stock top must not sweep the above-stock half at full depth.
const crossing=['ramp',1,3,1,5,3,-1,0,'roughing'];
const segments=sweptSegments(config,[crossing]);assert.equal(segments[0][0][0],3);assert.equal(segments[0][0][2],0);
assert.deepEqual(sweptSegments(config,[cut],0),[]);
assert.ok(removed([cut],.25)<removed([cut],.5));
console.log('Solid surface passed: cylinder/capsule analytic volume, XYZ ramps, top clipping, rapid isolation, rewind/partial prefix, dominance and finite normals.');
