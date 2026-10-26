import assert from 'node:assert/strict';
import {numericValue,readOperationValues,validateTimingFeeds,importedMachiningState,jobStatusText,calculationSummary,cutoutPreferences,priorRoughingAvailable,addRoughingRegion,isAutomaticStockBoundary} from './static/form_state.js';

const tool={diameter_mm:3.175,feed_mm_min:650,plunge_mm_min:140};
const previous={roughing_enabled:true,cutout_enabled:true,roughing_feed_mm_min:700,cutout_feed_mm_min:900,plunge_mm_min:150,cutout_bottom_mm:-15.7,cutout_stepdown_mm:.635};
const form={roughEnabled:true,cutoutEnabled:true,operationOrder:'cutout_then_roughing',roughingOrder:'layer',
 cutoutDepth:'17.4',cutoutStepdown:'1.2',cutoutDirection:'conventional',cutoutContours:'all',cutoutUsePriorRoughing:false,
 roughFeed:'711',cutoutFeed:'922',plungeFeed:'155',rapidFeed:'2500',spindleRpm:'11000'};
// Opening a different model must keep values currently typed in the form,
// even if the previous project snapshot has older feeds and layer settings.
const edited=readOperationValues(form,previous,tool,0,{strict:false});
const oldSettings={stepdown_mm:1.3,stepover_mm:1.1,sampling_mm:.15,radial_allowance_mm:.2,
 stock_top_mm:0,bottom_mm:-15.7,entry_angle_deg:4,clearance_mm:3,obstacle_top_mm:4,
 boundaries_mm:[[[90,90],[95,90],[95,95]]],exclusions_mm:[[[1,1],[2,1],[2,2]]]};
const mesh={bounds_mm:{minimum:[0,0,-20],maximum:[20,20,0],size:[20,20,20]}};
const imported=importedMachiningState(mesh,oldSettings,edited,tool.diameter_mm);
assert.equal(imported.operations.roughing_feed_mm_min,711);
assert.equal(imported.operations.cutout_feed_mm_min,922);
assert.equal(imported.operations.plunge_mm_min,155);
assert.equal(imported.operations.spindle_rpm,11000);
assert.equal(imported.operations.order,'cutout_then_roughing');
assert.equal(imported.operations.roughing_order,'layer');
assert.equal(imported.operations.cutout_enabled,true);
assert.equal(imported.operations.cutout_contours,'all');
assert.equal(imported.operations.cutout_use_prior_roughing,false);
assert.equal(imported.operations.cutout_use_roughing_regions,false);
for(const key of ['stepdown_mm','stepover_mm','sampling_mm','radial_allowance_mm','entry_angle_deg','clearance_mm'])assert.equal(imported.settings[key],oldSettings[key]);
assert.equal(imported.settings.stock_top_mm,0);assert.equal(imported.settings.bottom_mm,-20);
assert.equal(imported.operations.cutout_bottom_mm,-20);assert.equal(imported.operations.drill_bottom_mm,-20);assert.equal(imported.settings.obstacle_top_mm,0);
assert.deepEqual(imported.settings.exclusions_mm,[]);
assert.deepEqual(imported.settings.boundaries_mm,[[[-5,-5],[25,-5],[25,25],[-5,25]]]);
assert.deepEqual(imported.stock,{x0:-5,y0:-5,x1:25,y1:25,step:.25});
const keepIn=[[0,0],[10,0],[10,10],[0,10]],anotherKeepIn=[[12,0],[20,0],[20,10],[12,10]];
assert.equal(isAutomaticStockBoundary(imported.settings,mesh.bounds_mm),true);
const limited=addRoughingRegion(imported.settings,'boundary',keepIn,mesh.bounds_mm);
assert.equal(isAutomaticStockBoundary(limited,mesh.bounds_mm),false);
assert.deepEqual(limited.boundaries_mm,[keepIn],'The first drawn Keep In replaces the full-stock default');
assert.deepEqual(imported.settings.boundaries_mm,[[[-5,-5],[25,-5],[25,25],[-5,25]]],'Adding a region must not mutate the imported snapshot');
const multiple=addRoughingRegion(limited,'boundary',anotherKeepIn,mesh.bounds_mm);
assert.deepEqual(multiple.boundaries_mm,[keepIn,anotherKeepIn],'Subsequent user Keep Ins form a union');
const protectedRegion=addRoughingRegion(imported.settings,'keepout',keepIn,mesh.bounds_mm);
assert.deepEqual(protectedRegion.exclusions_mm,[keepIn]);
assert.deepEqual(protectedRegion.boundaries_mm,imported.settings.boundaries_mm,'A Keep Out does not replace the stock limit');
assert.equal(isAutomaticStockBoundary(protectedRegion,mesh.bounds_mm),true);
assert.equal(isAutomaticStockBoundary({boundaries_mm:null},mesh.bounds_mm),false);
assert.equal(isAutomaticStockBoundary({boundaries_mm:[]},mesh.bounds_mm),false);
assert.deepEqual(oldSettings.exclusions_mm,[[[1,1],[2,1],[2,2]]]);
validateTimingFeeds(imported.operations,tool);
// Moving the new mesh resets geometric bounds again while retaining machining.
const moved=importedMachiningState({bounds_mm:{minimum:[-10,-10,0],maximum:[10,10,20]}},imported.settings,imported.operations,3.175);
assert.equal(moved.settings.stock_top_mm,20);assert.equal(moved.settings.bottom_mm,0);
assert.equal(moved.operations.cutout_bottom_mm,0);assert.equal(moved.operations.roughing_feed_mm_min,711);
assert.deepEqual(moved.settings.boundaries_mm,[[[-15,-15],[15,-15],[15,15],[-15,15]]]);
assert.equal(moved.operations.cutout_contours,'all');
assert.equal(moved.operations.cutout_use_prior_roughing,false);

