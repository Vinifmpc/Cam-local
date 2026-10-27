import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {importedMachiningState} from './static/form_state.js';
import {profilePatch} from './static/machining_presets.js';

const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
assert.equal(new Set(ids).size,ids.length,'Workspace markup must not contain duplicate IDs');
const availability=source.slice(source.indexOf('function updateWorkspaceAvailability()'),source.indexOf('function adopt('));
const startup=source.slice(source.indexOf('async function initializeWorkspace()'),source.indexOf('await initializeWorkspace();'));
const elements=new Map(ids.map(id=>[id,{hidden:false,disabled:false,textContent:''}]));
const requests=[],messages=[],classes=new Set();
const sandbox={data:null,tool:null,tools:[],token:'',busy:false,exportBusy:false,presetStore:{presets:[],last_used:null},presetError:'',identity:[[1,0,0],[0,1,0],[0,0,1]],importedMachiningState,profilePatch,fillFields(){},renderPresets(){},
 $:id=>{assert.ok(elements.has(id),id);return elements.get(id);},
 document:{body:{classList:{toggle:(name,active)=>active?classes.add(name):classes.delete(name)}}},
 api:async path=>{requests.push(path);return {token:'test-session-token',tools:[{id:'flat',name:'Tool'}]};},
 displayToolSelect(){},setMotion(){},updateDepthLegend(){},view(){},toast:message=>messages.push(message)};
const context=vm.createContext(sandbox);vm.runInContext(availability+startup,context);
await vm.runInContext('initializeWorkspace()',context);
assert.deepEqual(requests,['/api/bootstrap'],'Startup must not request a demo or a model');
assert.equal(context.data,null);assert.equal(context.tool.id,'flat');assert.equal(context.token,'test-session-token');
assert.equal(elements.get('emptyScene').hidden,false);assert.equal(elements.get('loadingScene').hidden,true);
for(const id of ['calculate','saveProject','applyPlacement','inspectDrill','resetStock','stockMode'])assert.equal(elements.get(id).disabled,true,id);
assert.ok(classes.has('workspace-empty'));assert.equal(messages.length,0);
context.data={mesh:{}};vm.runInContext('updateWorkspaceAvailability()',context);
assert.equal(elements.get('emptyScene').hidden,true);assert.equal(elements.get('calculate').disabled,false);assert.equal(elements.get('saveProject').disabled,false);
context.data=null;context.token='';context.api=async()=>{throw Error('offline');};
await vm.runInContext('initializeWorkspace()',context);
assert.equal(elements.get('calculate').disabled,true);assert.equal(messages.at(-1),'offline');
assert.doesNotMatch(html,/Exemplo do anel|Carregando exemplo/);
assert.match(html,/Sua próxima peça começa aqui/);
console.log('Empty startup, no demo import, model availability, error state and unique workspace controls passed.');
