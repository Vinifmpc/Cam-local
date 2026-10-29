// Original CAM Local code. CNCjs keeps ownership of the serial connection.
const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));
const KEYS={machine_max_rate_mm_min:['$110','$111','$112'],machine_acceleration_mm_s2:['$120','$121','$122']};
const IDS=Object.values(KEYS).flat();
const settingPattern=/^(\$\d+)\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*(?:\(.*\))?$/i;
const uid=()=>globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
const valuesOf=settings=>Object.fromEntries(Object.entries(KEYS).map(([key,ids])=>[key,ids.map(id=>settings[id])]));
const same=(left,right)=>Object.keys(left).length===Object.keys(right).length&&Object.keys(left).every(k=>k in right&&Math.abs(left[k]-right[k])<.00051);
export function validateProfile(profile){
 if(!profile||typeof profile!=='object'||Object.keys(profile).length!==2||Object.keys(profile).some(k=>!KEYS[k]))throw Error('Informe somente máximos e acelerações XYZ.');
 const settings={};
 for(const [key,ids]of Object.entries(KEYS)){
  if(!Array.isArray(profile[key])||profile[key].length!==3)throw Error('Informe os três eixos do perfil.');
  profile[key].forEach((value,i)=>{if(typeof value!=='number'||!Number.isFinite(value)||value<.001||value>1000000)throw Error('Use valores positivos entre 0,001 e 1000000.');settings[ids[i]]=Number(value.toFixed(3));});
 }
 return settings;
}