// Old projects may carry the former universal-region switch. It never applies
// the Rough mask to Cutout after restore, even if its old value was true.
const legacy={...previous,cutout_use_roughing_regions:true};
assert.deepEqual(cutoutPreferences(legacy),{cutout_use_roughing_regions:false,cutout_contours:'external',cutout_use_prior_roughing:true});
const restoredPreferences=JSON.parse(JSON.stringify({...legacy,...cutoutPreferences(legacy,{cutoutContours:'all',cutoutUsePriorRoughing:false})}));
assert.deepEqual(cutoutPreferences(restoredPreferences),{cutout_use_roughing_regions:false,cutout_contours:'all',cutout_use_prior_roughing:false});
const legacyForm=readOperationValues({...form,cutoutContours:undefined,cutoutUsePriorRoughing:undefined,cutoutRegions:true},legacy,tool,0);
assert.equal(legacyForm.cutout_use_roughing_regions,false);
assert.equal(legacyForm.cutout_contours,'external');assert.equal(legacyForm.cutout_use_prior_roughing,true);
const legacyImport=importedMachiningState(mesh,oldSettings,legacy,tool.diameter_mm);
assert.equal(legacyImport.operations.cutout_use_roughing_regions,false);
assert.equal(legacyImport.operations.cutout_contours,'external');
assert.equal(legacyImport.operations.cutout_use_prior_roughing,true);
assert.equal(priorRoughingAvailable(true,true,'roughing_then_cutout'),true);
for(const [rough,cutout,order]of [[true,true,'cutout_then_roughing'],[true,false,'roughing_then_cutout'],[false,true,'roughing_then_cutout']])assert.equal(priorRoughingAvailable(rough,cutout,order),false);
assert.equal(priorRoughingAvailable(true,true,'roughing_then_cutout',['roughing','drill','cutout'],true),false,'An intervening active Drill cannot reuse the Rough handoff proof');
assert.equal(priorRoughingAvailable(true,true,'roughing_then_cutout',['roughing','drill','cutout'],false),true,'A disabled Drill does not break the Rough handoff');
assert.equal(priorRoughingAvailable(true,true,'roughing_then_cutout',['drill','roughing','cutout'],true),true);
assert.equal(priorRoughingAvailable(true,true,'roughing_then_cutout',['roughing','cutout','drill'],true),true);
assert.equal(edited.cutout_use_prior_roughing,false,'An unavailable reuse checkbox preserves its preference');
assert.throws(()=>cutoutPreferences({cutout_contours:'unknown'}),/contornos do Cutout/);

