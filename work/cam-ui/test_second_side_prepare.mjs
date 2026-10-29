// Run the actual application handlers: preparing a fixture after a manual
// flip must not perform another turn or reset the already chosen work frame.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {placementAction,samePlacement,secondSideState} from './static/placement_controls.js';
import {insidePolygon} from './static/stock_model.js';
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
function actualFunction(name){
 const match=new RegExp('(?:^|\\n)((?:async )?function '+name+'\\()').exec(source);
 assert.ok(match,name);
 const start=match.index+(match[0].startsWith('\n')?1:0),rest=source.slice(start),next=/\n(?:async )?function [A-Za-z_$][\w$]*\(/.exec(rest);
 return next?rest.slice(0,next.index):rest;
}
const handlers=['applyPlacementCandidate','prepareSecondSide'].map(actualFunction).join('\n');
const copy=value=>JSON.parse(JSON.stringify(value));
function fixture(){
 const nodes=new Map(),tabs=[],panels=[],calls=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='secondSideAxis'?'current':'2'});return nodes.get(id);};
 const placement={units:'mm',rotation:[[1,0,0],[0,-1,0],[0,0,-1]],translation_mm:[17,28,-4],xy_origin:'keep',z_origin:'keep'};
 const raw=[];for(const x of [0,20])for(const y of [0,12])for(const z of [-4,0])raw.push([x,y,z]);
 const triangles=raw.flatMap(p=>placement.rotation.map((row,i)=>row.reduce((s,v,j)=>s+v*p[j],placement.translation_mm[i])));
 const data={asset:'same-stl',name:'already-flipped',placement,triangles,mesh:{transform:{rotation:placement.rotation,translation_mm:placement.translation_mm},bounds_mm:{minimum:[17,16,-4],maximum:[37,28,0],size:[20,12,4]}},
  settings:{stock_top_mm:0,bottom_mm:-2.3,obstacle_top_mm:0,domain_mode:'expanded',stepdown_mm:.7,boundaries_mm:[[[18,17],[36,17],[36,27],[18,27]]],exclusions_mm:[[[19,18],[20,18],[20,19]]]},
  operations:{machining_mode:'manual',roughing_enabled:true,cutout_enabled:true,drill_enabled:false,cutout_bottom_mm:-4.2,roughing_feed_mm_min:500},stock:{x0:12,y0:11,x1:42,y1:33,step:.5},notes:'user note',motion:{moves:['old']},project_id:'old'};
 const context=vm.createContext({$:element,placementAction,samePlacement,secondSideState,
  data:copy(data),placement:copy(placement),settings:copy(data.settings),operations:copy(data.operations),revision:3,busy:false,exportBusy:false,placementUiBusy:false,placementUndo:null,
  commandIdle(){if(context.busy||context.exportBusy||context.placementUiBusy)throw Error('busy');},
  placementSnapshot(){return {scene:copy({...context.data,settings:context.settings,operations:context.operations,placement:context.placement}),camera:{position:[1,2,3],target:[0,0,0],zoom:1}};},
  syncPlacementUi(){},stop(){},toast(){},restorePlacementCamera(){},
  async api(){calls.push('inspect');throw Error('An unchanged orientation must not need mesh inspection');},
  adopt(next){context.data=copy(next);context.settings=copy(next.settings);context.operations=copy(next.operations);context.placement=copy(next.placement);context.revision++;},
  selectOperationTab(tab){tabs.push(tab);},setPlacementPanel(panel){panels.push(panel);},
  commandState(){return copy({placement:context.placement,settings:context.settings,operations:context.operations});}});
 vm.runInContext(handlers,context);
 return {context,nodes,element,tabs,panels,calls};
}
{
 const f=fixture(),c=f.context,before=copy(c.data),protectedCenter=[27,22];
 await c.prepareSecondSide(undefined,{diameter_mm:6,height_mm:5});
 assert.deepEqual(copy(c.placement),before.placement);
 assert.deepEqual(copy(c.data.mesh),before.mesh);assert.deepEqual(copy(c.data.triangles),before.triangles);
 assert.deepEqual(copy(c.data.stock),before.stock);assert.equal(c.data.notes,before.notes);
 for(const key of ['stock_top_mm','bottom_mm','boundaries_mm','stepdown_mm'])assert.deepEqual(copy(c.settings[key]),before.settings[key]);
 assert.equal(c.settings.domain_mode,'silhouette');assert.equal(c.settings.obstacle_top_mm,5);
 assert.equal(c.settings.exclusions_mm.length,1);assert.ok(insidePolygon(...protectedCenter,c.settings.exclusions_mm[0]));
 assert.equal(c.operations.roughing_enabled,true);assert.equal(c.operations.cutout_enabled,false);assert.equal(c.operations.drill_enabled,false);
 assert.equal(c.operations.cutout_bottom_mm,-4.2);assert.equal(c.operations.roughing_feed_mm_min,500);
 assert.equal(c.data.motion,null);assert.equal(c.data.project_id,null);assert.deepEqual(f.calls,[]);
 assert.deepEqual(copy(c.placementUndo.scene),before,'Undo must retain the state before preparing');
 const prepared=copy(c.data);
 await c.prepareSecondSide('current',{diameter_mm:6,height_mm:5});
 assert.deepEqual(copy(c.data),prepared,'Preparing the same clamp twice must not move, turn or duplicate it');
 assert.deepEqual(f.tabs,['rough','rough']);assert.deepEqual(f.panels,['origin','origin']);
}
// Invalid dimensions and orientation must leave the placed model untouched.
{
 const f=fixture(),c=f.context,before=copy(c.data.mesh);
 c.operations.machining_mode='smart';c.operations.smart_part_released=true;c.operations.smart_stock_bottom_mm=-5;
 await c.prepareSecondSide('current',{diameter_mm:6,height_mm:2});
 assert.equal(c.operations.machining_mode,'smart');assert.equal(c.operations.smart_part_released,true);
 assert.equal(c.operations.cutout_enabled,true);assert.equal(c.operations.smart_stock_bottom_mm,-5);
 assert.deepEqual(copy(c.data.mesh),before);
}
for(const [axis,clamp] of [['z',{diameter_mm:6,height_mm:2}],['current',{diameter_mm:0,height_mm:2}],['current',{diameter_mm:6,height_mm:-1}]]){
 const f=fixture(),before=copy(f.context.data);
 await assert.rejects(()=>f.context.prepareSecondSide(axis,clamp));assert.deepEqual(copy(f.context.data),before);
}
// Additional turning remains an explicit option and is consumed by the UI.
{
 const f=fixture(),c=f.context;let candidate;
 c.applyPlacementCandidate=async(value,options)=>{candidate=copy(value);assert.equal(options.secondSide.height_mm,2);};
 f.element('secondSideAxis').value='x';
 await c.prepareSecondSide('x',{diameter_mm:6,height_mm:2});
 assert.deepEqual(candidate.rotation,[[1,0,0],[0,1,0],[0,0,1]]);
 assert.equal(f.element('secondSideAxis').value,'current');
}
const html=fs.readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
assert.match(html,/<select id="secondSideAxis"[^>]*><option value="current" selected>/);
assert.match(html,/id="prepareSecondSide"[^>]*>Preparar fixação<\/button>/);
console.log('Second face: preparing after a flip preserves orientation, zero, depth and stock; central clamp, repeat, explicit turn, undo and invalid input passed.');
