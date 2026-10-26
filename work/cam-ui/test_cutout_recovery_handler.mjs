// Run the real application handlers with a small UI and deferred validation API.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {getCutoutRecovery} from './static/cutout_feedback.js';
import {mergeOperationOptions} from './static/operation_list.js';

const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
function actualFunction(name){
 const match=new RegExp('(?:^|\\n)((?:async )?function '+name+'\\()').exec(source);
 assert.ok(match,`Actual application handler ${name} was not found`);
 const start=match.index+(match[0].startsWith('\n')?1:0),rest=source.slice(start);
 const next=/\n(?:async )?function [A-Za-z_$][\w$]*\(/.exec(rest);
 return next?rest.slice(0,next.index):rest;
}
const handlers=['clearCutoutRecovery','presentCalculationError','applyCutoutRecovery','patchCommandConfig'].map(actualFunction).join('\n');
const copy=value=>JSON.parse(JSON.stringify(value));
const error='Cutout: há contorno interno estreito demais para a fresa de diâmetro 3,175 mm. Selecione somente contornos externos para recortar a peça ou use uma fresa menor para usinar os internos.';
const eligible={roughing_enabled:true,cutout_enabled:true,drill_enabled:true,cutout_contours:'all',
 operation_sequence:['roughing','drill','cutout'],drill_allow_helix:true};

function fixture(){
 const nodes=new Map(),toasts=[],apiCalls=[],tabs=[],renders=[];
 const element=id=>{
  if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',disabled:false,value:'all',focusCount:0,
   focus(){this.focusCount++;},setAttribute(){},removeAttribute(){}});
  return nodes.get(id);
 };
 let validate=async next=>copy(next);
 const context=vm.createContext({getCutoutRecovery,mergeOperationOptions,$:element,revision:4,busy:false,exportBusy:false,cutoutRecovery:null,cutoutRecoveryApplying:false,
  settings:{boundaries_mm:[[[1,2],[8,2],[8,9],[1,9]]],exclusions_mm:[[[3,3],[4,3],[4,4],[3,4]]]},
  operations:copy(eligible),tool:{id:'unchanged-tool',diameter_mm:3.175,cutting_length_mm:22},
  data:{asset:'unchanged-model',stock:{x0:0,y0:0,x1:20,y1:20,step:.25},notes:'retain'},windows:{unchanged:true},
  placement:{position:[0,0,0]},
  readOperations(){return copy(context.operations);},
  toast(message,isError=false,action=null){toasts.push({message,isError,action});},
  commandIdle(){if(context.busy||context.exportBusy)throw Error('Aguarde ou cancele o cálculo/exportação antes de alterar o projeto.');},
  commandRequest(){return {asset:context.data.asset,placement:copy(context.placement),tool:copy(context.tool),settings:copy(context.settings),operations:copy(context.operations),notes:context.data.notes,ui:{stock:copy(context.data.stock)}};},
  commandObject(value){if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Informe um objeto.');return value;},
  api(path,next){apiCalls.push({path,next:copy(next)});return validate(next);},
  fillFields(){element('cutoutContours').value=context.operations.cutout_contours;},
  displayToolSelect(){renders.push('tools');},makeTool(){renders.push('tool');},renderRegions(){renders.push('regions');},regionList(){renders.push('region-list');},
  dirty(){context.revision++;context.clearCutoutRecovery();},
  selectOperationTab(tab){tabs.push(tab);},
  commandState(){return {operations:copy(context.operations),tool:copy(context.tool),settings:copy(context.settings)};},
  startCalculation(){throw Error('Recovery must never calculate automatically');}});
 vm.runInContext(handlers,context);
 const present=(message=error,atRevision=context.revision,operations=context.operations)=>context.presentCalculationError(message,{revision:atRevision,operations:copy(operations)});
 return {context,element,toasts,apiCalls,tabs,renders,present,setValidation(fn){validate=fn;}};
}

// Showing an actionable failure never changes the selection or machining data.
{
 const f=fixture(),before=copy({settings:f.context.settings,tool:f.context.tool,operations:f.context.operations});
 f.present();
 assert.equal(f.element('cutoutRecovery').hidden,false);
 assert.match(f.element('cutoutRecoveryMessage').textContent,/contorno externo/i);
 assert.equal(f.element('cutoutRecoveryApply').textContent,'Soltar a peça · somente externo');
 assert.equal(f.toasts.at(-1).action.label,'Soltar a peça · somente externo');
 assert.equal(typeof f.toasts.at(-1).action.run,'function');
 assert.equal(f.apiCalls.length,0);
 assert.deepEqual(copy({settings:f.context.settings,tool:f.context.tool,operations:f.context.operations}),before);
 const result=await f.context.applyCutoutRecovery();
 assert.equal(f.apiCalls.length,1);
 assert.equal(f.apiCalls[0].path,'/api/validate-config');
 assert.equal(result.operations.cutout_contours,'external');
 assert.deepEqual(copy(f.context.operations),{...before.operations,cutout_contours:'external'});
 assert.deepEqual(copy(f.context.settings),before.settings,'Keep In and Keep Out polygons are retained');
 assert.deepEqual(copy(f.context.tool),before.tool,'The selected tool is retained');
 assert.equal(f.context.data.asset,'unchanged-model');
 assert.deepEqual(f.tabs,['cutout']);assert.equal(f.element('cutoutContours').focusCount,1);
 assert.equal(f.element('cutoutRecovery').hidden,true);
 await assert.rejects(()=>f.context.applyCutoutRecovery());
 assert.equal(f.apiCalls.length,1,'A consumed suggestion cannot submit another mutation');
}
// The toast action invokes the same explicit handler as the persistent card.
{
 const f=fixture();f.present();await f.toasts.at(-1).action.run();
 for(let i=0;i<4;i++)await Promise.resolve();
 assert.equal(f.apiCalls.length,1);
 assert.equal(f.context.operations.cutout_contours,'external');
 assert.deepEqual(f.tabs,['cutout']);
}