// Disabled operations must not demand their empty depth, stepdown or feed.
const roughOnly={...form,cutoutEnabled:false,cutoutDepth:'',cutoutStepdown:'',cutoutFeed:'-1'};
const r=readOperationValues(roughOnly,previous,tool,0);
assert.equal(r.cutout_bottom_mm,-15.7);assert.equal(r.cutout_stepdown_mm,.635);assert.equal(r.cutout_feed_mm_min,900);
validateTimingFeeds(r,tool);
assert.throws(()=>readOperationValues({...roughOnly,cutoutEnabled:true},previous,tool,0),/Profundidade do cutout/);
assert.throws(()=>readOperationValues({...form,roughEnabled:false,cutoutEnabled:false},previous,tool,0),/Ative Roughing, Drill ou Cutout/);
// A feed entered in the tool dialog is sufficient; no redundant operation input.
const fromTool=readOperationValues({...roughOnly,roughFeed:'',plungeFeed:''},previous,tool,0);
assert.equal(fromTool.roughing_feed_mm_min,null);assert.equal(fromTool.plunge_mm_min,null);
validateTimingFeeds(fromTool,tool);
assert.throws(()=>validateTimingFeeds(fromTool,{}),/Feedrate do desbaste, Plunge rate/);
assert.throws(()=>readOperationValues({...form,roughFeed:'0'},previous,tool,0),/Feedrate do desbaste/);
assert.throws(()=>numericValue('','Topo do bruto'),/Preencha o campo: Topo do bruto/);
assert.equal(numericValue('0','Topo do bruto'),0);
assert.throws(()=>importedMachiningState({bounds_mm:{minimum:[0,0,0],maximum:[20,20,0]}}),/espessura/);
assert.equal(jobStatusText({phase:'Validando rampas',progress:.61,elapsed_s:65.9}),'Validando rampas · 61% · 1min 5s');
assert.match(jobStatusText({},4.2),/4s$/);
assert.match(calculationSummary({moves:[],operations:{roughing:{}}}),/Nenhum corte/);
assert.match(calculationSummary({moves:[['cut',0,0,0,1,0,0,0,'cutout']],operations:{roughing:{},cutout:{}}}),/Roughing sem material/);
assert.equal(calculationSummary({moves:[['cut',0,0,0,1,0,0,0,'roughing']],operations:{roughing:{}}}),'Percurso calculado e salvo localmente.');
const cutoutMotion={moves:[['cut',0,0,0,1,0,0,0,'cutout']],operations:{cutout:{contours_selection:'external',internal_contours_total:2,skipped_internal_contours:2}}};
assert.match(calculationSummary(cutoutMotion),/2 contorno\(s\) interno\(s\) fora do recorte/);
assert.match(calculationSummary(cutoutMotion),/Para incluí-los, escolha Internos \+ externo/);
assert.doesNotMatch(calculationSummary({...cutoutMotion,operations:{cutout:{...cutoutMotion.operations.cutout,contours_selection:'all'}}}),/fora do recorte/);
assert.doesNotMatch(calculationSummary({...cutoutMotion,operations:{cutout:{...cutoutMotion.operations.cutout,skipped_internal_contours:0}}}),/fora do recorte/);
// Drill remains opt-in for existing projects and participates independently.
assert.equal(edited.drill_enabled,false);assert.equal(edited.drill_allow_helix,false);assert.equal(edited.drill_center_cutting,false);
assert.equal(edited.drill_compensate_facets,false,'Nominal STL compensation stays opt-in for old projects');
const drillOnly={...form,roughEnabled:false,cutoutEnabled:false,drillEnabled:true,operationSequence:['drill','cutout','roughing'],drillDepth:'12',drillPeck:'.8',drillTolerance:'.02',drillAllowHelix:true,drillCenterCutting:true,drillCompensateFacets:true,drillFeed:'450',cutoutDepth:'',cutoutStepdown:''};
const d=readOperationValues(drillOnly,previous,tool,0);
assert.equal(d.drill_bottom_mm,-12);assert.equal(d.drill_peck_mm,.8);assert.equal(d.drill_tolerance_mm,.02);
assert.equal(d.drill_feed_mm_min,450);assert.equal(d.drill_allow_helix,true);assert.equal(d.drill_center_cutting,true);
assert.equal(d.drill_compensate_facets,true);
assert.equal(readOperationValues({...drillOnly,drillCompensateFacets:undefined},d,tool,0).drill_compensate_facets,true);
assert.equal(readOperationValues({...drillOnly,drillCompensateFacets:false},d,tool,0).drill_compensate_facets,false);
assert.deepEqual(d.operation_sequence,['drill','cutout','roughing']);assert.equal(d.order,'cutout_then_roughing');validateTimingFeeds(d,tool);
assert.throws(()=>readOperationValues({...drillOnly,drillDepth:''},previous,tool,0),/Profundidade do Drill/);
assert.throws(()=>readOperationValues({...drillOnly,drillPeck:'0'},previous,tool,0),/Passo de furação/);
assert.throws(()=>readOperationValues({...drillOnly,drillTolerance:'-.1'},previous,tool,0),/Tolerância circular/);
assert.throws(()=>readOperationValues({...drillOnly,drillTolerance:'0'},previous,tool,0),/Tolerância circular/);
assert.throws(()=>validateTimingFeeds({...d,drill_feed_mm_min:null},{}),/Feedrate do Drill/);
validateTimingFeeds({...d,drill_allow_helix:false,drill_feed_mm_min:null},{});
const drilledImport=importedMachiningState(mesh,oldSettings,d,tool.diameter_mm);
assert.equal(drilledImport.operations.drill_bottom_mm,-20);assert.equal(drilledImport.operations.drill_allow_helix,true);assert.equal(drilledImport.operations.drill_peck_mm,.8);
assert.equal(drilledImport.operations.drill_compensate_facets,true,'Changing STL preserves the explicit compensation preference');
assert.deepEqual(drilledImport.operations.operation_sequence,d.operation_sequence);
assert.match(calculationSummary({moves:[['cut',0,0,0,0,0,-1,0,'drill']],operations:{roughing:{},drill:{}}}),/^Drill calculado/);
const combined=calculationSummary({...cutoutMotion,operations:{...cutoutMotion.operations,drill:{holes_count:3,helix_count:2,skipped_holes_count:1}}});
assert.match(combined,/2 contorno\(s\) interno\(s\) fora do recorte/);assert.match(combined,/Drill: 3 furo\(s\), 2 em hélice/);assert.match(combined,/1 furo\(s\) ignorado/);
assert.match(calculationSummary({moves:[],operations:{drill:{holes_count:0,skipped_holes_count:2}}}),/2 furo\(s\) ignorado/);
// Smart policy never asks for its disabled manual depths. It must still demand
// actual cutting data and reject malformed stock/retention inputs.
const smartForm={...form,machiningMode:'smart',roughEnabled:false,cutoutEnabled:false,drillEnabled:true,
 drillDepth:'12',drillPeck:'1',drillTolerance:'.03',cutoutDepth:'',smartStockBottom:'-22',smartBreakthrough:'.2',smartSkin:'.4'};
