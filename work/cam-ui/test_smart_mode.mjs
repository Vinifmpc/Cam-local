import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {effectiveMachiningOptions,validateSmartOperationPatch,smartPlanText,smartEntryHint,smartPolicyText} from './static/smart_mode.js';
import {operationListFromOptions,operationOptionsFromList} from './static/operation_list.js';
import {readOperationValues,priorRoughingAvailable} from './static/form_state.js';
import * as THREE from '../ui-runtime/node_modules/three/build/three.module.js';
import {createAutomaticRegionOverlay} from './static/automatic_regions.js';
import {FeedClock,timeLabel} from './static/playback.js';
import {StockPlayback} from './static/stock_model.js';

const manual={machining_mode:'manual',order:'cutout_then_roughing',operation_sequence:['cutout','roughing','drill'],roughing_enabled:false,cutout_enabled:true,drill_enabled:false,cutout_contours:'all',cutout_use_prior_roughing:false};
assert.deepEqual(effectiveMachiningOptions(manual),manual);
const smart=effectiveMachiningOptions({...manual,machining_mode:'smart'});
assert.deepEqual(smart.operation_sequence,['drill','roughing','cutout']);assert.equal(smart.roughing_enabled,true);assert.equal(smart.cutout_enabled,true);
assert.equal(smart.drill_enabled,false);assert.equal(smart.cutout_contours,'external');assert.equal(smart.cutout_use_prior_roughing,true);
assert.equal(manual.cutout_contours,'all','Effective policy must not mutate saved manual preferences');
for(const patch of [{order:['roughing','cutout']},{enabled:{roughing:false}},{enabled:{cutout:false}}])assert.throws(()=>validateSmartOperationPatch(patch),/modo inteligente/);
validateSmartOperationPatch({enabled:{drill:true}});
const plan={enabled:true,sequence:['roughing','cutout'],stock_bottom_mm:-10,roughing_bottom_mm:-10,cutout_bottom_mm:-10.2,retention_z_mm:-9.6,skin_mm:.4,cutout_stepdown_mm:.7,assumptions:['Bruto até o fundo do STL.']};
const summary=smartPlanText(plan);
assert.match(summary,/Rough → Cutout/);assert.match(summary,/pele externa de 0.4/);assert.match(summary,/Z -10.2/);assert.match(summary,/Bruto até o fundo/);
assert.equal(smartPlanText({enabled:false}),'');
const fullContourPlan={...plan,exterior_strategy:{mode:'features_then_cutout',reason:'Exterior vertical constante em Z.',external_prismatic:true},
 preparation_contours:{eligible:0,blocked:0,not_required:true,levels_mm:[]}};
const openEdgePlan={...fullContourPlan,exterior_strategy:{mode:'features_then_cutout',reason:'Rebaixos abertos à borda são alcançados pelo Rough 3D.',external_prismatic:false}};
const preparedPlan={...plan,exterior_strategy:{mode:'rough_prepare_then_release',reason:'A entrada do Cutout exige preparar um canal de acesso.',external_prismatic:false}};
assert.match(smartPlanText(fullContourPlan),/Rough: rebaixos e bolsões, inclusive abertos à borda/);assert.match(smartPlanText(fullContourPlan),/Cutout: contorno externo completo/);
assert.match(smartPlanText(fullContourPlan),/sem cortes de Rough/);assert.doesNotMatch(smartPlanText(fullContourPlan),/pele externa de/);
assert.match(smartPlanText(fullContourPlan),/Exterior vertical constante em Z/);
assert.match(smartPlanText(preparedPlan),/canal externo de acesso/);assert.match(smartPlanText(preparedPlan),/Cutout: liberação/);assert.match(smartPlanText(preparedPlan),/pele externa de 0.4/);
assert.match(smartPolicyText(null).order,/Confira a viabilidade no plano/);assert.doesNotMatch(smartPolicyText(null).order,/canal|preparo/);assert.match(smartPolicyText(fullContourPlan).order,/contorno externo completo/);
assert.match(smartPolicyText(preparedPlan).regions,/prepara o canal de acesso/);
assert.deepEqual(smartPolicyText(openEdgePlan),smartPolicyText(fullContourPlan),'Prismatic classification must not override the validated operation policy');
assert.match(smartPlanText(openEdgePlan),/Cutout: contorno externo completo/);assert.doesNotMatch(smartPlanText(openEdgePlan),/pele externa de/);

