// Exercise the actual application's progress lifecycle with controllable time.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {timeLabel} from './static/playback.js';

const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const functions=source.slice(source.indexOf('function setCalculationJob('),source.indexOf('function stop()'));
assert.ok(functions.length>500,'Application progress functions were not found');
const nodes=new Map();
function element(id){
 if(!nodes.has(id))nodes.set(id,{hidden:true,dataset:{},attributes:{},value:0,textContent:'',
  setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];}});
 return nodes.get(id);
}
let clock=1000,serial=0;const timers=new Map(),timeouts=[],apiCalls=[],messages=[];
let apiHandler=async()=>({});
const context=vm.createContext({$:element,timeLabel,performance:{now:()=>clock},
 setInterval(fn){timers.set(++serial,fn);return serial;},clearInterval(id){timers.delete(id);},
 setTimeout(fn){timeouts.push(fn);return ++serial;},api(path,payload){apiCalls.push({path,payload});return apiHandler(path,payload);},
 toast(message,error=false){messages.push({message,error});}});
vm.runInContext('let calcProgressTimer=null,calcProgressStarted=0,calcProgressValue=null,activeCalculationJob=null,cancellationRequested=false,busy=false;'+functions,context);
const call=(name,...args)=>context[name](...args);

call('startCalculationProgress');
assert.equal(element('calcProgress').hidden,false);
assert.equal(element('calcProgressPercent').textContent,'…');
assert.equal(element('cancelCalculation').hidden,false);
assert.equal(element('cancelCalculation').disabled,true,'Do not offer cancellation before the server has returned a job');
clock+=3200;for(const tick of timers.values())tick();
assert.equal(element('calcProgressElapsed').textContent,'Tempo decorrido: 00:03');
call('showCalculationProgress',{status:'running',progress:.33,phase:'Camada 3/10',elapsed_s:3.2});
assert.equal(element('calcProgressBar').value,33);
call('showCalculationProgress',{status:'running',progress:.2});
assert.equal(element('calcProgressBar').value,33,'An older phase must not move the bar backward');
call('showCalculationProgress',{status:'failed',phase:'STL inválido'});
assert.equal(element('calcProgress').dataset.state,'failed');
assert.equal(element('calcProgressBar').value,33,'Failure must not imply 100% completion');
assert.equal(timers.size,0,'Failure must stop the elapsed clock');

call('startCalculationProgress');
assert.equal(element('calcProgressPercent').textContent,'…','A new job must reset the old percentage');
call('showCalculationProgress',{status:'running',progress:1});
assert.equal(element('calcProgressBar').value,99,'Only a complete job can reach 100%');
call('showCalculationProgress',{status:'complete',progress:1,elapsed_s:12.8});
assert.equal(element('calcProgressBar').value,100);
assert.equal(element('calcProgress').dataset.state,'complete');
assert.equal(element('calcProgressElapsed').textContent,'Tempo decorrido: 00:12');
assert.equal(timers.size,0);

call('startCalculationProgress');
call('showCalculationProgress',{status:'running',progress:.6},true);
assert.equal(element('calcProgress').dataset.state,'stale');
assert.match(element('calcProgressLabel').textContent,/configuração anterior/);
call('showCalculationProgress',{status:'complete',progress:1},true);
assert.equal(element('calcProgress').dataset.state,'stale');
assert.match(element('calcProgressLabel').textContent,/anterior concluído/);
call('clearCalculationProgress');
assert.equal(element('calcProgress').hidden,true);
assert.equal(timers.size,0);

call('startCalculationProgress');vm.runInContext('busy=true',context);
await call('cancelCalculation');
assert.equal(apiCalls.length,0,'A job that is still being submitted has no cancellation target');
call('setCalculationJob','cancelled-job');
assert.equal(element('cancelCalculation').disabled,false);
let resolveCancel;
apiHandler=()=>new Promise(resolve=>{resolveCancel=resolve;});
const cancel=call('cancelCalculation');
assert.equal(element('cancelCalculation').disabled,true);
assert.equal(element('cancelCalculation').textContent,'Cancelando…');
await call('cancelCalculation');
assert.equal(apiCalls.length,1,'Repeated cancellation must not submit duplicate requests');
assert.equal(apiCalls[0].path,'/api/cancel');
assert.equal(apiCalls[0].payload.job,'cancelled-job');
call('showCalculationProgress',{status:'running',progress:.34});
call('showCalculationProgress',{status:'cancelled',progress:.34,elapsed_s:5});
resolveCancel({status:'cancelled'});await cancel;
assert.equal(element('calcProgress').dataset.state,'cancelled');
assert.equal(element('calcProgressBar').value,34,'Cancellation must not imply a complete calculation');
assert.equal(element('calcProgressLabel').textContent,'Cálculo cancelado');
assert.equal(element('cancelCalculation').hidden,true);
assert.equal(timers.size,0);
assert.equal(vm.runInContext('activeCalculationJob',context),null);

