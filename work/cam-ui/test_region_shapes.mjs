import assert from 'node:assert/strict';
import {rectanglePolygon,roundPolygon,freehandPolygon,parseRegionVertices,validateRegionPolygon} from './static/region_shapes.js';
import {addRoughingRegion} from './static/form_state.js';

assert.deepEqual(rectanglePolygon([5,7],[-1,2]),[[-1,2],[5,2],[5,7],[-1,7]]);
assert.throws(()=>rectanglePolygon([0,0],[0,3]),/largura/);
for(const kind of ['boundary','keepout'])for(const [rx,ry]of [[10,10],[20,7]]){
 const center=[3,-4],points=roundPolygon(center,rx,ry,kind);
 assert.ok(points.length>=32&&points.length<=256);
 for(let i=0;i<points.length;i++){
  const normalized=points.map(p=>[(p[0]-center[0])/rx,(p[1]-center[1])/ry]);
  const a=normalized[i],b=normalized[(i+1)%points.length];
  const edgeDistance=Math.abs(a[0]*b[1]-a[1]*b[0])/Math.hypot(b[0]-a[0],b[1]-a[1]);
  if(kind==='keepout')assert.ok(edgeDistance>=1-1e-12,'Keep Out must contain the requested curve');
  else assert.ok(Math.hypot(...a)<=1+1e-12,'Keep In must stay within the requested curve');
  assert.ok((Math.hypot(...a)-edgeDistance)*Math.max(rx,ry)<=.0201);
 }
}
assert.throws(()=>roundPolygon([0,0],0),/raio mínimo/);
assert.throws(()=>roundPolygon([0,0],NaN),/raio/);
assert.throws(()=>roundPolygon([0,0],10000),/grande demais/);
const concave=[[0,0],[5,0],[5,4],[2,2],[0,4]];
assert.deepEqual(validateRegionPolygon([...concave,[0,4],[0,0]]),concave);
assert.throws(()=>validateRegionPolygon([[0,0],[4,4],[0,4],[4,0]]),/cruza/);
assert.throws(()=>validateRegionPolygon([[0,0],[4,0],[8,0]]),/área/);
assert.throws(()=>validateRegionPolygon([[0,0],[Infinity,0],[1,2]]),/inválido/);
assert.deepEqual(parseRegionVertices('0 0\n5,5;0\n5.5 4\n0 4'),[[0,0],[5.5,0],[5.5,4],[0,4]]);
assert.throws(()=>parseRegionVertices('0 0 3\n1 2\n3 4'),/separados/);
const stroke=[];
for(let edge=0;edge<concave.length;edge++)for(let i=0;i<60;i++){
 const a=concave[edge],b=concave[(edge+1)%concave.length],t=i/60;
 stroke.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);
}
stroke.push(concave[0]);
const simplified=freehandPolygon(stroke);
assert.deepEqual(simplified,concave,'Closed freehand simplification must preserve the concave shape');
assert.throws(()=>freehandPolygon([[0,0],[4,4],[0,4],[4,0]]),/cruza/);
const bounds={minimum:[0,0,-2],maximum:[20,20,0]};
const initial={boundaries_mm:[[[-5,-5],[25,-5],[25,25],[-5,25]]],exclusions_mm:[]};
const circle=roundPolygon([8,8],5),limited=addRoughingRegion(initial,'boundary',circle,bounds);
assert.deepEqual(limited.boundaries_mm,[circle],'First Keep In replaces stock for every shape');
const protectedShape=addRoughingRegion(limited,'keepout',simplified,bounds);
assert.deepEqual(protectedShape.boundaries_mm,[circle]);assert.deepEqual(protectedShape.exclusions_mm,[concave]);
assert.deepEqual(JSON.parse(JSON.stringify(protectedShape)),protectedShape,'All shapes persist as ordinary XY polygons');
console.log('Region drawing: rectangle, conservative circle/ellipse, concave polygon, closed freehand simplification, crossing rejection and Keep In/Out persistence passed.');