// Exercise the actual app's readonly preview handler, including pending and
// stale replies, without browser automation or a second implementation.
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const functions=source.slice(source.indexOf('function smartModeEnabled('),source.indexOf('function updateHints('));
const nodes=new Map();
function element(id){if(!nodes.has(id))nodes.set(id,{value:id==='machiningMode'?'smart':'',dataset:{},disabled:false,hidden:false,checked:false,textContent:''});return nodes.get(id);}
const requests=[],payload={asset:'fixture.stl',operations:{machining_mode:'smart'}};
let reply=async()=>structuredClone(plan),list=operationListFromOptions(manual),locked=false;
const context=vm.createContext({$:element,data:{},motion:null,revision:4,smartPlanPreview:null,smartPlanPending:false,smartPlanText,smartPolicyText,
 THREE,createAutomaticRegionOverlay,automaticRegionsSource:null,automaticRegionsZ:null,automaticRegionGroup:new THREE.Group(),regionGroup:new THREE.Group(),clearGroup:group=>group.clear(),
 fmt:value=>String(value),commandRequest:()=>structuredClone(payload),effectiveMachiningOptions,operationListFromOptions,operationOptionsFromList,
 operationList:{getState:()=>structuredClone(list),setState:state=>list=structuredClone(state),setLocked:value=>locked=value},
 api(path,request){requests.push({path,request});return reply();}});
