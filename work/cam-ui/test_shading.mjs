import assert from 'node:assert/strict';
import {smoothWallNormals} from './static/stock_shading.js';
import {StockModel} from './static/stock_model.js';
// A quarter-mm grid must fit the actual 94 x 94 mm example stock.
const stock=new StockModel({x0:-5,y0:-5,x1:89,y1:89,top:0,bottom:-17.1,step:.25,diameter:3.175});
assert.equal(stock.heights.length,141376);
// Neighboring staircase wall normals become less abrupt, with unit length.
const normals=new Float32Array([1,0,0, 0,1,0, 1,0,0, 0,1,0]);
const before=normals.slice(),heights=stock.heights.slice();
smoothWallNormals(normals,4,1);
assert.ok(Math.hypot(...normals.slice(0,3).map((v,i)=>v-normals[i+3]))<Math.SQRT2);
assert.notDeepEqual(normals,before);
for(let i=0;i<normals.length;i+=3)assert.ok(Math.abs(Math.hypot(...normals.slice(i,i+3))-1)<1e-6);
// Flat faces and opposite sides of a narrow slot retain their normals.
const distinct=new Float32Array([0,0,1, 1,0,0, -1,0,0]);
assert.deepEqual(smoothWallNormals(distinct.slice(),3,1),distinct);
assert.deepEqual(stock.heights,heights);
console.log('Smooth display passed: fine ring grid, reduced wall-normal jumps, flat floors and opposite walls preserved.');
