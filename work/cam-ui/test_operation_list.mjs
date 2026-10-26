import assert from 'node:assert/strict';
import {operationListFromOptions,operationOptionsFromList,patchOperationList,moveOperation,createOperationList,mergeOperationOptions} from './static/operation_list.js';

const defaults=operationListFromOptions();
assert.deepEqual(defaults,{order:['roughing','cutout','drill'],enabled:{roughing:true,cutout:false,drill:false}});
const reversed=operationListFromOptions({order:'cutout_then_roughing',roughing_enabled:false,cutout_enabled:true});
assert.deepEqual(operationOptionsFromList(reversed),{order:'cutout_then_roughing',operation_sequence:['cutout','roughing','drill'],roughing_enabled:false,cutout_enabled:true,drill_enabled:false});
assert.deepEqual(moveOperation(defaults,'cutout',0).order,['cutout','roughing','drill']);
assert.deepEqual(defaults.order,['roughing','cutout','drill']);
for(const patch of [{order:null},{order:['roughing','roughing']},{order:['cutout']},{order:['roughing','drill']},{order:['roughing','cutout','cutout']},{order:['unknown','cutout']},{enabled:{roughing:'false'}},{enabled:{unknown:true}},null])assert.throws(()=>patchOperationList(defaults,patch));
assert.equal(patchOperationList(defaults,{enabled:{roughing:false}}).enabled.roughing,false,'All disabled is editable; calculate performs the required-operation check');
const withDrill=operationListFromOptions({operation_sequence:['roughing','drill','cutout'],drill_enabled:true});
assert.deepEqual(withDrill.order,['roughing','drill','cutout']);
assert.equal(withDrill.enabled.drill,true);
assert.deepEqual(patchOperationList(withDrill,{order:['cutout','roughing']}).order,['cutout','drill','roughing'],'A legacy command preserves Drill position');
assert.equal(operationOptionsFromList(moveOperation(withDrill,'drill',0)).order,'roughing_then_cutout','Legacy order ignores Drill position');
assert.deepEqual(operationOptionsFromList(withDrill).operation_sequence,withDrill.order);
const priorOptions={...operationOptionsFromList(withDrill),drill_allow_helix:true,drill_compensate_facets:true};
const legacyPatch=mergeOperationOptions(priorOptions,{order:'cutout_then_roughing'});
assert.deepEqual(legacyPatch.operation_sequence,['cutout','drill','roughing'],'Legacy config.patch order must change the active three-operation sequence');
assert.equal(legacyPatch.drill_enabled,true);assert.equal(legacyPatch.drill_allow_helix,true);assert.equal(legacyPatch.drill_compensate_facets,true);
assert.deepEqual(priorOptions.operation_sequence,['roughing','drill','cutout'],'Merging a command does not mutate prior state');
assert.deepEqual(mergeOperationOptions(priorOptions,{operation_sequence:['drill','cutout','roughing']}).operation_sequence,['drill','cutout','roughing']);
assert.throws(()=>mergeOperationOptions(priorOptions,{order:'invalid'}),/Ordem/);