call('startCalculationProgress');call('setCalculationJob','cancel-retry');
apiHandler=async()=>{throw Error('Serviço indisponível');};
await call('cancelCalculation');
assert.equal(element('cancelCalculation').disabled,false,'A failed cancellation request must allow retry');
assert.equal(element('cancelCalculation').textContent,'Cancelar cálculo');
assert.match(messages.at(-1).message,/Serviço indisponível/);
let rejectOldCancel;
apiHandler=()=>new Promise((resolve,reject)=>{rejectOldCancel=reject;});
const delayedCancel=call('cancelCalculation');
call('startCalculationProgress');call('setCalculationJob','new-job');
rejectOldCancel(Error('Resposta antiga'));await delayedCancel;
assert.equal(vm.runInContext('activeCalculationJob',context),'new-job','An old response must not target a new job');
assert.equal(element('cancelCalculation').disabled,false);
call('showCalculationProgress',{status:'failed',phase:'Falha do motor'});
assert.equal(vm.runInContext('activeCalculationJob',context),null);
assert.equal(element('cancelCalculation').hidden,true);

// Exercise the actual request/poll lifecycle, including a native worker that is
// alive without a new percentage, cancellation, previous motion and retry.
const handler=source.slice(source.indexOf('async function startCalculation('),source.indexOf("$('exportNC').onclick=async()=>{"));
let scheduled=0,replaced=0;
Object.assign(context,{request:()=>({operations:{},tool:{}}),validateTimingFeeds(){},stop(){},cancelSolid(){},
 clearCutoutRecovery(){},cancelDraw(){},presentCalculationError(message){context.toast(message,true);},
 scheduleSolid(){scheduled++;},setMotion(){replaced++;},jobStatusText:state=>state.phase,
 calculationSummary:()=> 'Percurso calculado e salvo localmente.'});
vm.runInContext("let revision=0,motion={moves:[['cut']]},computedProject='previous',lastCalculationJob=null;busy=false;"+handler,context);
apiHandler=async path=>path==='/api/calculate'?{job:'lifecycle-job'}:path==='/api/cancel'?{status:'cancelling'}:{status:'running',phase:'Calculando passada 6',progress:.34,heartbeat_s:20,worker_alive:true};
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
await element('calculate').onclick();await flush();
assert.equal(element('cancelCalculation').disabled,false);
assert.match(element('calcStatus').textContent,/Processando esta passada/);
assert.equal(element('calcProgressBar').value,34,'A worker heartbeat is not new percentage progress');
assert.equal(vm.runInContext('busy',context),true);
await assert.rejects(()=>context.startCalculation(true),/Já há um cálculo/);
assert.equal(vm.runInContext('lastCalculationJob',context),'lifecycle-job');
await call('cancelCalculation');
apiHandler=async()=>({status:'cancelled',progress:.34,elapsed_s:22});
timeouts.shift()();await flush();
assert.equal(vm.runInContext('busy',context),false);
assert.equal(element('calculate').disabled,false);
assert.equal(element('calculate').attributes['aria-busy'],'false');
assert.equal(element('calcProgress').dataset.state,'cancelled');
assert.match(element('calcStatus').textContent,/percurso anterior continua disponível/);
assert.equal(replaced,0,'Cancellation must preserve the previous valid motion');
assert.equal(scheduled,1,'The previous simulation can resume after cancellation');

apiHandler=async path=>path==='/api/calculate'?{job:'failed-job'}:{status:'failed',error:'Erro no worker',progress:.34};
await element('calculate').onclick();await flush();
assert.equal(vm.runInContext('busy',context),false);
assert.equal(element('calcProgress').dataset.state,'failed');
assert.equal(vm.runInContext('activeCalculationJob',context),null);
assert.match(element('calcStatus').textContent,/Erro no worker/);
apiHandler=async path=>path==='/api/calculate'?{job:'retry-job'}:{status:'complete',motion:{moves:[['cut']]},progress:1};
await element('calculate').onclick();await flush();
assert.equal(element('calcProgressBar').value,100);
assert.equal(replaced,1,'A successful retry replaces the previous motion');
assert.equal(vm.runInContext('activeCalculationJob',context),null);
assert.equal(element('cancelCalculation').hidden,true);
assert.equal(timers.size,0);
console.log('Calculation progress: elapsed time, monotonic updates, heartbeat, failure, retry, completion, stale configuration, cancellation lifecycle and previous motion preservation passed.');
