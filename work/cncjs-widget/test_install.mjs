import assert from 'node:assert/strict';
import {installWidget,activateInstallPage,WIDGET_ID,BACKUP_KEY} from './install.js';
const origin='http://cnc.test:8000',url=origin+'/cam-perfil/index.html';
const options={origin,url,version:'1.11.5',now:()=>new Date('2026-10-27T12:00:00Z')};
const clone=value=>JSON.parse(JSON.stringify(value));
function storage(initial={}){const values=new Map(Object.entries(initial)),writes=[];return {getItem:key=>values.has(key)?values.get(key):null,setItem(key,value){writes.push(key);values.set(key,String(value));},values,writes};}
const source={version:'1.11.4',extra:'preserved',state:{session:{token:'SECRET-AUTH',name:'fixture-user'},workspace:{container:{default:{widgets:['visualizer']},primary:{show:false,widgets:['connection','console','custom:esp32']},secondary:{show:true,widgets:['axes',WIDGET_ID,'probe']}},machineProfile:{id:'machine-1'}},widgets:{'custom:esp32':{url:'http://esp.test/status?custom=KEEP',title:'ESP32',disabled:false},connection:{port:'COM7',baudrate:115200},axes:{axes:['x','y','z']},[WIDGET_ID]:{disabled:true,minimized:true,title:'Old',url:url+'?token=OLDSECRET',extra:'keep-own-extra'}}}};
const s=storage({cnc:JSON.stringify(source)}),result=installWidget(s,options),after=JSON.parse(s.getItem('cnc'));
assert.equal(result.status,'installed');assert.equal(result.already_installed,false);
assert.deepEqual(after.state.session,source.state.session,'Authentication and session remain untouched');
assert.equal(after.version,'1.11.4','Existing CNCjs version is preserved');
assert.deepEqual(after.state.widgets['custom:esp32'],source.state.widgets['custom:esp32'],'ESP widget configuration stays exact');
assert.deepEqual(after.state.widgets.connection,source.state.widgets.connection,'No serial connection configuration changes');
assert.deepEqual(after.state.workspace.container.primary.widgets,[WIDGET_ID,'connection','console','custom:esp32']);
assert.equal(after.state.workspace.container.primary.show,true,'Activation makes the primary container visible');
assert.deepEqual(after.state.workspace.container.secondary.widgets,['axes','probe']);
assert.deepEqual(after.state.workspace.container.default,source.state.workspace.container.default);
assert.deepEqual(after.state.workspace.machineProfile,source.state.workspace.machineProfile);
assert.deepEqual(after.state.widgets[WIDGET_ID],{disabled:false,minimized:false,title:'CAM · Perfil GRBL',url,extra:'keep-own-extra'});
const backup=s.getItem(BACKUP_KEY),savedBackup=JSON.parse(backup);
assert.equal(backup.includes('SECRET'),false,'Workspace backup never duplicates authentication tokens or query credentials');
assert.equal(backup.includes('ESP32'),false,'Unrelated widget configuration is not duplicated');
assert.deepEqual(savedBackup.workspace.container.primary,{show:false,widgets:['connection','console','custom:esp32']});
assert.equal(savedBackup.widget.url,url);
assert.deepEqual(s.writes,[BACKUP_KEY,'cnc'],'Backup is stored before the new layout');
const encoded=s.getItem('cnc'),repeat=installWidget(s,options);
assert.equal(repeat.already_installed,true);assert.equal(s.getItem(BACKUP_KEY),backup,'Repeated activation preserves first backup');
assert.equal(s.getItem('cnc'),encoded);assert.equal(s.writes.length,2,'Idempotent activation does not rewrite browser storage');

for(const initial of [{}, {state:{session:{token:'STAYS'}}}, {version:'1.11.5',state:{workspace:{container:{primary:{widgets:[]}}}}}]){
 const local=storage({cnc:JSON.stringify(initial)});installWidget(local,options);
 const state=JSON.parse(local.getItem('cnc')).state;
 const expected=initial.state?.workspace?.container?.primary?.widgets===undefined?[WIDGET_ID,'connection','console','grbl','marlin','smoothie','tinyg','webcam']:[WIDGET_ID];
 assert.deepEqual(state.workspace.container.primary.widgets,expected);
 assert.deepEqual(state.session,initial.state?.session);
}
const empty=storage();installWidget(empty,options);assert.equal(JSON.parse(empty.getItem('cnc')).version,'1.11.5');
for(const corrupt of ['','{secret-invalid','null','[]','123',JSON.stringify({state:[]}),JSON.stringify({state:{widgets:[]}}),JSON.stringify({state:{workspace:{container:{primary:{widgets:'console'}}}}}),JSON.stringify({state:{workspace:{container:{secondary:{widgets:[1]}}}}})]){
 const local=storage({cnc:corrupt});assert.throws(()=>installWidget(local,options));assert.equal(local.getItem('cnc'),corrupt);assert.equal(local.writes.length,0,'Malformed configuration is never replaced or backed up');
}
for(const bad of ['https://other.test/cam-perfil/index.html',origin+'/cam-perfil/index.html?token=secret',origin+'/cam-perfil/index.html#hash','http://user:pass@cnc.test:8000/cam-perfil/index.html','javascript:alert(1)']){
 const local=storage();assert.throws(()=>installWidget(local,{...options,url:bad}));assert.equal(local.writes.length,0);
}
const blocked=storage({cnc:JSON.stringify(source)});blocked.setItem=()=>{throw Error('Storage full');};assert.throws(()=>installWidget(blocked,options),/Storage full/);assert.equal(blocked.getItem('cnc'),JSON.stringify(source));

function document(){const elements=new Map(['installStatus','installDetail','returnCncjs'].map(id=>[id,{dataset:{},textContent:'',href:''}]));return {getElementById:id=>elements.get(id),elements};}
const doc=document(),local=storage(),scheduled=[];let redirected;
const activated=activateInstallPage({document:doc,storage:local,location:{href:origin+'/cam-perfil/install.html?ignored=1',origin,replace:value=>{redirected=value;}},schedule:(fn,delay)=>scheduled.push({fn,delay})});
assert.equal(activated.status,'installed');assert.equal(doc.elements.get('installStatus').dataset.state,'verified');
assert.equal(scheduled.length,1);assert.equal(scheduled[0].delay,1000);scheduled[0].fn();assert.equal(redirected,origin+'/');
assert.equal(JSON.parse(local.getItem('cnc')).state.widgets[WIDGET_ID].url,url,'Activation strips install page query from widget URL');
const failureDoc=document();const failed=activateInstallPage({document:failureDoc,storage:storage({cnc:'broken'}),location:{href:origin+'/cam-perfil/install.html',origin,replace(){throw Error('Must not redirect');}},schedule(){throw Error('Must not schedule');}});
assert.equal(failed.status,'failed');assert.equal(failureDoc.elements.get('installStatus').dataset.state,'error');
assert.equal(failureDoc.elements.get('installStatus').textContent.includes('broken'),false,'Errors never expose stored configuration');
console.log('CNCjs widget installer: same-origin activation, auth/ESP/layout preservation, first backup, idempotence, corruption rejection and automatic return passed.');
