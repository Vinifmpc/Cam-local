// One list state feeds UI, saved OperationSettings, simulation and NC order.
export const OPERATION_IDS=['roughing','cutout','drill'];
const names={roughing:'Rough',cutout:'Cutout',drill:'Drill'};
function normalizedOrder(order,current=OPERATION_IDS){
 if(!Array.isArray(order)||![2,3].includes(order.length)||new Set(order).size!==order.length||order.some(id=>!OPERATION_IDS.includes(id))||(order.length===2&&order.includes('drill')))throw Error('order deve conter roughing, drill e cutout, uma vez cada; a ordem legada aceita roughing e cutout.');
 if(order.length===3)return [...order];
 // Legacy two-operation commands reorder Rough/Cutout without moving Drill.
 let index=0;return current.map(id=>id==='drill'?id:order[index++]);
}
export function operationListFromOptions(options={}){
 const legacy=options.order==='cutout_then_roughing'?['cutout','roughing','drill']:['roughing','cutout','drill'];
 return {order:options.operation_sequence==null?legacy:normalizedOrder(options.operation_sequence),
  enabled:{roughing:options.roughing_enabled??true,cutout:options.cutout_enabled??false,drill:options.drill_enabled??false}};
}
export function patchOperationList(state,patch={}){
 if(!patch||typeof patch!=='object'||Array.isArray(patch)||Object.keys(patch).some(key=>!['order','enabled'].includes(key)))throw Error('Configuração da lista de operações inválida.');
 const order=normalizedOrder(patch.order===undefined?state.order:patch.order,state.order);
 const enabled={...state.enabled};
 if(patch.enabled!==undefined){
  if(!patch.enabled||typeof patch.enabled!=='object'||Array.isArray(patch.enabled))throw Error('enabled deve ser um objeto de booleanos.');
  for(const [id,value]of Object.entries(patch.enabled)){
   if(!OPERATION_IDS.includes(id)||typeof value!=='boolean')throw Error('Ativação inválida: use roughing, drill ou cutout com true ou false.');
   enabled[id]=value;
  }
 }
 return {order:[...order],enabled};
}
export function operationOptionsFromList(state){
 const next=patchOperationList(state);
 return {order:next.order.indexOf('roughing')<next.order.indexOf('cutout')?'roughing_then_cutout':'cutout_then_roughing',operation_sequence:[...next.order],roughing_enabled:next.enabled.roughing,cutout_enabled:next.enabled.cutout,drill_enabled:next.enabled.drill};
}
export function mergeOperationOptions(previous={},patch={}){
 const next={...previous,...patch};
 if(Object.hasOwn(patch,'order')&&!Object.hasOwn(patch,'operation_sequence')){
  if(!['roughing_then_cutout','cutout_then_roughing'].includes(patch.order))throw Error('Ordem de operações inválida.');
  const order=patch.order==='cutout_then_roughing'?['cutout','roughing']:['roughing','cutout'];
  next.operation_sequence=patchOperationList(operationListFromOptions(previous),{order}).order;
 }
 return next;
}
export function moveOperation(state,id,index){
 if(!OPERATION_IDS.includes(id)||!Number.isInteger(index)||index<0||index>=state.order.length)throw Error('Posição da operação inválida.');
 const order=state.order.filter(key=>key!==id);order.splice(index,0,id);return patchOperationList(state,{order});
}
export function createOperationList(container,{onChange=()=>{},onSelect=()=>{},announce=()=>{}}={}){
 const rows=new Map([...container.querySelectorAll('[data-operation]')].map(row=>[row.dataset.operation,row]));
 const checkbox=id=>rows.get(id).querySelector('input[type="checkbox"]');
 const handle=id=>rows.get(id).querySelector('[data-drag-operation]');
 let state={order:[...OPERATION_IDS],enabled:Object.fromEntries(OPERATION_IDS.map(id=>[id,checkbox(id).checked]))},selected='roughing',drag=null,locked=false;
 const clone=()=>patchOperationList(state);
 function render(){
  const active=container.ownerDocument.activeElement;
  if([...container.children].some((row,i)=>row.dataset.operation!==state.order[i]))container.append(...state.order.map(id=>rows.get(id)));
  for(const [index,id]of state.order.entries()){
   const row=rows.get(id);checkbox(id).checked=state.enabled[id];
   row.classList.toggle('is-disabled',!state.enabled[id]);row.classList.toggle('is-selected',id===selected);
   row.setAttribute('aria-posinset',String(index+1));row.setAttribute('aria-setsize',String(state.order.length));
   row.querySelector('[data-operation-number]').textContent=String(index+1);
   handle(id).setAttribute('aria-label',`Mover ${names[id]}, posição ${index+1} de ${state.order.length}`);
   handle(id).disabled=locked;checkbox(id).disabled=locked&&id!=='drill';
  }
  if(active&&container.contains(active)&&container.ownerDocument.activeElement!==active)active.focus({preventScroll:true});
 }
 function cancelDrag(){
  if(!drag)return;const current=drag;drag=null;
  for(const row of rows.values()){row.classList.remove('is-dragging','drop-target');row.style.transform='';}
  container.classList.remove('is-reordering');current.handle.setAttribute('aria-pressed','false');
  if(current.handle.hasPointerCapture(current.pointer))current.handle.releasePointerCapture(current.pointer);
 }
 function setState(patch,{notify=false}={}){
  const next=patchOperationList(state,patch),changed=JSON.stringify(next)!==JSON.stringify(state);
  cancelDrag();state=next;render();
  if(changed&&notify)onChange(clone());
  return clone();
 }
 function moveTo(id,index){
  if(locked)return;
  const next=moveOperation(state,id,index),changed=next.order.join()!==state.order.join();
  setState(next,{notify:true});
  if(changed)announce(`${names[id]} na posição ${index+1} de ${state.order.length}. Recalcule os percursos.`);
  handle(id).focus({preventScroll:true});
 }
 function updateDrag(event){
  if(!drag||event.pointerId!==drag.pointer)return;
  const dy=event.clientY-drag.y;if(Math.abs(dy)>4)drag.moved=true;
  if(!drag.moved)return;
  rows.get(drag.id).classList.add('is-dragging');container.classList.add('is-reordering');
  const limit=drag.centers.at(-1)-drag.centers[0];rows.get(drag.id).style.transform=`translateY(${Math.max(-limit,Math.min(limit,dy))}px)`;
  drag.target=drag.centers.reduce((best,center,index)=>Math.abs(center-event.clientY)<Math.abs(drag.centers[best]-event.clientY)?index:best,0);
  for(const [index,id]of state.order.entries())rows.get(id).classList.toggle('drop-target',index===drag.target&&id!==drag.id);
 }
 for(const id of OPERATION_IDS){
  const grip=handle(id);grip.draggable=false;
  checkbox(id).addEventListener('change',()=>{
   if(locked&&id!=='drill'){render();return;}
   setState({enabled:{[id]:checkbox(id).checked}},{notify:true});
   announce(`${names[id]} ${state.enabled[id]?'ativado':'desativado'}.`);
  });
  rows.get(id).querySelector('[data-edit-operation]').addEventListener('click',()=>onSelect(id));
  grip.addEventListener('pointerdown',event=>{
   if(locked||event.button!==0||event.isPrimary===false||drag)return;
   event.preventDefault();grip.focus({preventScroll:true});
   drag={id,handle:grip,pointer:event.pointerId,y:event.clientY,moved:false,target:state.order.indexOf(id),
    centers:state.order.map(key=>{const rect=rows.get(key).getBoundingClientRect();return rect.top+rect.height/2;})};
   grip.setAttribute('aria-pressed','true');grip.setPointerCapture(event.pointerId);
  });
  grip.addEventListener('pointermove',updateDrag);
  grip.addEventListener('pointerup',event=>{
   if(!drag||event.pointerId!==drag.pointer)return;
   updateDrag(event);const current=drag;cancelDrag();
   if(current.moved)moveTo(current.id,current.target);
  });
  grip.addEventListener('pointercancel',cancelDrag);grip.addEventListener('lostpointercapture',cancelDrag);
  grip.addEventListener('keydown',event=>{
   if(event.key==='Escape'){cancelDrag();return;}
   const index=state.order.indexOf(id),target={ArrowUp:Math.max(0,index-1),ArrowDown:Math.min(state.order.length-1,index+1),Home:0,End:state.order.length-1}[event.key];
   if(target!==undefined){event.preventDefault();moveTo(id,target);}
  });
 }
 container.ownerDocument.defaultView?.addEventListener('blur',cancelDrag);
 render();
 return {getState:clone,setState,cancelDrag,setLocked(value){locked=!!value;cancelDrag();render();},select(id){if(!OPERATION_IDS.includes(id))throw Error('Operação inválida.');selected=id;render();}};
}