const smart=readOperationValues(smartForm,previous,tool,0);
assert.equal(smart.machining_mode,'smart');assert.equal(smart.roughing_enabled,true);assert.equal(smart.cutout_enabled,true);
assert.deepEqual(smart.operation_sequence,['drill','roughing','cutout']);assert.equal(smart.order,'roughing_then_cutout');
assert.equal(smart.cutout_contours,'external');assert.equal(smart.cutout_use_prior_roughing,true);
assert.equal(smart.cutout_bottom_mm,previous.cutout_bottom_mm,'Smart policy preserves the manual cutout depth; the backend derives the effective depth');
assert.equal(smart.smart_stock_bottom_mm,-22);assert.equal(smart.smart_breakthrough_mm,.2);assert.equal(smart.smart_skin_mm,.4);
const automatic=readOperationValues({...smartForm,smartStockBottom:'',smartSkin:'',smartBreakthrough:'0'},previous,tool,0);
assert.equal(automatic.smart_stock_bottom_mm,null);assert.equal(automatic.smart_skin_mm,null);assert.equal(automatic.smart_breakthrough_mm,0);
for(const patch of [{smartStockBottom:'abc'},{smartSkin:'0'},{smartSkin:'-.2'},{smartSkin:'abc'},{smartBreakthrough:'-.1'},{smartBreakthrough:''}])assert.throws(()=>readOperationValues({...smartForm,...patch},previous,tool,0));
assert.throws(()=>readOperationValues({...smartForm,machiningMode:'unknown'},previous,tool,0),/modo/);
validateTimingFeeds(smart,tool);
const smartImport=importedMachiningState(mesh,oldSettings,smart,tool.diameter_mm);
assert.equal(smartImport.operations.machining_mode,'smart');assert.equal(smartImport.operations.smart_stock_bottom_mm,null,'A different STL cannot inherit the prior stock Z');
assert.equal(smartImport.operations.smart_skin_mm,.4);assert.equal(smartImport.operations.smart_breakthrough_mm,.2);
console.log('Form state: machining preferences preserved across new STL, placement and restore; Rough-only regions, explicit Cutout contour selection, rest-material availability, actionable omitted-internal summary and validation passed.');