vm.runInContext(functions,context);
context.syncSmartOperationList();assert.equal(locked,true);assert.deepEqual(list.order,['drill','roughing','cutout']);assert.equal(list.enabled.roughing,true);assert.equal(list.enabled.cutout,true);
assert.equal(element('roughEnabled').checked,true);assert.equal(element('cutoutEnabled').checked,true);
const before=JSON.stringify(payload),result=await context.inspectSmartPlan();
assert.deepEqual(result,plan);assert.equal(JSON.stringify(payload),before);assert.equal(requests[0].path,'/api/smart-plan');assert.match(element('smartPlanSummary').textContent,/pele externa/);
assert.equal(element('inspectSmartPlan').disabled,false);
reply=async()=>structuredClone(openEdgePlan);await context.inspectSmartPlan();
assert.match(element('smartPlanSummary').textContent,/Cutout: contorno externo completo/);assert.match(element('orderHint').textContent,/rebaixos e bolsões, inclusive abertos à borda/);
assert.doesNotMatch(element('orderHint').textContent,/pele de retenção/);assert.match(element('regionNote').textContent,/contorno externo completo fica/);
assert.match(element('cutoutReuseHint').textContent,/contorno externo completo em camadas/);
reply=async()=>structuredClone(preparedPlan);await context.inspectSmartPlan();
assert.match(element('smartPlanSummary').textContent,/Cutout: liberação/);assert.match(element('orderHint').textContent,/canal de acesso com pele/);
assert.match(element('regionNote').textContent,/prepara o canal de acesso/);assert.match(element('cutoutReuseHint').textContent,/quais camadas o preparo/);
let resolve;
reply=()=>new Promise(done=>resolve=done);
const pending=context.inspectSmartPlan();assert.equal(element('inspectSmartPlan').disabled,true);
await assert.rejects(()=>context.inspectSmartPlan(),/Aguarde/);
vm.runInContext('revision++',context);context.renderSmartPlan();assert.equal(element('smartPlanSummary').textContent,'Confira o plano antes de calcular.');
assert.match(element('orderHint').textContent,/Confira a viabilidade no plano/,'An invalidated report must request feasibility without promising an implicit access channel');
resolve(plan);await assert.rejects(()=>pending,/configuração mudou/);
assert.equal(context.currentSmartPlan(),null,'A stale preview cannot become the current plan');assert.equal(element('inspectSmartPlan').disabled,false);
reply=async()=>{throw Error('Fundo do bruto acima do modelo.');};
await assert.rejects(()=>context.inspectSmartPlan(),/Fundo/);assert.equal(element('smartPlanSummary').dataset.state,'error');assert.match(element('smartPlanSummary').textContent,/Fundo/);
element('machiningMode').value='manual';context.syncSmartOperationList();assert.equal(locked,false);assert.equal(element('smartModePanel').hidden,true);
// The real selector restores the editable manual choices when the user leaves
// smart mode, while leaving the typed depth values intact throughout.
list=operationListFromOptions(manual);element('cutoutContours').value='all';element('cutoutUsePriorRoughing').checked=false;
element('bottom').value='7.3';element('cutoutDepth').value='8.1';
context.manualOperationState=null;context.manualCutoutPreferences=null;context.updateOperationControls=()=>{};
context.updateHints=()=>{};context.regionList=()=>{};context.dirty=()=>context.revision++;
const modeHandler=source.slice(source.indexOf("$('machiningMode').onchange=()=>{"),source.indexOf("$('inspectSmartPlan').onclick="));
vm.runInContext(modeHandler,context);
element('machiningMode').value='smart';element('machiningMode').onchange();assert.equal(locked,true);assert.equal(element('cutoutContours').value,'external');assert.equal(element('cutoutUsePriorRoughing').checked,true);
assert.equal(element('bottom').value,'7.3');assert.equal(element('cutoutDepth').value,'8.1');
element('machiningMode').value='manual';element('machiningMode').onchange();assert.equal(locked,false);assert.deepEqual(list,operationListFromOptions(manual));
assert.equal(element('cutoutContours').value,'all');assert.equal(element('cutoutUsePriorRoughing').checked,false);assert.equal(element('cutoutDepth').value,'8.1');
// Preview uses the real request builder with strict reads. Invalid geometry
// cannot silently fall back to an older value while the calculation rejects it.
const strictReads=[];
let previewForm={machiningMode:'smart',roughEnabled:true,cutoutEnabled:true,drillEnabled:false,
 smartStockBottom:'',smartSkin:'',smartBreakthrough:'0',cutoutDepth:'',cutoutStepdown:'.7',rapidFeed:'3000',roughFeed:'',cutoutFeed:'',plungeFeed:'',spindleRpm:''};
