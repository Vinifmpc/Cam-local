import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as THREE from '../ui-runtime/node_modules/three/build/three.module.js';
import {AUTOMATIC_REGION_COLOR,automaticRegionLoops,automaticRegionText,smartPlanForState,createAutomaticRegionOverlay} from './static/automatic_regions.js';
import {smartPlanText} from './static/smart_mode.js';

// Canonical Clipper orientation: CCW shells, CW holes. An island inside the
// hole and a separate component must remain distinct filled regions.
const loops=[[[0,0],[20,0],[20,20],[0,20]],[[5,5],[5,15],[15,15],[15,5]],
 [[8,8],[12,8],[12,12],[8,12]],[[30,0],[34,0],[34,4],[30,4]]];
const automatic={polygons_mm:loops,area_mm2:332,offset_mm:1.6,bounds_mm:[0,0,34,20],manual_limits_applied:true,source:'filled_external_silhouette'};
const plan={enabled:true,automatic_regions:automatic,preparation_contours:{eligible:1,blocked:1}};
const original=JSON.stringify(plan),copied=automaticRegionLoops(automatic);copied[0][0][0]=99;assert.equal(loops[0][0][0],0);
assert.deepEqual(automaticRegionLoops({polygons_mm:[[[0,0],[1,0],[NaN,1]]]}),[]);
assert.equal(createAutomaticRegionOverlay(THREE,{polygons_mm:[]},0).children.length,0);
const group=createAutomaticRegionOverlay(THREE,automatic,7.18),fills=group.children.filter(item=>item.userData.automaticRegionFill),outlines=group.children.filter(item=>item.userData.automaticRegionOutline);
assert.equal(fills.length,3);assert.equal(outlines.length,4);
let totalArea=0,holes=0;
for(const fill of fills){
 const geometry=fill.geometry,position=geometry.attributes.position,index=geometry.index.array;
 holes+=geometry.parameters.shapes.holes.length;
 for(let i=0;i<index.length;i+=3){
  const a=new THREE.Vector2().fromBufferAttribute(position,index[i]),b=new THREE.Vector2().fromBufferAttribute(position,index[i+1]),c=new THREE.Vector2().fromBufferAttribute(position,index[i+2]);
  totalArea+=Math.abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))/2;
 }
 assert.equal(fill.material.color.getHex(),AUTOMATIC_REGION_COLOR);assert.ok(fill.material.opacity<.1);assert.equal(fill.material.depthWrite,false);assert.equal(fill.position.z,7.18);
}
assert.equal(holes,1);assert.equal(totalArea,332,'Visual triangulation must preserve the hole, island and separate component');
for(const outline of outlines){
 assert.equal(outline.material.type,'LineDashedMaterial');assert.equal(outline.material.color.getHex(),AUTOMATIC_REGION_COLOR);
 const p=outline.geometry.attributes.position,d=outline.geometry.attributes.lineDistance;
 assert.deepEqual([p.getX(0),p.getY(0),p.getZ(0)],[p.getX(p.count-1),p.getY(p.count-1),p.getZ(p.count-1)]);
 assert.equal(d.count,p.count);assert.equal(d.getX(0),0);assert.ok(d.getX(d.count-1)>0);
}
assert.equal(JSON.stringify(plan),original,'Rendering must never write automatic polygons into manual settings or mutate the report');
const compact=smartPlanForState(plan);
assert.equal(compact.automatic_regions.polygons_mm,undefined);assert.equal(compact.automatic_regions.polygon_count,4);assert.equal(compact.automatic_regions.vertex_count,16);
assert.equal(compact.automatic_regions.area_mm2,332);assert.equal(smartPlanForState(plan,true),plan);assert.equal(JSON.stringify(plan),original);
assert.match(automaticRegionText(plan),/área dos centros da fresa de 332 mm²/);assert.match(automaticRegionText(plan),/Limites manuais impedem preparar/);
assert.match(automaticRegionText(plan),/não representa remoção em todas as profundidades/);
assert.doesNotMatch(automaticRegionText({...plan,preparation_contours:{blocked:0}}),/impedem preparar/);
const featuresPlan={...plan,exterior_strategy:{mode:'features_then_cutout',external_prismatic:false}};
assert.match(automaticRegionText(featuresPlan),/formas 3D, bolsões e rebaixos/);assert.match(automaticRegionText(featuresPlan),/abertos à borda/);assert.doesNotMatch(automaticRegionText(featuresPlan),/faixa de planejamento|impedem preparar/);
assert.match(smartPlanText({...plan,sequence:['roughing','cutout'],roughing_bottom_mm:-10,skin_mm:.4,retention_z_mm:-9.6,cutout_bottom_mm:-10,cutout_stepdown_mm:.5}),/área dos centros/);

