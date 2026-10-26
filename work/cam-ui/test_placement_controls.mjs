import assert from 'node:assert/strict';
import fs from 'node:fs';
import {placementAction,placementOrigin,samePlacement} from './static/placement_controls.js';

const identity=[[1,0,0],[0,1,0],[0,0,1]];
const raw=[];for(const x of [10,12])for(const y of [20,24])for(const z of [30,36])raw.push([x,y,z]);
const close=(a,b)=>a.forEach((v,i)=>Array.isArray(v)?close(v,b[i]):assert.ok(Math.abs(v-b[i])<1e-9,`${v} != ${b[i]}`));
function scene(p){
 const triangles=raw.flatMap(point=>p.rotation.map((row,i)=>row.reduce((sum,v,j)=>sum+v*point[j]*(p.units==='inch'?25.4:1),p.translation_mm[i])));
 const low=[0,1,2].map(i=>Math.min(...triangles.filter((_,j)=>j%3===i))),high=[0,1,2].map(i=>Math.max(...triangles.filter((_,j)=>j%3===i)));
 return {bounds_mm:{minimum:low,maximum:high,size:low.map((v,i)=>high[i]-v)},transform:{rotation:p.rotation,translation_mm:p.translation_mm},triangles};
}
function act(p,action){const mesh=scene(p);return placementAction(p,mesh,mesh.triangles,action);}
const original={units:'mm',rotation:identity,translation_mm:[-10,-20,-36],xy_origin:'keep',z_origin:'keep'};
const initial=scene(original);assert.deepEqual(placementOrigin(initial.bounds_mm),{xy:[0,0],z:'top'});
const rotated=act(original,{kind:'rotate',axis:'x',turns:1});close(scene(rotated).bounds_mm.size,[2,6,4]);
close(scene(rotated).bounds_mm.minimum,[0,0,-4]);close(scene(rotated).bounds_mm.maximum,[2,6,0]);
for(const axis of ['x','y','z']){
 let p=original;for(let i=0;i<4;i++)p=act(p,{kind:'rotate',axis,turns:1});
 close(p.rotation,identity);close(p.translation_mm,original.translation_mm);
 close(act(act(original,{kind:'rotate',axis,turns:-1}),{kind:'rotate',axis,turns:1}).translation_mm,original.translation_mm);
}
for(const u of [0,.5,1])for(const v of [0,.5,1]){
 const moved=act(original,{kind:'origin_xy',anchor:[u,v]}),b=scene(moved).bounds_mm;
 close([b.minimum[0]+u*b.size[0],b.minimum[1]+v*b.size[1]],[0,0]);
 close(moved.rotation,identity);assert.equal(b.maximum[2],0);
}
for(const [anchor,f] of [['top',1],['center',.5],['bottom',0]]){
 const p=act(original,{kind:'origin_z',anchor}),b=scene(p).bounds_mm;
 close([b.minimum[2]+f*b.size[2]],[0]);close(b.minimum.slice(0,2),[0,0]);
}
const translated=act(original,{kind:'translate',delta_mm:[3,-4,2]});close(scene(translated).bounds_mm.minimum,[3,-4,-4]);
assert.deepEqual(placementOrigin(scene(translated).bounds_mm),{xy:null,z:null});
const inch={...original,units:'inch'},shifted=act(inch,{kind:'translate',delta_mm:[1,2,3]});
close(shifted.translation_mm,[-9,-18,-33]);assert.equal(shifted.units,'inch','Relative moves are mm, regardless of STL units');
const angle=Math.PI/4,diagonal={...original,rotation:[[Math.cos(angle),-Math.sin(angle),0],[Math.sin(angle),Math.cos(angle),0],[0,0,1]]};
const reset=act(diagonal,{kind:'reset'});close(reset.rotation,identity);close(scene(reset).bounds_mm.size,[2,4,6]);
const flipped=act(original,{kind:'flip'});close(flipped.rotation,[[1,0,0],[0,-1,0],[0,0,-1]]);close(scene(flipped).bounds_mm.size,[2,4,6]);
assert.ok(samePlacement(act(original,{kind:'translate',delta_mm:[0,0,0]}),original,initial));
for(const action of [{kind:'rotate',axis:'bad',turns:1},{kind:'rotate',axis:'x',turns:.5},{kind:'translate',delta_mm:[NaN,0,0]},{kind:'origin_xy',anchor:[.2,0]},{kind:'origin_z',anchor:'bad'},{kind:'unknown'}])assert.throws(()=>act(original,action));
const html=fs.readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
const beforeMain=html.slice(0,html.indexOf('<main>'));
assert.doesNotMatch(beforeMain,/id="(?:units|face|xyOrigin|zOrigin|applyPlacement)"/,'Placement controls must leave the sidebar');
const viewport=html.slice(html.indexOf('id="viewport"'),html.indexOf('<div class="transport">'));
for(const id of ['placementDock','placementPanel','units','face','xyOrigin','zOrigin','applyPlacement','placementDeltaX','placementDeltaY','placementDeltaZ'])assert.ok(viewport.includes(`id="${id}"`),id);
assert.equal((viewport.match(/data-placement-xy=/g)||[]).length,9);
assert.equal((viewport.match(/data-placement-rotate=/g)||[]).length,6);
console.log('Placement: real transforms, nine XY anchors, three Z anchors, rotations, units, no-ops and viewport ownership passed.');
