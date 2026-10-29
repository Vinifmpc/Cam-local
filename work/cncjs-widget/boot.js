import {createCncjsConnection} from './connection.js';
import {mountWidget} from './app.js';

export function cncjsContext(location,referrer=''){
 const params=new URLSearchParams(location.search),token=params.get('token');
 if(!token)throw Error('Abra este painel como widget personalizado dentro do CNCjs.');
 const parentOrigin=referrer?new URL(referrer).origin:location.origin;
 const url=new URL(params.get('host')||parentOrigin);
 if(!['http:','https:'].includes(url.protocol)||url.origin!==parentOrigin)throw Error('O servidor do widget precisa ser o mesmo CNCjs que abriu o painel.');
 return {host:url.origin,parentOrigin,token};
}

export function persistProfileBackup(storage,backup){
 const settings=value=>Object.fromEntries(Object.entries(value||{}).filter(([key,number])=>/^\$\d+$/.test(key)&&typeof number==='number'&&Number.isFinite(number)));
 const record={format:1,created_utc:backup.created_utc,port:backup.port,before:settings(backup.before),requested:settings(backup.requested)};
 try{
  const previous=JSON.parse(storage.getItem('cam-local.grbl-profile-backups')||'[]');
  if(!Array.isArray(previous))throw Error();
  storage.setItem('cam-local.grbl-profile-backups',JSON.stringify([...previous,record].slice(-10)));
 }catch{throw Error('Não foi possível salvar o backup no navegador; nenhum novo valor será gravado.');}
}

async function start(){
 const context=cncjsContext(window.location,document.referrer);
 if(window.parent===window)throw Error('Adicione este endereço como widget personalizado no CNCjs.');
 await new Promise((resolve,reject)=>{
  const script=document.createElement('script');
  script.src=context.host+'/socket.io/socket.io.js';script.referrerPolicy='no-referrer';
  script.onload=resolve;script.onerror=()=>reject(Error('Não foi possível carregar a conexão do CNCjs.'));
  document.head.append(script);
 });
 if(typeof window.io!=='function')throw Error('O CNCjs não disponibilizou seu cliente de conexão.');
 // Backup persistence is awaited before the first assignment, rather than
 // relying on a UI observer. Failure leaves the transfer without any writes.
 const controller=createCncjsConnection({...context,io:window.io,window,saveBackup:backup=>persistProfileBackup(localStorage,backup)});
 const widget=mountWidget({document,controller,clipboard:navigator.clipboard});
 const cleanup=()=>{widget.destroy?.();controller.dispose();};
 window.addEventListener('pagehide',cleanup,{once:true});
 controller.start();
 const resize=()=>window.parent.postMessage({token:context.token,action:{type:'resize',payload:{scrollHeight:document.body.scrollHeight,scrollWidth:document.body.scrollWidth}}},context.parentOrigin);
 const observer=new ResizeObserver(resize);observer.observe(document.body);resize();
}
if(typeof window!=='undefined'&&typeof document!=='undefined')start().catch(error=>{
 const status=document.getElementById('status')||document.querySelector('[role="status"]');
 if(status){status.textContent=error.message;status.dataset.state='error';}
});
