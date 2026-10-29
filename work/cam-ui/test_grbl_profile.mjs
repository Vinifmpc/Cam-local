import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createGrblProfile,grblProfileValues} from './static/grbl_profile.js';

const target={machine_max_rate_mm_min:[1500,1500,1500],machine_acceleration_mm_s2:[80,80,100]};
const stored={machine_max_rate_mm_min:[1400,1400,900],machine_acceleration_mm_s2:[10,10,10]};
const copy=value=>JSON.parse(JSON.stringify(value));
let clock=0,calls=[],replyMode='verified',onRead=null,onApply=null;
async function api(path,body){
 calls.push({path,body:copy(body)});
 if(path==='/api/grbl/ports')return {ports:[{port:'COM7',description:'GRBL USB',hwid:'test'}]};
 if(path==='/api/grbl/read'){if(onRead)return onRead();return {read_id:'one-read',expires_in_s:300,values:copy(stored),settings:{'$110':1400},status:'read'};}
 if(path==='/api/grbl/apply'){
  if(onApply)return onApply();
  return {status:replyMode,verified:replyMode==='verified',values:copy(replyMode==='verified'?body.values:stored),message:replyMode==='verified'?'Gravação conferida.':'Gravação parcial.',backup_path:'backup.json'};
 }
 throw Error('Unexpected API '+path);
}
const controller=createGrblProfile({api,readProfile:()=>target,now:()=>clock});
assert.equal(controller.state().can_apply,false);
await assert.rejects(()=>controller.apply(),/Leia os valores/);
await controller.refresh();assert.equal(calls.length,1,'Port enumeration never reads or writes the controller');
controller.select({port:'COM7'});await controller.read();
assert.deepEqual(target.machine_acceleration_mm_s2,[80,80,100],'Reading actual settings preserves the edited target');
assert.deepEqual(controller.state().values,stored);assert.equal(controller.state().can_apply,true);
const first=controller.state();first.values.machine_max_rate_mm_min[0]=1;
assert.equal(controller.state().values.machine_max_rate_mm_min[0],1400,'Caller cannot mutate stored readback');
await assert.rejects(()=>controller.apply({read_id:'other'}),/não corresponde/);
assert.equal(calls.filter(c=>c.path.endsWith('apply')).length,0);
const verified=await controller.apply();assert.equal(verified.verified,true);
assert.deepEqual(calls.at(-1).body,{port:'COM7',baudrate:115200,read_id:'one-read',values:target});
assert.equal(controller.state().phase,'verified');assert.equal(controller.state().can_apply,false,'Every write consumes the read identifier');
await assert.rejects(()=>controller.apply(),/Leia os valores/);
await controller.read();controller.select({baudrate:57600});
assert.equal(controller.state().can_apply,false,'A changed connection requires a fresh read');
await controller.read();clock=300001;
await assert.rejects(()=>controller.apply(),/Leia os valores/);
clock=0;await controller.read();replyMode='partial';const partial=await controller.apply();
assert.equal(partial.status,'partial');assert.equal(controller.state().phase,'partial');assert.equal(controller.state().can_apply,false);
await controller.read();onApply=()=>{throw Error('timeout');};
await assert.rejects(()=>controller.apply(),/Gravação não confirmada.*Leia o GRBL/);
assert.equal(controller.state().can_apply,false,'A lost response never triggers automatic write retries');
onApply=null;onRead=()=>{throw Error('Porta ocupada pelo CNCjs');};
await assert.rejects(()=>controller.read(),/CNCjs/);assert.equal(controller.state().can_apply,false);
onRead=null;let finishRead;
onRead=()=>new Promise(resolve=>finishRead=resolve);
const pending=controller.read();assert.equal(controller.state().busy,true);
await assert.rejects(()=>controller.apply(),/Aguarde/);await assert.rejects(()=>controller.read(),/Aguarde/);assert.throws(()=>controller.select({port:'COM8'}),/Aguarde/);
finishRead({read_id:'two',expires_in_s:300,values:stored});await pending;onRead=null;

for(const invalid of [null,{},[],[1,2],['',1,1],[true,1,1],[0,1,1],[-1,1,1],[Infinity,1,1]]){
 assert.throws(()=>grblProfileValues({...target,machine_acceleration_mm_s2:invalid}));
}
assert.deepEqual(Object.keys(grblProfileValues({...target,machine_steps_per_mm:[800,800,800],unexpected:'$3=0'})).sort(),['machine_acceleration_mm_s2','machine_max_rate_mm_min'],'Only the two supported fields can reach a write request');

// Exercise the real form handlers with a mock serial service, without a model.
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
const controls=new Map();
function element(id){if(!controls.has(id))controls.set(id,{value:'',disabled:false,hidden:false,textContent:'',dataset:{},children:[],replaceChildren(...items){this.children=items;},add(option){this.children.push(option);},append(...items){this.children.push(...items);}});return controls.get(id);}
function Option(label,value){this.label=label;this.value=value;}
let remembered=0,dirtied=0;calls=[];replyMode='verified';
const ctx=vm.createContext({createGrblProfile,grblProfileValues,grblProfileRows:values=>values?['X','Y','Z'].map((axis,i)=>({axis,maximum:values.machine_max_rate_mm_min[i],acceleration:values.machine_acceleration_mm_s2[i]})):[],api,$:element,Option,document:{createElement:()=>({children:[],append(...items){this.children.push(...items);}})},fmt:String,toast(){},commandIdle(){},scheduleRemember(){remembered++;},dirty(){dirtied++;},data:null});
for(const [i,axis]of ['X','Y','Z'].entries()){element('machineMaxRate'+axis).value=String(target.machine_max_rate_mm_min[i]);element('machineAcceleration'+axis).value=String(target.machine_acceleration_mm_s2[i]);}
vm.runInContext(source.slice(source.indexOf('function grblTargetValues('),source.indexOf('function updateOperationControls(')),ctx);
assert.equal(element('grblApply').disabled,true);
await ctx.grblPorts();await ctx.grblRead({port:'COM7',baudrate:115200});
assert.equal(element('machineAccelerationX').value,'80','Actual readback has its own display and cannot overwrite edited targets');
assert.equal(element('grblReadValues').hidden,false);assert.equal(element('grblApply').disabled,false);
ctx.grblUseEstimate();assert.equal(element('machineAccelerationX').value,10);assert.equal(remembered,1);assert.equal(dirtied,0,'Import works before a STL exists');
element('machineAccelerationX').value='80';await ctx.grblApply();
assert.equal(calls.at(-1).body.values.machine_acceleration_mm_s2[0],80);
assert.equal(element('grblStatus').dataset.state,'verified');assert.equal(element('grblBackup').hidden,false);assert.equal(element('grblApply').disabled,true);
await ctx.grblRead();element('grblPort').value='COM8';element('grblPort').onchange();assert.equal(element('grblApply').disabled,true);
for(const id of ['grblPort','grblBaudrate','grblRefresh','grblRead','grblApply','grblUseEstimate','grblReadValues','grblValuesBody','grblStatus','grblBackup'])assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,`One control for ${id}`);
assert.ok(html.indexOf('class="grbl-profile"')>html.indexOf('</fieldset>'),'Controller transfer remains available in the constant timing model');
assert.match(html,/Desconecte a porta no CNCjs/);assert.match(html,/Editar estima o tempo · Gravar altera o GRBL/);
assert.match(html,/Algumas placas podem reiniciar/);
console.log('GRBL profile UI: explicit writes, preserved targets, read identity, timeout/partial handling, expiry, model-free import and real form handlers passed.');
