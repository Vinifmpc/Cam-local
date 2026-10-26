const SHAPES=['rectangle','circle','ellipse','polygon','freehand'];
const KINDS=['boundary','keepout'];

// Choosing the region kind only opens these choices. Geometry is created by
// the drawing tool after an explicit shape choice, never by opening the picker.
export function createRegionPicker(container,{onChoose=()=>{},onCancel=()=>{}}={}){
 const document=container.ownerDocument;
 const buttons=[...container.querySelectorAll('[data-region-shape]')];
 if(buttons.length!==SHAPES.length||new Set(buttons.map(button=>button.dataset.regionShape)).size!==SHAPES.length||buttons.some(button=>!SHAPES.includes(button.dataset.regionShape)))throw Error('O seletor de regiões precisa das cinco formas, uma vez cada.');
 const title=container.querySelector('[data-region-picker-title]');
 const cancel=container.querySelector('[data-region-picker-cancel]');
 let kind=null,trigger=null,disabled=false,destroyed=false;
 const listeners=[];
 const state=()=>({open:kind!==null,kind,disabled});
 function listen(element,event,handler){element.addEventListener(event,handler);listeners.push([element,event,handler]);}
 function close({restoreFocus=false,cancel:notifyCancel=false}={}){
  const previousKind=kind,previousTrigger=trigger;
  kind=null;trigger=null;container.hidden=true;container.setAttribute('aria-hidden','true');
  delete container.dataset.kind;
  previousTrigger?.setAttribute('aria-expanded','false');
  if(previousKind!==null&&restoreFocus&&!previousTrigger?.disabled)previousTrigger?.focus({preventScroll:true});
  if(previousKind!==null&&notifyCancel)onCancel(previousKind);
  return state();
 }
 function show(nextKind,nextTrigger){
  if(!KINDS.includes(nextKind))throw Error('Tipo de região inválido. Use boundary ou keepout.');
  if(destroyed||disabled)return state();
  if(kind===nextKind&&trigger===nextTrigger)return close({restoreFocus:true,cancel:true});
  close();kind=nextKind;trigger=nextTrigger??null;
  container.hidden=false;container.setAttribute('aria-hidden','false');container.dataset.kind=kind;
  if(title)title.textContent=`${kind==='boundary'?'Keep In':'Keep Out'} · escolha a forma`;
  trigger?.setAttribute('aria-expanded','true');
  if(container.id)trigger?.setAttribute('aria-controls',container.id);
  buttons[0].focus({preventScroll:true});
  return state();
 }
 function choose(shape){
  if(!SHAPES.includes(shape))throw Error('Forma de região inválida.');
  if(kind===null||disabled||destroyed||buttons.find(button=>button.dataset.regionShape===shape).disabled)return state();
  const selectedKind=kind;close();onChoose(shape,selectedKind);
  return state();
 }
 for(const [index,button]of buttons.entries()){
  button.type='button';
  listen(button,'click',()=>choose(button.dataset.regionShape));
  listen(button,'keydown',event=>{
   if(kind===null||disabled||destroyed)return;
   let target;
   if(event.key==='ArrowRight'||event.key==='ArrowDown')target=(index+1)%buttons.length;
   else if(event.key==='ArrowLeft'||event.key==='ArrowUp')target=(index+buttons.length-1)%buttons.length;
   else if(event.key==='Home')target=0;
   else if(event.key==='End')target=buttons.length-1;
   if(target!==undefined){event.preventDefault();buttons[target].focus({preventScroll:true});}
  });
 }
 listen(document,'keydown',event=>{
  if(kind!==null&&event.key==='Escape'){
   event.preventDefault();close({restoreFocus:true,cancel:true});
  }
 });
 // Click runs after the target's handler. Clicking the other kind trigger can
 // switch the picker before this check, without issuing a spurious cancel.
 listen(document,'click',event=>{
  if(kind!==null&&!container.contains(event.target)&&!trigger?.contains(event.target))close({cancel:true});
 });
 if(cancel)listen(cancel,'click',()=>close({restoreFocus:true,cancel:true}));
 close();
 return {show,close,choose,state,setDisabled(value){
  disabled=Boolean(value);for(const button of buttons)button.disabled=disabled;
  if(disabled)close({cancel:true});
  return state();
 },destroy(){
  close();destroyed=true;
  for(const [element,event,handler]of listeners)element.removeEventListener(event,handler);
 }};
}