export class CncjsProfileController{
 constructor({io,host,token,window:win=globalThis.window,parentOrigin,timeoutMs=6000,quietMs=300,now=()=>Date.now(),sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),saveBackup=()=>{}}={}){
  if(typeof io!=='function'||!token||typeof token!=='string')throw Error('Abra este widget pelo CNCjs autenticado.');
  const address=new URL(host||parentOrigin||win?.location?.origin);
  if(!['http:','https:'].includes(address.protocol)||address.username||address.password)throw Error('Endereço CNCjs inválido.');
  this.io=io;this.host=address.origin;this.token=token;this.window=win;this.parentOrigin=new URL(parentOrigin||address.origin).origin;
  if(this.host!==this.parentOrigin)throw Error('O servidor deve corresponder ao CNCjs que contém o widget.');
  this.timeoutMs=timeoutMs;this.quietMs=quietMs;this.now=now;this.sleep=sleep;this.saveBackup=saveBackup;this.listeners=new Set();this.handlers=[];
  this.socket=null;this.started=false;this.disposed=false;this.connected=false;this.port='';this.controllerType='';this.machineState='';this.workflow=null;this.feeder=null;this.sender=null;
  this.busy=false;this.phase='waiting';this.message='Aguardando a conexão já aberta no CNCjs.';this.current=null;this.lastReport=null;this.snapshot=null;this.pending=null;this.attachWaiter=null;
  this.epoch=0;this.operationEpoch=null;this.lastForeignWrite=0;this.selected=null;this.attaching=false;this.opened=false;
  this.messageHandler=event=>this._parentMessage(event);
 }
 state(){
  return {connected:this.connected,port:this.port,machine_state:this.machineState||'—',workflow:this.workflow,busy:this.busy,phase:this.phase,message:this.message,
   values:clone(this.current),last_report:clone(this.lastReport),can_read:!this.busy&&this.connected&&this._queuesIdle(),
   can_apply:!this.busy&&this.connected&&this._queuesIdle()&&!!this.snapshot&&this.snapshot.port===this.port&&this.snapshot.epoch===this.epoch&&this.now()<this.snapshot.expires};
 }
 subscribe(callback){this.listeners.add(callback);callback(this.state());return()=>this.listeners.delete(callback);}
 _render(){for(const callback of this.listeners)callback(this.state());}
 _on(name,callback){this.socket.on(name,callback);this.handlers.push([name,callback]);}
 start(){
  if(this.started)return this;this.started=true;this.window?.addEventListener('message',this.messageHandler);this._connectSocket();return this;
 }
 _connectSocket(){
  if(this.disposed)return;
  this.socket=this.io(this.host,{query:{token:this.token},reconnection:false,autoConnect:false});
  this._on('connect',()=>{this.message='CNCjs conectado. Aguardando a porta selecionada.';this._render();this.window?.parent?.postMessage({token:this.token,action:{type:'connect'}},this.parentOrigin);});
  this._on('connect_error',()=>this._lost('Não foi possível autenticar no CNCjs. Recarregue o widget.'));
  this._on('disconnect',()=>this._lost('O widget perdeu a conexão com o CNCjs. Recarregue-o para continuar.'));
  this._on('serialport:list',ports=>{if(this.attachWaiter){const waiter=this.attachWaiter;this.attachWaiter=null;clearTimeout(waiter.timer);waiter.resolve(ports);}});
  this._on('serialport:open',options=>{if(options?.port===this.port&&options?.controllerType==='Grbl'){this.opened=true;this.controllerType='Grbl';}});
  this._on('serialport:close',options=>{if(!options?.port||options.port===this.port)this._lost('A porta foi desconectada no CNCjs. Conecte-a novamente por lá.');});
  this._on('workflow:state',state=>{this.workflow=state;if(state!=='idle')this._activity('O CNCjs iniciou ou pausou um trabalho.');this._render();});
  this._on('feeder:status',state=>{this.feeder=clone(state);if(!this._feederIdle())this._activity('Há comandos na fila do CNCjs.');this._render();});
  this._on('sender:status',state=>{this.sender=clone(state);if(!this._senderIdle())this._activity('Há um programa sendo enviado pelo CNCjs.');this._render();});
  this._on('controller:state',(kind,state)=>{if(kind!=='Grbl')return;this.machineState=String(state?.status?.activeState||'');if(this.machineState&&this.machineState!=='Idle')this._activity('A máquina saiu do estado Idle.');this._render();});
  this._on('serialport:write',(data,context)=>this._written(data,context));
  this._on('serialport:read',data=>this._received(data));
  this.socket.connect();
 }
 _removeSocket(){
  const socket=this.socket;if(!socket)return;
  for(const [name,callback]of this.handlers)socket.off?.(name,callback)||socket.removeListener?.(name,callback);
  this.handlers=[];this.socket=null;socket.disconnect();
 }
 _parentMessage(event){
  if(event.source!==this.window?.parent||event.origin!==this.parentOrigin||event.data?.token!==this.token)return;
  const {version,action}=event.data||{};
  if(action?.type!=='change')return;
  if(version){const parts=String(version).split('.').map(Number);if(parts[0]!==1||parts[1]<9||(parts[1]===9&&parts[2]<12)){this._lost('Este widget requer CNCjs 1.9.12 a 1.x.');return;}}
  const {port,controller}=action.payload||{};
  this.selectPort(port,controller).catch(error=>{this.phase='error';this.message=error.message;this._render();});
 }
 async selectPort(port,kind='Grbl'){
  const selected=typeof port==='string'?port:'';
  if(selected===this.port&&kind===this.controllerType&&(this.connected||this.attaching))return;
  if(this.port&&selected!==this.port){this._activity('A porta selecionada no CNCjs mudou.');this.connected=false;this.current=null;this.lastReport=null;this._removeSocket();this.port='';this.controllerType='';this.workflow=null;this.feeder=null;this.sender=null;this.machineState='';this._connectSocket();return;}
  if(!selected||kind!=='Grbl'){this._lost(!selected?'Conecte e selecione a porta no CNCjs.':'Selecione uma controladora GRBL no CNCjs.');return;}
  if(this.attaching)return;
  this.attaching=true;this.port=selected;this.controllerType=kind;this.connected=false;this.opened=false;this.phase='attaching';this.message='Usando a conexão já aberta pelo CNCjs…';this._render();
  try{
   const ports=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.attachWaiter=null;reject(Error('CNCjs não informou as portas abertas.'));},this.timeoutMs);this.attachWaiter={resolve,reject,timer};this.socket.emit('list');});
   if(!Array.isArray(ports)||!ports.some(p=>p.port===selected&&p.inuse===true))throw Error('Esta porta não está aberta no CNCjs. Conecte-a pelo painel do CNCjs.');
   // CNCjs's supported custom-widget API attaches an observer to an already
   // open controller. Never emit close, reset, unlock or a serial baud rate.
   await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('O CNCjs não confirmou o vínculo do widget.')),this.timeoutMs);this.socket.emit('open',selected,{controllerType:'Grbl'},error=>{clearTimeout(timer);if(error)reject(Error('Não foi possível usar a conexão aberta no CNCjs.'));else resolve();});});
   if(!this.opened)throw Error('A porta aberta não confirmou uma controladora GRBL.');
   this.connected=true;this.phase='connected';this.message='Conexão compartilhada com o CNCjs. Leia o GRBL antes de gravar.';
  }catch(error){this.connected=false;this.phase='error';this.message=error.message;throw error;}
  finally{this.attaching=false;this._render();}
 }
 _feederIdle(){return !!this.feeder&&!this.feeder.hold&&!this.feeder.pending&&Number(this.feeder.queue)===0;}
 _senderIdle(){return !!this.sender&&!this.sender.hold&&Number.isFinite(this.sender.sent)&&Number.isFinite(this.sender.received)&&this.sender.sent<=this.sender.received;}
 _queuesIdle(){return this.workflow==='idle'&&this._feederIdle()&&this._senderIdle();}
 _safe(){if(!this.connected||!this.socket?.connected)throw Error('O CNCjs não está conectado.');if(!this._queuesIdle())throw Error('Aguarde o CNCjs ficar Idle, sem programa ou comandos na fila.');if(this.operationEpoch!==null&&this.epoch!==this.operationEpoch)throw Error('Outro comando foi enviado pelo CNCjs. Leia novamente antes de continuar.');}
 _activity(message){this.epoch++;this.snapshot=null;this.lastForeignWrite=this.now();if(this.pending)this._settle(Error(message));}
 _lost(message){this.connected=false;this.snapshot=null;this.current=null;this.epoch++;this.phase='error';this.message=message;if(this.pending)this._settle(Error(message));if(this.attachWaiter){clearTimeout(this.attachWaiter.timer);this.attachWaiter.reject(Error(message));this.attachWaiter=null;}this._render();}
 _written(data,context={}){
  const text=String(data).trim();
  if(this.pending&&context?.cam_profile_request===this.pending.id&&text===this.pending.command){this.pending.echo=true;return;}
  // Other clients may use realtime status queries. They do not create ACKs.
  if(text==='?')return;
  this._activity('Outro comando foi enviado pelo CNCjs durante a transferência.');this._render();
 }
 _received(data){
  for(const raw of String(data).split(/\r?\n/)){
   const line=raw.trim();if(!line)continue;
   if(line.length>8192){this._lost('Resposta GRBL maior que o permitido.');return;}
   if(/^grbl\s/i.test(line)||/^ALARM:/i.test(line)){this._lost('A controladora reiniciou ou entrou em alarme. Leia novamente pelo CNCjs.');continue;}
   const pending=this.pending;if(!pending||!pending.echo)continue;
   const status=/^<([A-Za-z]+)(?::\d+)?(?:[|,].*)?>$/.exec(line);
   if(status){this.machineState=status[1];if(status[1]!=='Idle'){this._activity('A máquina precisa estar Idle.');this._render();continue;}if(pending.type==='status')this._settle(null,'Idle');continue;}
   if(pending.type==='status')continue;
   if(/^error:/i.test(line)){this._settle(Error('GRBL: '+line));continue;}
   if(line==='ok'){this._settle(null,pending.lines);continue;}
   pending.lines.push(line);if(pending.lines.length>1024)this._settle(Error('Resposta GRBL maior que o permitido.'));
  }
 }
 _settle(error,value){const pending=this.pending;if(!pending)return;this.pending=null;clearTimeout(pending.timer);if(error)pending.reject(error);else pending.resolve(value);}
 _query(command,type='command'){
  this._safe();if(this.pending)throw Error('Já há uma consulta GRBL em andamento.');
  if(command!=='?'&&command!=='$$'&&!/^\$(?:110|111|112|120|121|122)=\d+(?:\.\d+)?$/.test(command))throw Error('Comando fora do perfil permitido.');
  return new Promise((resolve,reject)=>{const id=uid(),timer=setTimeout(()=>this._settle(Error('Sem confirmação do GRBL. Leia os valores novamente; a última escrita pode ter sido aplicada.')),this.timeoutMs);this.pending={id,command,type,echo:false,lines:[],timer,resolve,reject};this.socket.emit('write',this.port,command+(command==='?'?'':'\n'),{cam_profile_request:id});});
 }
 async _idle(){this._safe();const state=await this._query('?','status');this._safe();return state;}
 async _quiet(){
  await this.sleep(this.quietMs);this._safe();
  if(this.now()-this.lastForeignWrite<this.quietMs)throw Error('Aguarde os comandos do CNCjs terminarem antes de ler ou gravar.');
 }
 async _settings(){
  const lines=await this._query('$$'),settings={};
  for(const line of lines){const match=settingPattern.exec(line);if(match){const value=Number(match[2]);if(!Number.isFinite(value))throw Error('Configuração GRBL inválida.');settings[match[1]]=value;}}
  if(IDS.some(key=>!Number.isFinite(settings[key])||settings[key]<=0))throw Error('O GRBL não retornou o perfil XYZ completo.');
  return settings;
 }
 _begin(phase,message){if(this.busy)throw Error('Aguarde a transferência com o CNCjs.');this._safe();this.busy=true;this.phase=phase;this.message=message;this.operationEpoch=this.epoch;this._render();}
 _end(){this.busy=false;this.operationEpoch=null;this._render();}
 async read(){
  this._begin('reading','Lendo os valores reais pelo CNCjs…');this.snapshot=null;this.current=null;this.lastReport=null;
  try{
   await this._quiet();await this._idle();const settings=await this._settings();await this._idle();
   this.snapshot={port:this.port,epoch:this.epoch,settings,expires:this.now()+300000};this.current=valuesOf(settings);this.phase='read';this.message='Valores lidos. Os campos editados foram preservados.';
   const report={status:'read',port:this.port,machine_state:'Idle',settings,values:clone(this.current)};this.lastReport=report;return clone(report);
  }catch(error){this.phase='error';this.message=error.message;throw error;}finally{this._end();}
 }
 async apply(profile){
  const requested=validateProfile(profile),snapshot=this.snapshot;
  if(!snapshot||snapshot.port!==this.port||snapshot.epoch!==this.epoch||this.now()>=snapshot.expires)throw Error('Leia os valores atuais do GRBL antes de gravar.');
  this._begin('writing','Gravando o perfil pela conexão do CNCjs…');this.snapshot=null;
  const report={status:'failed',verified:false,port:this.port,values:null,before:null,after:null,requested,written_settings:[],backup:null};let attempted=false;
  try{
   await this._quiet();await this._idle();const before=await this._settings();report.before=before;
   if(!same(before,snapshot.settings))throw Error('Os valores da controladora mudaram. Leia novamente antes de gravar.');
   report.backup={format:1,created_utc:new Date().toISOString(),port:this.port,before:clone(before),requested:clone(requested)};
   await this.saveBackup(clone(report.backup));
   // Publish the backup to the UI before sending the first setting assignment.
   this.lastReport=clone(report);this._render();
   for(const key of IDS){if(Math.abs(before[key]-requested[key])<.00051)continue;await this._idle();attempted=true;await this._query(key+'='+String(requested[key]));report.written_settings.push(key);}
   await this._idle();const after=await this._settings();report.after=after;report.values=valuesOf(after);
   if(IDS.some(key=>Math.abs(after[key]-requested[key])>.00051))throw Error('A leitura final não corresponde ao perfil solicitado.');
   report.status='verified';report.verified=true;report.message='Valores gravados e confirmados pelo GRBL, sem desconectar o CNCjs.';this.phase='verified';this.current=clone(report.values);this.message=report.message;return clone(report);
  }catch(error){report.status=attempted?'partial':'failed';report.error=error.message;report.message=(attempted?'Gravação não confirmada por completo. ':'')+error.message+' Leia novamente antes de outra gravação.';this.phase=attempted?'partial':'error';this.current=report.values?clone(report.values):null;this.message=report.message;return clone(report);}
  finally{this.lastReport=clone(report);this._end();}
 }
 dispose(){this.disposed=true;this.window?.removeEventListener('message',this.messageHandler);this._lost('Widget encerrado.');this._removeSocket();this.listeners.clear();}
}
export const createCncjsConnection=options=>new CncjsProfileController(options);