// Exercise the actual cache, revision invalidation and shared layer controls.
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8'),nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,{checked:true,hidden:false,value:'0'});return nodes.get(id);};
let builds=0,clears=0;
const context=vm.createContext({THREE,$,revision:1,smartPlanPreview:{revision:1,report:plan},motion:null,smart:true,
 automaticRegionsSource:null,automaticRegionsZ:null,automaticRegionGroup:new THREE.Group(),regionGroup:new THREE.Group(),
 modelGroup:new THREE.Group(),pathGroup:new THREE.Group(),rapidGroup:new THREE.Group(),
 smartModeEnabled:()=>context.smart,
 createAutomaticRegionOverlay(...args){builds++;return createAutomaticRegionOverlay(...args);},
 clearGroup(group){clears++;for(const item of [...group.children]){group.remove(item);item.traverse(child=>{child.geometry?.dispose();child.material?.dispose();});}},
 commandObject(){},updateDepthLegend(){},commandState:()=>({simulation:{}})});
vm.runInContext(source.slice(source.indexOf('function currentSmartPlan('),source.indexOf('function renderSmartPlan(')),context);
context.renderAutomaticRegions();assert.equal(builds,1);assert.equal(context.automaticRegionGroup.visible,true);assert.equal($('automaticRegionLegend').hidden,false);
assert.deepEqual(JSON.parse(JSON.stringify(context.automaticRegionsViewState())),{visible:true,legend_visible:true,polygon_count:4});
context.renderAutomaticRegions();assert.equal(builds,1,'Unchanged plan identity must not rebuild geometry');assert.equal(clears,1);
const applyLayers=source.slice(source.indexOf(" if(action==='simulation.set'){"),source.indexOf(" if(action==='simulation.play')"));
vm.runInContext('function commandSimulation(command){const action=command.action;'+applyLayers+'}',context);
context.commandSimulation({action:'simulation.set',layers:{regions:false}});assert.equal(context.regionGroup.visible,false);assert.equal(context.automaticRegionGroup.visible,false);assert.equal($('automaticRegionLegend').hidden,true);
assert.deepEqual(JSON.parse(JSON.stringify(context.automaticRegionsViewState())),{visible:false,legend_visible:false,polygon_count:4});
context.commandSimulation({action:'simulation.set',layers:{regions:true}});assert.equal(context.automaticRegionGroup.visible,true);assert.equal(builds,1,'Layer commands change visibility without rebuilding');
let disposed=false;context.automaticRegionGroup.children[0].children[0].geometry.addEventListener('dispose',()=>disposed=true);
context.revision=2;context.renderAutomaticRegions();assert.equal(context.automaticRegionGroup.children.length,0);assert.equal($('automaticRegionLegend').hidden,true);assert.equal(disposed,true,'Stale geometry must be disposed immediately');
assert.equal(context.automaticRegionsViewState().polygon_count,0);
context.motion={smart_plan:plan};context.renderAutomaticRegions();assert.equal(builds,2,'A loaded or calculated motion plan restores its automatic envelope');
context.smart=false;context.renderAutomaticRegions();assert.equal(context.automaticRegionGroup.children.length,0);assert.equal(context.regionGroup.visible,true,'Manual region visibility remains independent of smart planning');
assert.match(source,/smart_plan:smartPlanForState\(currentSmartPlan\(\),detail\)/);
assert.match(source,/\$\('showKeepout'\)\.onchange=syncRegionVisibility/);
assert.equal(JSON.stringify(plan),original);
console.log('Automatic regions: Clipper shell/hole/island topology, exact visual area, dashed closed contours, compact/detail reports, blocked-profile feedback, cached rendering, disposal and command layer visibility passed.');
