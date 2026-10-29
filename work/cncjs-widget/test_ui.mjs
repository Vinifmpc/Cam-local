import assert from 'node:assert/strict';
import fs from 'node:fs';
import {mountWidget,profileValues,backupRecord} from './app.js';

const clone=value=>JSON.parse(JSON.stringify(value));
const target={machine_max_rate_mm_min:[1500,1500,1500],machine_acceleration_mm_s2:[80,80,100]};
const actual={machine_max_rate_mm_min:[1400,1400,900],machine_acceleration_mm_s2:[10,10,10]};
function fixture(){
 const html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8'),elements=new Map();
 for(const [,id]of html.matchAll(/id="([^"]+)"/g))elements.set(id,{value:'',textContent:'',disabled:false,hidden:false,dataset:{},events:new Map(),
  addEventListener(name,fn){this.events.set(name,fn);},removeEventListener(name,fn){if(this.events.get(name)===fn)this.events.delete(name);},
  focus(){this.focused=true;},select(){this.selected=true;},async click(){if(!this.disabled)return this.events.get('click')?.();}});
 for(const [i,axis]of ['X','Y','Z'].entries()){elements.get('maximum'+axis).value=String(target.machine_max_rate_mm_min[i]);elements.get('acceleration'+axis).value=String(target.machine_acceleration_mm_s2[i]);}
 let state={connected:false,port:'',machine_state:null,busy:false,phase:'idle',message:'Waiting',can_apply:false,values:null,last_report:null},subscriber,reads=0,writes=[],resolveRead=null;
 const controller={state:()=>clone(state),subscribe(fn){subscriber=fn;return ()=>{subscriber=null;};},
  emit(patch){state={...state,...patch};subscriber?.(clone(state));},
  async read(){reads++;controller.emit({busy:true,phase:'reading'});if(resolveRead)await resolveRead;controller.emit({busy:false,phase:'read',values:actual,can_apply:true,message:'Read complete'});return {values:actual};},
  async apply(values){writes.push(clone(values));controller.emit({busy:true,phase:'writing',can_apply:false});controller.emit({busy:false,phase:'verified',message:'Written and checked',values,last_report:{before:{'$3':6,'$120':10,'$121':10,'$122':10},requested:values,after:{'$3':6,'$120':80,'$121':80,'$122':100},written_settings:['$120','$121','$122'],status:'verified',verified:true}});return {verified:true};}};
 const downloads=[],doc={getElementById:id=>elements.get(id)};
 const mounted=mountWidget({document:doc,controller,download:(text,name)=>downloads.push({text,name}),now:()=>new Date('2026-10-27T12:00:00Z')});
 return {elements,controller,mounted,downloads,get reads(){return reads;},get writes(){return writes;},get subscriber(){return subscriber;},set pendingRead(value){resolveRead=value;}};
}

const f=fixture(),$=id=>f.elements.get(id);
assert.equal(f.reads,0);assert.equal(f.writes.length,0,'Mounting never queries or writes controller');
assert.equal($('readProfile').disabled,true);assert.equal($('applyProfile').disabled,true);
assert.deepEqual(f.mounted.targets(),target,'Initial target keeps user requested values');
f.controller.emit({connected:true,port:'COM7',machine_state:'Idle',can_read:true});
assert.equal($('readProfile').disabled,false);assert.equal($('connectionPort').textContent,'COM7');
await $('readProfile').click();
assert.equal(f.reads,1);assert.equal(f.writes.length,0);
assert.deepEqual(f.mounted.targets(),target,'Reading actual machine values preserves edited targets');
assert.equal($('actualMaximumX').textContent,'1.400');assert.equal($('actualAccelerationX').textContent,'10');
assert.equal($('applyProfile').disabled,false);
$('accelerationX').value='0';await $('applyProfile').click();
assert.equal(f.writes.length,0,'Invalid input never reaches controller');
assert.equal($('uiFeedback').dataset.error,'true');
$('accelerationX').value='80';await $('applyProfile').click();
assert.deepEqual(f.writes,[target]);assert.equal($('applyProfile').disabled,true,'A write cannot be repeated without reading');
assert.equal($('controllerStatus').dataset.state,'verified');assert.equal($('backupPanel').hidden,false);
const backup=JSON.parse($('backupJson').value);
assert.deepEqual(backup.before,{'$3':6,'$120':10,'$121':10,'$122':10});
assert.deepEqual(backup.requested,target);assert.equal(backup.verified,true);
await $('copyBackup').click();assert.equal($('backupJson').selected,true,'Unavailable clipboard selects JSON for manual copy');
await $('saveBackup').click();assert.equal(f.downloads.length,1);assert.match(f.downloads[0].name,/grbl-perfil-2026-10-27/);
f.controller.emit({phase:'error',message:'Disconnected',connected:false,values:null,can_apply:false});
assert.equal($('applyProfile').disabled,true);assert.equal($('useReadback').disabled,true);
assert.equal($('actualMaximumX').textContent,'—','Disconnected invalidated readback is not presented as current');
f.controller.emit({connected:true,values:actual});await $('useReadback').click();
assert.deepEqual(f.mounted.targets(),actual);assert.equal(f.writes.length,1,'Using readback only edits the target');

const pending=fixture();pending.controller.emit({connected:true,port:'COM8',machine_state:'Idle'});
let finish;pending.pendingRead=new Promise(resolve=>finish=resolve);
const read=pending.elements.get('readProfile').click();
assert.equal(pending.elements.get('maximumX').disabled,true,'Targets freeze during a transfer');
assert.equal(pending.elements.get('readProfile').disabled,true);finish();await read;
assert.equal(pending.elements.get('maximumX').disabled,false);
pending.controller.emit({busy:true,phase:'writing'});assert.equal(pending.elements.get('applyProfile').disabled,true);
f.mounted.destroy();assert.equal(f.subscriber,null);assert.equal($('readProfile').events.size,0);

for(const bad of [null,{},[],[10,10],[0,10,10],[true,10,10],['',10,10],[Infinity,10,10],[1000001,10,10]])assert.throws(()=>profileValues({...target,machine_acceleration_mm_s2:bad}));
const redacted=backupRecord({port:'COM7',token:'SECRET',last_report:{before:{'$3':6,token:'SECRET'},after:{'$3':6,token:'SECRET'},requested:{...target,token:'SECRET'},token:'SECRET',status:'partial',written_settings:['$120','$3'],verified:false}},()=>new Date('2026-10-27T12:00:00Z'));
assert.equal(JSON.stringify(redacted).includes('SECRET'),false,'Backups never include authentication tokens');
assert.deepEqual(redacted.written_settings,['$120']);assert.equal(redacted.verified,false);
assert.equal(backupRecord({last_report:null}),null);
const html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8');
assert.match(html,/Usa a conexão aberta pelo CNCjs/);assert.match(html,/type="module" src="\.\/boot.js"/);
assert.doesNotMatch(html,/https?:\/\//,'Widget UI has no external network or font dependency');
console.log('CNCjs widget UI: targets preserved, explicit writes, disabled transfer controls, readback, backups, clipboard fallback and auth redaction passed.');
