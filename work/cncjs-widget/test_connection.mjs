import assert from 'node:assert/strict';
import {CncjsProfileController,validateProfile} from './connection.js';
const target={machine_max_rate_mm_min:[1500,1500,1500],machine_acceleration_mm_s2:[80,80,100]};
const copy=value=>JSON.parse(JSON.stringify(value));
class MockSocket{
 constructor(board){this.board=board;this.callbacks=new Map();this.connected=false;this.calls=[];board.sockets.push(this);}
 on(event,fn){if(!this.callbacks.has(event))this.callbacks.set(event,new Set());this.callbacks.get(event).add(fn);}
 off(event,fn){this.callbacks.get(event)?.delete(fn);}
 server(event,...args){for(const fn of this.callbacks.get(event)||[])fn(...args);}
 connect(){this.connected=true;this.server('connect');}
 disconnect(){this.connected=false;this.server('disconnect');}
 emit(event,...args){
  this.calls.push([event,...args]);const board=this.board;
  if(event==='list'){this.server('serialport:list',[{port:'COM7',inuse:board.inuse}]);return;}
  if(event==='open'){
   board.attached++;this.server('serialport:open',{port:'COM7',controllerType:'Grbl'});
   this.server('workflow:state',board.workflow);this.server('feeder:status',board.feeder);this.server('sender:status',board.sender);
   this.server('controller:state','Grbl',{status:{activeState:board.state}});args[2](null);return;
  }
  if(event==='write'){
   const [port,data,context]=args,command=data.trim();board.commands.push(command);
   if(board.beforeEcho)this.server('serialport:read','ok');
   this.server('serialport:write',data,context);
   if(command==='?'){this.server('serialport:read',`<${board.state}|MPos:0,0,0|FS:0,0>`);return;}
   if(command==='$$'){
    Object.entries(board.settings).forEach(([key,value])=>this.server('serialport:read',`${key}=${value.toFixed(3)} (value)`));
    this.server('serialport:read','ok');return;
   }
   const [key,raw]=command.split('=');
   if(board.failKey===key){this.server('serialport:read','error:3');return;}
   if(board.ignoreKey!==key)board.settings[key]=Number(raw);
   if(board.foreignAfter===key)this.server('serialport:write','G0X1\n',{source:'client'});
   if(board.runAfter===key){board.state='Run';this.server('controller:state','Grbl',{status:{activeState:'Run'}});}
   if(board.resetAfter===key)this.server('serialport:read',"Grbl 1.1h ['$' for help]");
   if(board.timeoutKey!==key)this.server('serialport:read','ok');
  }
 }
}
function fixture(options={}){
 const board={inuse:true,state:'Idle',workflow:'idle',feeder:{hold:false,pending:false,queue:0},sender:{hold:false,sent:0,received:0},settings:{'$3':6,'$13':0,'$100':400,'$101':400,'$102':400,'$110':1500,'$111':1500,'$112':1500,'$120':10,'$121':10,'$122':10},commands:[],sockets:[],attached:0};
 const messages=[],events=new Map(),parent={postMessage:(...message)=>messages.push(message)},win={parent,location:{origin:'http://cnc.local:8000'},addEventListener:(event,fn)=>events.set(event,fn),removeEventListener:(event)=>events.delete(event)};
 const controller=new CncjsProfileController({io:()=>new MockSocket(board),host:'http://cnc.local:8000',token:'private-test-token',parentOrigin:'http://cnc.local:8000',window:win,quietMs:0,timeoutMs:15,sleep:async()=>{},...options});
 controller.start();return {board,controller,messages,events,win};
}
async function attached(options){const f=fixture(options);await f.controller.selectPort('COM7','Grbl');return f;}
let passed=0;
async function test(label,fn){await fn();passed++;console.log(label);}
await test('shares an already-open controller and never emits serial close',async()=>{
 const f=await attached();assert.equal(f.controller.state().connected,true);assert.equal(f.board.attached,1);assert.equal(f.board.commands.length,0);
 assert.equal(f.messages[0][0].action.type,'connect');assert.equal(f.messages[0][1],'http://cnc.local:8000');f.controller.dispose();
 assert.equal(f.board.sockets[0].calls.some(call=>call[0]==='close'),false);
});
await test('closed ports are rejected before open attachment',async()=>{
 const f=fixture();f.board.inuse=false;await assert.rejects(()=>f.controller.selectPort('COM7','Grbl'),/não está aberta/);
 assert.equal(f.board.attached,0);f.controller.dispose();
});
await test('parent messages require source, origin and authentication token',async()=>{
 const f=fixture(),event={source:f.win.parent,origin:'http://cnc.local:8000',data:{token:'private-test-token',version:'1.10.0',action:{type:'change',payload:{port:'COM7',controller:'Grbl'}}}};
 const handler=f.events.get('message');handler({...event,origin:'https://example.org'});handler({...event,source:{}});handler({...event,data:{...event.data,token:'bad'}});
 await Promise.resolve();assert.equal(f.board.attached,0);handler(event);await new Promise(resolve=>setTimeout(resolve,1));assert.equal(f.board.attached,1);f.controller.dispose();
});
await test('fresh reads retain full settings but do not write assignments',async()=>{
 const f=await attached(),report=await f.controller.read();assert.equal(report.status,'read');assert.deepEqual(report.values.machine_acceleration_mm_s2,[10,10,10]);assert.equal(report.settings['$3'],6);assert.deepEqual(f.board.commands,['?','$$','?']);assert.equal(f.controller.state().can_apply,true);f.controller.dispose();
});
await test('profile applies only changed six whitelisted settings and verifies readback',async()=>{
 const f=await attached(),before=copy(f.board.settings);await f.controller.read();const report=await f.controller.apply(target);
 assert.equal(report.status,'verified');assert.equal(report.verified,true);assert.deepEqual(report.written_settings,['$120','$121','$122']);assert.deepEqual(report.values,target);assert.deepEqual(report.backup.before,before);
 assert.deepEqual(f.board.commands.filter(command=>command.includes('=')),['$120=80','$121=80','$122=100']);assert.equal(f.board.settings['$3'],6);assert.equal(f.controller.state().can_apply,false);await assert.rejects(()=>f.controller.apply(target),/Leia os valores/);f.controller.dispose();
});
await test('read refuses active workflow and sender or feeder queues',async()=>{
 for(const kind of ['workflow','sender','feeder']){
  const f=await attached();if(kind==='workflow')f.board.sockets[0].server('workflow:state','running');
  if(kind==='sender')f.board.sockets[0].server('sender:status',{hold:false,sent:2,received:1});
  if(kind==='feeder')f.board.sockets[0].server('feeder:status',{hold:false,pending:true,queue:1});
  await assert.rejects(()=>f.controller.read(),/Idle/);assert.equal(f.board.commands.length,0);f.controller.dispose();
 }
});
await test('cached Idle cannot authorize writes when fresh GRBL status is Run',async()=>{
 const f=await attached();await f.controller.read();f.board.state='Run';const report=await f.controller.apply(target);assert.equal(report.status,'failed');assert.equal(f.board.commands.some(c=>c.includes('=')),false);f.controller.dispose();
});
await test('any changed setting since snapshot invalidates the write',async()=>{
 const f=await attached();await f.controller.read();f.board.settings['$13']=1;const report=await f.controller.apply(target);assert.equal(report.status,'failed');assert.match(report.error,/mudaram/);assert.equal(f.board.commands.some(c=>c.includes('=')),false);f.controller.dispose();
});
await test('other client commands invalidate previous read and abort an in-progress write',async()=>{
 const f=await attached();await f.controller.read();f.board.sockets[0].server('serialport:write','G0X1\n',{source:'client'});await assert.rejects(()=>f.controller.apply(target),/Leia os valores/);
 await f.controller.read();f.board.foreignAfter='$120';const report=await f.controller.apply(target);assert.equal(report.status,'partial');assert.equal(report.verified,false);assert.equal(f.board.settings['$120'],80);assert.equal(f.board.commands.some(c=>c.startsWith('$121=')),false);f.controller.dispose();
});
await test('missing acknowledgement is partial and never automatically retried',async()=>{
 const f=await attached();await f.controller.read();f.board.timeoutKey='$120';const report=await f.controller.apply(target);assert.equal(report.status,'partial');assert.equal(report.written_settings.length,0);assert.equal(f.board.commands.filter(c=>c==='$120=80').length,1);assert.equal(f.controller.state().values,null);f.controller.dispose();
});
await test('acknowledgements before our write echo cannot authorize success',async()=>{
 const f=await attached();await f.controller.read();f.board.beforeEcho=true;f.board.failKey='$120';const report=await f.controller.apply(target);assert.equal(report.status,'partial');assert.equal(report.written_settings.length,0);assert.match(report.error,/error:3/);f.controller.dispose();
});
await test('failed readback never reports success and preserves actual values',async()=>{
 const f=await attached();await f.controller.read();f.board.ignoreKey='$121';const report=await f.controller.apply(target);assert.equal(report.status,'partial');assert.equal(report.verified,false);assert.deepEqual(report.values.machine_acceleration_mm_s2,[80,10,100]);f.controller.dispose();
});
await test('reset and Run during a transfer stop all later assignments',async()=>{
 for(const key of ['resetAfter','runAfter']){const f=await attached();await f.controller.read();f.board[key]='$120';const report=await f.controller.apply(target);assert.equal(report.status,'partial');assert.equal(f.board.commands.some(c=>c.startsWith('$121=')),false);f.controller.dispose();}
});
await test('unchanged profile performs no EEPROM writes',async()=>{
 const f=await attached(),read=await f.controller.read(),report=await f.controller.apply(read.values);assert.equal(report.status,'verified');assert.equal(report.written_settings.length,0);assert.equal(f.board.commands.some(c=>c.includes('=')),false);f.controller.dispose();
});
await test('expired read and invalid profiles cannot write to the controller',async()=>{
 let now=0;const f=await attached({now:()=>now});await f.controller.read();now=300001;await assert.rejects(()=>f.controller.apply(target),/Leia os valores/);
 for(const invalid of [0,-1,Infinity,NaN,true,.00001])assert.throws(()=>validateProfile({...target,machine_acceleration_mm_s2:[invalid,1,1]}));
 assert.throws(()=>validateProfile({...target,machine_steps_per_mm:[1,1,1]}));assert.equal(f.board.commands.some(c=>c.includes('=')),false);f.controller.dispose();
});
await test('switching CNCjs ports detaches only the widget and removes stale readback',async()=>{
 const f=await attached();await f.controller.read();assert.equal(f.controller.state().values.machine_acceleration_mm_s2[0],10);
 await f.controller.selectPort('COM8','Grbl');assert.equal(f.controller.state().values,null);assert.equal(f.controller.state().can_apply,false);
 assert.equal(f.board.sockets[0].connected,false);assert.equal(f.board.sockets[0].calls.some(call=>call[0]==='close'),false);assert.equal(f.board.commands.some(c=>c.includes('=')),false);f.controller.dispose();
});
await test('backup storage failure prevents every assignment and returns a clear error',async()=>{
 const f=await attached({saveBackup:()=>{throw Error('Backup storage full');}});
 await f.controller.read();const report=await f.controller.apply(target);
 assert.equal(report.status,'failed');assert.match(report.error,/Backup storage full/);
 assert.equal(f.board.commands.some(command=>command.includes('=')),false);
 assert.equal(f.controller.state().busy,false);f.controller.dispose();
});
console.log(JSON.stringify({status:'passed',tests:passed,physical_controller_accessed:false}));