// Old failures, missing snapshots, changed settings and unrelated errors have
// no actionable card/toast, even if the text mentions Cutout or tool diameter.
for(const prepare of [
 f=>f.present(error,f.context.revision-1),
 f=>f.context.presentCalculationError(error),
 f=>f.present('Cutout bloqueado pelas regiões: o contorno completo não cabe na área permitida'),
 f=>f.present('Drill: furo incompatível com o diâmetro da fresa'),
 f=>{f.context.operations.cutout_enabled=false;f.present();},
 f=>{f.context.operations.cutout_contours='external';f.present();},
 f=>f.present(error,f.context.revision,{...eligible,cutout_enabled:false}),
 f=>f.present(error,f.context.revision,{...eligible,cutout_contours:'external'})]){
 const f=fixture();prepare(f);
 assert.equal(f.element('cutoutRecovery').hidden,true);
 assert.ok(!f.toasts.at(-1)?.action);
 assert.equal(f.apiCalls.length,0);
}
// An unrelated newer failure removes a suggestion from the previous failure.
{
 const f=fixture();f.present();f.present('Cutout excede o comprimento de corte da ferramenta');
 assert.equal(f.element('cutoutRecovery').hidden,true);
 assert.equal(f.context.cutoutRecovery,null);
}

// State must be checked again when a delayed user clicks a visible action.
for(const mutate of [f=>f.context.revision++,f=>f.context.busy=true,f=>f.context.exportBusy=true,
 f=>f.context.operations.cutout_enabled=false,f=>f.context.operations.cutout_contours='external']){
 const f=fixture();f.present();mutate(f);
 await assert.rejects(()=>f.context.applyCutoutRecovery());
 assert.equal(f.apiCalls.length,0,'An ineligible action must not reach validation');
}

// Validation is asynchronous. A revision change or a new calculation while it
// is pending must prevent a late successful response from replacing live state.
for(const mutate of [f=>f.context.revision++,f=>f.context.busy=true,f=>f.context.exportBusy=true]){
 const f=fixture();let complete;
 f.setValidation(next=>new Promise(resolve=>{complete=()=>resolve(copy(next));}));
 f.present();const pending=f.context.applyCutoutRecovery();
 assert.equal(f.apiCalls.length,1);
 const before=copy({settings:f.context.settings,tool:f.context.tool,operations:f.context.operations});
 mutate(f);complete();await assert.rejects(()=>pending);
 assert.deepEqual(copy({settings:f.context.settings,tool:f.context.tool,operations:f.context.operations}),before);
 assert.equal(f.renders.length,0,'No UI geometry should be rebuilt for a stale response');
 assert.equal(f.tabs.length,0);
}

// Repeated activation while validation is pending cannot enqueue two changes.
{
 const f=fixture();let complete;
 f.setValidation(next=>new Promise(resolve=>{complete=()=>resolve(copy(next));}));
 f.present();const first=f.context.applyCutoutRecovery();
 await assert.rejects(()=>f.context.applyCutoutRecovery());
 assert.equal(f.apiCalls.length,1);complete();await first;
 assert.equal(f.context.operations.cutout_contours,'external');
}
// A rejected candidate leaves the project untouched and permits an explicit
// retry instead of leaving the recovery button permanently disabled.
{
 const f=fixture();f.present();const before=copy(f.context.operations);
 f.setValidation(async()=>{throw Error('Serviço local indisponível');});
 await assert.rejects(()=>f.context.applyCutoutRecovery(),/indisponível/);
 assert.deepEqual(copy(f.context.operations),before);assert.equal(f.renders.length,0);
 assert.equal(f.element('cutoutRecoveryApply').disabled,false);
 assert.equal(f.context.cutoutRecoveryApplying,false);
 f.setValidation(async next=>copy(next));await f.context.applyCutoutRecovery();
 assert.equal(f.context.operations.cutout_contours,'external');assert.equal(f.apiCalls.length,2);
}
console.log('Cutout recovery handlers passed: explicit apply, preserved project, exact failure context, stale/busy gates, deferred validation race and duplicate suppression.');