// Small deterministic DOM fixture exercises the actual pointer handlers.
const document={activeElement:null,defaultView:{events:{},addEventListener(name,fn){this.events[name]=fn;}}};
class Element{
 constructor(){this.dataset={};this.children=[];this.ownerDocument=document;this.attributes={};this.style={};this.events={};this.captured=null;this.checked=false;
  const classes=new Set();this.classList={add:(...keys)=>keys.forEach(k=>classes.add(k)),remove:(...keys)=>keys.forEach(k=>classes.delete(k)),contains:k=>classes.has(k),toggle:(k,v)=>{if(v??!classes.has(k))classes.add(k);else classes.delete(k);}};}
 setAttribute(key,value){this.attributes[key]=value;}
 addEventListener(key,fn){(this.events[key]??=[]).push(fn);}
 emit(key,event={}){for(const fn of this.events[key]||[])fn(event);}
 focus(){document.activeElement=this;}
 append(...nodes){for(const node of nodes){if(node.parentNode)node.parentNode.children=node.parentNode.children.filter(x=>x!==node);node.parentNode=this;this.children.push(node);}}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 querySelector(query){return this.lookup[query];}
 querySelectorAll(){return this.children;}
 getBoundingClientRect(){return {top:this.parentNode.children.indexOf(this)*65,height:58};}
 setPointerCapture(id){this.captured=id;}
 hasPointerCapture(id){return this.captured===id;}
 releasePointerCapture(){this.captured=null;}
}
const container=new Element(),rows={},grips={},checks={},numbers={},buttons={};
for(const id of ['roughing','cutout','drill']){
 const row=rows[id]=new Element();row.dataset.operation=id;
 const grip=grips[id]=new Element(),check=checks[id]=new Element(),number=numbers[id]=new Element(),button=buttons[id]=new Element();
 check.checked=id==='roughing';row.append(grip,check,number,button);
 row.lookup={'[data-drag-operation]':grip,'input[type="checkbox"]':check,'[data-operation-number]':number,'[data-edit-operation]':button};container.append(row);
}
const changes=[],announcements=[],selected=[];
const controller=createOperationList(container,{onChange:s=>changes.push(s),announce:t=>announcements.push(t),onSelect:id=>{selected.push(id);controller.select(id);}});
const pointer=(y,id=1)=>({button:0,isPrimary:true,pointerId:id,clientY:y,preventDefault(){}});
const keys=key=>({key,preventDefault(){}});
const domOrder=()=>container.children.map(row=>row.dataset.operation);
checks.cutout.checked=true;checks.cutout.emit('change');assert.equal(changes.length,1);assert.equal(controller.getState().enabled.cutout,true);
grips.roughing.emit('pointerdown',pointer(29));grips.roughing.emit('pointermove',pointer(94,2));assert.equal(rows.roughing.style.transform,undefined);
grips.roughing.emit('pointermove',pointer(94));assert.ok(rows.roughing.classList.contains('is-dragging'));
assert.ok(rows.cutout.classList.contains('drop-target'));
grips.roughing.emit('pointerup',pointer(94));
assert.deepEqual(domOrder(),['cutout','roughing','drill']);assert.equal(changes.length,2);assert.equal(numbers.cutout.textContent,'1');assert.equal(grips.roughing.captured,null);
assert.equal(grips.roughing.attributes['aria-label'],'Mover Rough, posição 2 de 3');assert.equal(document.activeElement,grips.roughing);
grips.roughing.emit('pointerdown',pointer(94));grips.roughing.emit('pointermove',pointer(29));grips.roughing.emit('keydown',keys('Escape'));
assert.deepEqual(domOrder(),['cutout','roughing','drill']);assert.equal(changes.length,2);assert.equal(rows.roughing.style.transform,'');
for(const cancel of ['pointercancel','lostpointercapture','blur']){
 grips.roughing.emit('pointerdown',pointer(94));grips.roughing.emit('pointermove',pointer(29));
 if(cancel==='blur')document.defaultView.events.blur();else grips.roughing.emit(cancel,pointer(29));
 assert.equal(changes.length,2);assert.equal(grips.roughing.captured,null);
}
grips.roughing.emit('pointerdown',pointer(94));grips.roughing.emit('pointerup',pointer(96));assert.equal(changes.length,2,'A click or tiny drag must not invalidate a path');
checks.roughing.checked=false;checks.roughing.emit('change');assert.ok(rows.roughing.classList.contains('is-disabled'));
grips.roughing.emit('keydown',keys('ArrowUp'));assert.deepEqual(domOrder(),['roughing','cutout','drill']);assert.equal(controller.getState().enabled.roughing,false);
const count=changes.length;grips.roughing.emit('keydown',keys('ArrowUp'));assert.equal(changes.length,count,'Moving beyond the boundary is a no-op');
grips.roughing.emit('keydown',keys('End'));assert.deepEqual(domOrder(),['cutout','drill','roughing']);
grips.roughing.emit('keydown',keys('Home'));assert.deepEqual(domOrder(),['roughing','cutout','drill']);
buttons.cutout.emit('click');assert.deepEqual(selected,['cutout']);assert.ok(rows.cutout.classList.contains('is-selected'));
const snapshot=controller.getState();snapshot.order.reverse();assert.deepEqual(domOrder(),['roughing','cutout','drill']);
const before=changes.length;controller.setState(reversed);assert.deepEqual(domOrder(),reversed.order);assert.equal(changes.length,before,'Restore must not emit a user edit');
assert.throws(()=>controller.setState({order:['cutout','cutout']}));assert.deepEqual(controller.getState(),reversed);
checks.drill.checked=true;checks.drill.emit('change');assert.equal(controller.getState().enabled.drill,true);
grips.drill.emit('pointerdown',pointer(159));grips.drill.emit('pointermove',pointer(29));grips.drill.emit('pointerup',pointer(29));
assert.deepEqual(domOrder(),['drill','cutout','roughing']);assert.equal(numbers.drill.textContent,'1');
assert.equal(rows.drill.attributes['aria-setsize'],'3');assert.equal(grips.drill.attributes['aria-label'],'Mover Drill, posição 1 de 3');
assert.ok(announcements.length>3);
controller.setLocked(true);
assert.equal(grips.roughing.disabled,true);assert.equal(grips.drill.disabled,true);assert.equal(checks.roughing.disabled,true);assert.equal(checks.cutout.disabled,true);assert.equal(checks.drill.disabled,false);
const lockedState=controller.getState(),lockedChanges=changes.length;
grips.roughing.emit('keydown',keys('Home'));grips.roughing.emit('pointerdown',pointer(159));grips.roughing.emit('pointermove',pointer(29));grips.roughing.emit('pointerup',pointer(29));
checks.roughing.checked=!lockedState.enabled.roughing;checks.roughing.emit('change');
assert.deepEqual(controller.getState(),lockedState);assert.equal(changes.length,lockedChanges,'Locked smart policy ignores reorder and Rough/Cutout toggles');
checks.drill.checked=!lockedState.enabled.drill;checks.drill.emit('change');assert.equal(changes.length,lockedChanges+1,'Drill remains optional in smart mode');
controller.setLocked(false);assert.equal(grips.roughing.disabled,false);assert.equal(checks.cutout.disabled,false);
console.log('Operation list passed: activation, actual pointer reorder, disabled rows, no-op clicks, Escape/cancel/blur, keyboard/focus, restore, validation and immutable state.');
