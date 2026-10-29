const AXES=['X','Y','Z'];
const FIELDS={machine_max_rate_mm_min:'maximum',machine_acceleration_mm_s2:'acceleration'};
const SETTINGS=new Set(['$110','$111','$112','$120','$121','$122']);
const format=value=>typeof value==='number'&&Number.isFinite(value)?new Intl.NumberFormat('pt-BR',{maximumFractionDigits:3}).format(value):'—';

export function profileValues(record){
 const result={};
 for(const key of Object.keys(FIELDS)){
  if(!Array.isArray(record?.[key])||record[key].length!==3)throw Error('Preencha os três eixos X, Y e Z.');
  result[key]=record[key].map(value=>{
   if((typeof value!=='number'&&typeof value!=='string')||String(value).trim()==='')throw Error('Preencha todos os máximos e acelerações.');
   const number=Number(value);
   if(!Number.isFinite(number)||number<.001||number>1000000)throw Error('Máximos e acelerações devem ficar entre 0,001 e 1.000.000.');
   return number;
  });
 }
 return result;
}

// Select fields explicitly so auth tokens and other connection metadata never
// enter an exported backup, even if the controller report contains them.
export function backupRecord(state,now=()=>new Date()){
 const report=state.last_report;
 if(!report?.before||typeof report.before!=='object')return null;
 const settings=source=>Object.fromEntries(Object.entries(source||{}).filter(([key,value])=>/^\$\d+$/.test(key)&&typeof value==='number'&&Number.isFinite(value)));
 let requested=settings(report.requested);
 try{if(Object.keys(FIELDS).every(key=>report.requested?.[key]!==undefined))requested=profileValues(report.requested);}catch{}
 return {format:1,application:'CAM Local · CNCjs',captured_utc:now().toISOString(),port:typeof state.port==='string'?state.port:'',
  before:settings(report.before),requested,after:settings(report.after),
  written_settings:Array.isArray(report.written_settings)?report.written_settings.filter(key=>SETTINGS.has(key)):[],
  status:typeof report.status==='string'?report.status:'unknown',verified:report.verified===true};
}

export function mountWidget({document:doc,controller,download,clipboard,now=()=>new Date()}){
 const $=id=>{const element=doc.getElementById(id);if(!element)throw Error('Controle ausente: '+id);return element;};
 let state=controller.state(),pending=false,backupText='',destroyed=false;
 const listeners=[];
 const listen=(id,event,callback)=>{const element=$(id);element.addEventListener(event,callback);listeners.push(()=>element.removeEventListener(event,callback));};
 function feedback(text='',error=false){$('uiFeedback').textContent=text;$('uiFeedback').dataset.error=String(error);$('uiFeedback').hidden=!text;}
 function targets(){return profileValues(Object.fromEntries(Object.entries(FIELDS).map(([key,prefix])=>[key,AXES.map(axis=>$(prefix+axis).value)])));}
 function render(next=controller.state()){
  if(destroyed)return;
  state=next||{};const busy=pending||state.busy===true,connected=state.connected===true;
  $('connectionBadge').textContent=connected?'Conexão do CNCjs':'Aguardando CNCjs';$('connectionBadge').dataset.state=connected?'online':'offline';
  $('connectionPort').textContent=state.port||'Sem porta selecionada';$('machineState').textContent=state.machine_state||'—';
  $('controllerStatus').textContent=state.message||'Aguardando a conexão do CNCjs. Nenhum valor será gravado automaticamente.';
  $('controllerStatus').dataset.state=state.phase||'idle';
  $('readProfile').disabled=busy||!connected||state.can_read===false;
  $('applyProfile').disabled=busy||state.can_apply!==true;
  $('readProfile').textContent=state.phase==='reading'?'Lendo…':'Ler do GRBL';
  $('applyProfile').textContent=state.phase==='writing'?'Gravando…':'Gravar no GRBL';
  let actual=null;try{if(state.values)actual=profileValues(state.values);}catch{}
  $('useReadback').disabled=busy||!actual;
  for(const [key,prefix]of Object.entries(FIELDS))for(const [i,axis]of AXES.entries()){
   $(prefix+axis).disabled=busy;
   $('actual'+prefix[0].toUpperCase()+prefix.slice(1)+axis).textContent=actual?format(actual[key][i]):'—';
  }
  const written=state.last_report?.written_settings?.filter(key=>SETTINGS.has(key))||[];
  $('writtenSettings').hidden=!written.length;$('writtenSettings').textContent=written.length?'Parâmetros aceitos pelo GRBL: '+written.join(', ')+'.':'';
  const backup=backupRecord(state,now);backupText=backup?JSON.stringify(backup,null,2):'';
  $('backupPanel').hidden=!backupText;$('backupJson').value=backupText;
 }
 async function perform(action){
  if(pending||state.busy)return;
  pending=true;feedback();render(state);
  try{return await action();}catch(error){feedback(error.message||String(error),true);return null;}
  finally{pending=false;render();}
 }
 listen('readProfile','click',()=>perform(()=>controller.read()));
 listen('applyProfile','click',()=>perform(()=>controller.apply(targets())));
 listen('useReadback','click',()=>{
  try{const actual=profileValues(state.values);for(const [key,prefix]of Object.entries(FIELDS))for(const [i,axis]of AXES.entries())$(prefix+axis).value=String(actual[key][i]);feedback('Valores lidos copiados para os campos. Nenhuma gravação foi executada.');}
  catch(error){feedback(error.message,true);}
 });
 listen('copyBackup','click',async()=>{
  if(!backupText)return;
  try{
   if(!clipboard?.writeText)throw Error('Clipboard unavailable');
   await clipboard.writeText(backupText);feedback('Backup JSON copiado.');
  }catch{
   $('backupPanel').open=true;$('backupJson').focus();$('backupJson').select();feedback('Texto selecionado. Use Ctrl+C para copiar o backup.');
  }
 });
 listen('saveBackup','click',()=>{
  if(!backupText)return;
  try{
   if(!download)throw Error('O download não está disponível neste widget.');
   download(backupText,'grbl-perfil-'+now().toISOString().replace(/[:.]/g,'-')+'.json');
   feedback('Download solicitado. Se o CNCjs bloquear, use Copiar JSON.');
  }catch(error){$('backupPanel').open=true;feedback(error.message+' Use Copiar JSON.',true);}
 });
 const unsubscribe=controller.subscribe(render);render(state);
 return {targets,render,destroy(){destroyed=true;for(const off of listeners)off();if(typeof unsubscribe==='function')unsubscribe();}};
}