context.data={asset:'fixture.stl'};context.placement={};context.tool={};context.windows=null;
context.readSettings=options=>{strictReads.push(['settings',options.strict]);return {};};
context.readOperations=options=>{strictReads.push(['operations',options.strict]);return readOperationValues(previewForm,{cutout_bottom_mm:-10},{},0,options);};
context.readStockSettings=()=>({x0:0,y0:0,x1:20,y1:20,step:.25});
vm.runInContext(source.slice(source.indexOf('function commandRequest('),source.indexOf('async function patchCommandConfig(')),context);
reply=async()=>structuredClone(plan);
for(const patch of [{smartSkin:'-1'},{smartSkin:'abc'},{smartBreakthrough:''}]){
 previewForm={...previewForm,smartSkin:'',smartBreakthrough:'0',...patch};
 const snapshot=JSON.stringify(previewForm),callsBefore=requests.length;
 await assert.rejects(()=>context.inspectSmartPlan(),/Pele externa|Ultrapassagem/);
 assert.equal(requests.length,callsBefore,'Invalid preview inputs must not reach the backend as fallback values');
 assert.equal(JSON.stringify(previewForm),snapshot,'Readonly preview leaves the invalid input available for correction');
 assert.equal(context.smartPlanPending,false);
}
previewForm={...previewForm,smartSkin:'',smartBreakthrough:'0'};
await context.inspectSmartPlan();assert.ok(strictReads.every(([,strict])=>strict===true));
assert.equal(requests.at(-1).request.operations.roughing_feed_mm_min,null,'Preview can inspect geometry before feeds are filled');
assert.match(source,/if\(action==='machining\.plan'\)return inspectSmartPlan\(\)/,'The supported command API must expose the same preview');
assert.match(source,/if\(smartModeEnabled\(\)\)validateSmartOperationPatch\(patch\)/,'Commands must respect the visible smart order policy');
// A certified central plunge is a cutting move throughout the view and grid.
// The actual app must display it in the entry color and use its feed duration.
const plunge=['plunge',3,3,0,3,3,-2,0,'roughing'],ramp=['ramp',3,3,-2,5,3,-2,0,'roughing'];
context.pathGroup=new THREE.Group();context.rapidGroup=new THREE.Group();context.motion={moves:[plunge,ramp]};
element('showPaths').checked=true;element('showRapids').checked=false;
vm.runInContext(source.slice(source.indexOf('function displayPaths('),source.indexOf('function setMotion(')),context);
context.displayPaths();const entryPath=context.pathGroup.children.find(item=>item.material.color.getHex()===0xca9b3d);
assert.deepEqual([...entryPath.geometry.attributes.position.array],[...plunge.slice(1,7),...ramp.slice(1,7)]);
context.motion={moves:[plunge],feeds_mm_min:[120]};context.feedClock=new FeedClock([plunge],[1]);context.cursor=.5;
context.timeLabel=timeLabel;context.toolGroup=new THREE.Group();context.showStockSurface=()=>{};
vm.runInContext(source.slice(source.indexOf('function updateCursor('),source.indexOf('function resetStock(')),context);
context.updateCursor();assert.equal(context.toolGroup.position.z,-1);assert.equal(context.stockWanted,.5);assert.match(element('moveInfo').textContent,/Mergulho · F 120/);
const plungeGrid=new StockPlayback({x0:0,y0:0,x1:6,y1:6,top:0,bottom:-3,step:.25,diameter:2,boundaries:null,exclusions:[]},[plunge]);
assert.equal(Math.min(...plungeGrid.seek(.5).heights),-1);assert.equal(Math.min(...plungeGrid.seek(1).heights),-2);
assert.match(smartEntryHint(true),/Plunge rate/);assert.match(smartEntryHint(false),/desativado/);
context.priorRoughingAvailable=priorRoughingAvailable;context.regionPicker=null;context.drawMode=null;
element('machiningMode').value='smart';element('roughEnabled').checked=true;element('cutoutEnabled').checked=true;element('drillEnabled').checked=false;element('drillCenterCutting').checked=false;
vm.runInContext(source.slice(source.indexOf('function updateOperationControls('),source.indexOf('function fillFields(')),context);
context.updateOperationControls();assert.equal(element('drillCenterCutting').disabled,false);assert.equal(element('drillFeed').disabled,true);assert.equal(element('drillCenterCutting').checked,false,'Smart mode never confirms cutter capability by itself');
element('machiningMode').value='manual';context.updateOperationControls();assert.equal(element('drillCenterCutting').disabled,true);
let selectedTab=null,focused=false;context.selectOperationTab=tab=>selectedTab=tab;element('drillCenterCutting').focus=()=>focused=true;
vm.runInContext(source.split('\n').find(line=>line.startsWith("$('reviewCenterCutting').onclick=")),context);element('reviewCenterCutting').onclick();
assert.equal(selectedTab,'drill');assert.equal(focused,true,'The Rough hint links to the original capability checkbox, without duplicating it');
console.log('Smart mode: effective policy, manual preservation, stock summary, fixed operation list, readonly preview, concurrency and stale response guards passed.');
