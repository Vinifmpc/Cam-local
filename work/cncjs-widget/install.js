export const WIDGET_ID='custom:cam-local-profile';
export const BACKUP_KEY='cam-local-profile.workspace-backup.v1';
const DEFAULT_PRIMARY=['connection','console','grbl','marlin','smoothie','tinyg','webcam'];
const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const clone=value=>JSON.parse(JSON.stringify(value));

function requireObject(parent,key,label){
 if(!own(parent,key)){parent[key]={};return parent[key];}
 if(!plain(parent[key]))throw Error('Configuração '+label+' inválida. O espaço de trabalho não foi alterado.');
 return parent[key];
}
function requireWidgetList(value,label){
 if(!Array.isArray(value)||value.some(id=>typeof id!=='string'))throw Error('Lista de widgets '+label+' inválida. O espaço de trabalho não foi alterado.');
 return value;
}
function safeOwnWidget(value){
 if(!plain(value))return null;
 const result={};
 for(const key of ['disabled','minimized','title'])if(own(value,key))result[key]=value[key];
 if(typeof value.url==='string'){
  try{const url=new URL(value.url);url.username='';url.password='';url.search='';url.hash='';result.url=url.href;}
  catch{result.url='';}
 }
 return result;
}

// Only the browser workspace is updated. This function neither opens a socket
// nor sends serial commands; session/authentication data remain in place.
export function installWidget(storage,{url,version='1.11.5',origin=globalThis.location?.origin,now=()=>new Date()}={}){
 let target;
 try{target=new URL(url);}catch{throw Error('Endereço do widget inválido.');}
 if(!origin||target.origin!==origin||!['http:','https:'].includes(target.protocol)||target.username||target.password||target.search||target.hash)throw Error('A ativação exige um widget no mesmo endereço do CNCjs, sem credenciais no link.');
 if(typeof version!=='string'||!/^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(version))throw Error('Versão do CNCjs inválida.');
 const previous=storage.getItem('cnc');
 let record;
 if(previous===null)record={version,state:{}};
 else{
  try{record=JSON.parse(previous);}catch{throw Error('O CNCjs possui uma configuração JSON inválida. Nenhum ajuste foi substituído.');}
  if(!plain(record))throw Error('O CNCjs possui uma configuração inválida. Nenhum ajuste foi substituído.');
 }
 const before=clone(record);
 const state=requireObject(record,'state','principal');
 const workspace=requireObject(state,'workspace','do espaço de trabalho');
 const container=requireObject(workspace,'container','dos painéis');
 const primary=requireObject(container,'primary','do painel principal');
 const widgets=requireObject(state,'widgets','dos widgets');
 const primaryList=own(primary,'widgets')?requireWidgetList(primary.widgets,'do painel principal'):DEFAULT_PRIMARY;
 const secondary=container.secondary;
 if(secondary!==undefined&&!plain(secondary))throw Error('Configuração do painel secundário inválida. O espaço de trabalho não foi alterado.');
 if(secondary&&own(secondary,'widgets'))requireWidgetList(secondary.widgets,'do painel secundário');
 const previousWidget=widgets[WIDGET_ID];
 if(previousWidget!==undefined&&!plain(previousWidget))throw Error('Configuração anterior do perfil GRBL inválida. O espaço de trabalho não foi alterado.');
 if(!own(record,'version'))record.version=version;
 primary.widgets=[WIDGET_ID,...primaryList.filter(id=>id!==WIDGET_ID)];
 primary.show=true;
 if(secondary&&own(secondary,'widgets'))secondary.widgets=secondary.widgets.filter(id=>id!==WIDGET_ID);
 widgets[WIDGET_ID]={...(previousWidget||{}),disabled:false,minimized:false,title:'CAM · Perfil GRBL',url:target.href};
 const changed=JSON.stringify(before)!==JSON.stringify(record);
 if(changed){
  if(storage.getItem(BACKUP_KEY)===null){
   const oldWorkspace=before.state?.workspace;
   const backup={format:1,created_utc:now().toISOString(),workspace:{container:{}},widget:safeOwnWidget(before.state?.widgets?.[WIDGET_ID])};
   // Snapshot only the panel locations changed by this installer. Session
   // tokens, credentials, and unrelated widgets never enter this backup.
   for(const panel of ['primary','secondary']){
    const old=oldWorkspace?.container?.[panel];
    if(!plain(old))continue;
    const selected={};
    if(own(old,'show'))selected.show=old.show;
    if(Array.isArray(old.widgets))selected.widgets=clone(old.widgets);
    backup.workspace.container[panel]=selected;
   }
   storage.setItem(BACKUP_KEY,JSON.stringify(backup));
  }
  const encoded=JSON.stringify(record);
  storage.setItem('cnc',encoded);
  if(storage.getItem('cnc')!==encoded)throw Error('O CNCjs atualizou a configuração durante a ativação. Abra este link novamente com o painel fechado.');
 }
 return {status:'installed',widget_id:WIDGET_ID,url:target.href,already_installed:!changed,backup_key:storage.getItem(BACKUP_KEY)!==null?BACKUP_KEY:null};
}

export function activateInstallPage({document:doc,storage,location,version='1.11.5',schedule=globalThis.setTimeout}){
 const status=doc.getElementById('installStatus'),detail=doc.getElementById('installDetail'),back=doc.getElementById('returnCncjs');
 const destination=new URL('/',location.href);back.href=destination.href;
 try{
  const url=new URL('./index.html',location.href);
  const result=installWidget(storage,{url:url.href,origin:location.origin,version});
  status.dataset.state='verified';status.textContent='Painel CAM · Perfil GRBL ativado.';
  detail.textContent='Seus widgets e a conexão foram preservados. Voltando ao CNCjs…';
  schedule(()=>location.replace(destination.href),1000);
  return result;
 }catch(error){
  status.dataset.state='error';status.textContent=error.message||'Não foi possível ativar o painel.';
  detail.textContent='Nenhum comando foi enviado à controladora. Volte ao CNCjs para conferir seu espaço de trabalho.';
  return {status:'failed'};
 }
}

if(typeof window!=='undefined'&&typeof document!=='undefined'){
 if(window.self!==window.top){
  const status=document.getElementById('installStatus');status.dataset.state='error';status.textContent='Abra este link diretamente na mesma janela em que usa o CNCjs.';
 }else{
  try{activateInstallPage({document,storage:window.localStorage,location:window.location});}
  catch{const status=document.getElementById('installStatus');status.dataset.state='error';status.textContent='O navegador bloqueou o acesso ao espaço de trabalho. Abra no mesmo navegador do CNCjs.';}
 }
}
