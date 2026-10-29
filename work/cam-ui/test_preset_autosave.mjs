import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {machiningProfile,profilePatch,rememberProfileRequest} from './static/machining_presets.js';

const tool={id:'flat',name:'Fresa',diameter_mm:3.175,cutting_length_mm:22};
const settings={stepdown_mm:.7,stepover_mm:1.27,stock_top_mm:0,bottom_mm:-17};
const operations={machine_acceleration_mm_s2:[10,10,10],roughing_feed_mm_min:700};
const original=machiningProfile(tool,settings,operations);
let disk={selected_id:'a',last_used:original,presets:[
 {id:'a',name:'Pinus',profile:structuredClone(original)},
 {id:'b',name:'Outro material',profile:machiningProfile(tool,settings,{...operations,machine_acceleration_mm_s2:[5,6,7]})}]};
const timers=new Map(),nodes=new Map(),requests=[];let timer=0,fail=false;
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const ctx=vm.createContext({structuredClone,machiningProfile,profilePatch,rememberProfileRequest,
 Option:class{},$:id=>{if(!nodes.has(id))nodes.set(id,{dataset:{},replaceChildren(){},add(){}});return nodes.get(id);},
 setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id),
 commandIdle(){},displayToolSelect(){},toast(){},
 api:async(path,record)=>{
  assert.equal(path,'/api/presets');requests.push(structuredClone(record));
  if(fail)throw Error('disk unavailable');
  if(record.action==='save'){
   const preset=disk.presets.find(p=>p.id===record.id);assert.ok(preset);
   preset.name=record.name;preset.profile=structuredClone(record.profile);
   disk.selected_id=preset.id;
  }else{assert.equal(record.action,'remember');disk.selected_id=record.selected_id;}
  disk.last_used=structuredClone(record.profile);return structuredClone(disk);
 }});
vm.runInContext(`
let tool=${JSON.stringify(tool)},settings=${JSON.stringify(settings)},operations=${JSON.stringify(operations)};
let formOperations=structuredClone(operations),formSettings=structuredClone(settings),data=null,token='local-test';
let presetStore=${JSON.stringify(disk)},presetTimer=null,presetRememberSelected=false,presetQueue=Promise.resolve(),presetSaving=false,presetError='';
function readSettings(){return structuredClone(formSettings);}
function readOperations(){return structuredClone(formOperations);}
function fillFields(){formSettings=structuredClone(settings);formOperations=structuredClone(operations);}
${source.slice(source.indexOf('function presetState('),source.indexOf('function grblTargetValues('))}
function edit(acceleration){formOperations.machine_acceleration_mm_s2=acceleration;scheduleRemember();}
function passive(acceleration){formOperations.machine_acceleration_mm_s2=acceleration;scheduleRemember({updateSelected:false});}
function state(){return presetState(true);}
`,ctx);
async function flush(){for(const[id,fn]of [...timers]){timers.delete(id);await fn();}}

ctx.edit([80,80,100]);assert.equal(ctx.state().saving,true);await flush();
assert.deepEqual(disk.presets[0].profile.operations.machine_acceleration_mm_s2,[80,80,100]);
assert.deepEqual(disk.last_used.operations.machine_acceleration_mm_s2,[80,80,100]);
assert.equal(disk.presets.length,2);assert.equal(disk.presets[0].name,'Pinus');
assert.deepEqual(disk.presets[1].profile.operations.machine_acceleration_mm_s2,[5,6,7]);
assert.equal(disk.presets[0].profile.operations.roughing_feed_mm_min,700);
assert.ok(!('bottom_mm' in disk.presets[0].profile.settings));
assert.match(nodes.get('presetStatus').textContent,/automaticamente/);
// Switching before the debounce expires must finish the old preset's save.
ctx.edit([90,91,92]);await ctx.applyPreset('b');
assert.deepEqual(disk.presets[0].profile.operations.machine_acceleration_mm_s2,[90,91,92]);
assert.equal(disk.selected_id,'b');
assert.deepEqual(disk.last_used.operations.machine_acceleration_mm_s2,[5,6,7]);
// Deselecting also flushes the selected preset before entering last-used mode.
ctx.edit([20,21,22]);nodes.get('presetSelect').value='';await nodes.get('presetSelect').onchange();
assert.deepEqual(disk.presets[1].profile.operations.machine_acceleration_mm_s2,[20,21,22]);
assert.equal(disk.selected_id,null);
ctx.edit([30,31,32]);await flush();
assert.deepEqual(disk.presets[1].profile.operations.machine_acceleration_mm_s2,[20,21,22]);
assert.deepEqual(disk.last_used.operations.machine_acceleration_mm_s2,[30,31,32]);
await ctx.applyPreset('a');const saved=structuredClone(disk.presets);
ctx.passive([1,2,3]);await flush();
assert.deepEqual(disk.presets,saved,'Loading project settings must not overwrite a named preset');
assert.deepEqual(disk.last_used.operations.machine_acceleration_mm_s2,[1,2,3]);
fail=true;ctx.edit([40,41,42]);await flush();
assert.deepEqual(disk.presets,saved);assert.match(ctx.state().error,/disk unavailable/);
assert.equal(ctx.state().saving,false);
const request=rememberProfileRequest(original,{presets:[],selected_id:null});
request.profile.operations.machine_acceleration_mm_s2[0]=99;
assert.equal(original.operations.machine_acceleration_mm_s2[0],10,'Queued request snapshots do not alias live settings');
console.log('Preset autosave: XYZ acceleration, same preset identity, independent presets, switch/deselect flush, automatic last-used, passive imports, write failures and snapshots passed.');
