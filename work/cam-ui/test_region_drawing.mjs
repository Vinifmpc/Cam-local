// Exercise the real pointer/keyboard handlers without a GPU or a browser.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as shapes from './static/region_shapes.js';
import {addRoughingRegion} from './static/form_state.js';
const elements=new Map(),listeners={},keys={};
class Element{
 constructor(){this.value='';this.checked=true;this.hidden=false;this.classList={add(){},remove(){},toggle(){}};}
 replaceChildren(){}setAttribute(){}focus(){}showModal(){this.open=true;}close(){this.open=false;}
}
const $=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let captured=null;
const canvas={addEventListener:(name,fn)=>listeners[name]=fn,
 getBoundingClientRect:()=>({height:100}),setPointerCapture:id=>captured=id,
 hasPointerCapture:id=>captured===id,releasePointerCapture:()=>captured=null};
class Geometry{setFromPoints(){return this;}dispose(){}}
class Material{dispose(){}}
class Line{constructor(geometry,material){this.geometry=geometry;this.material=material;}}
const context={...shapes,$,document:{createElement:()=>new Element(),body:{classList:{add(){},remove(){}}},addEventListener:(name,fn)=>keys[name]=fn},
 renderer:{domElement:canvas},THREE:{BufferGeometry:Geometry,Vector3:class{},LineBasicMaterial:Material,LineLoop:Line,Line},
 scene:{add(){},remove(){}},camera:{top:50,bottom:-50,zoom:1},controls:{enabled:true},
 worldPoint:e=>({x:e.clientX,y:e.clientY}),stop(){},view(){},cancelOriginPick(){},data:{},drawMode:null,drawShape:null,
 dragStart:null,preview:null,draftPoints:[],drawingPointer:null,pendingRegionShape:'rectangle',windows:null,
 settings:{boundaries_mm:null,exclusions_mm:[]},addRoughingRegion,bounds:()=>({minimum:[0,0,-1],maximum:[20,20,0]}),
 operationList:{select(){}},regionPicker:null,createRegionPicker(container,{onChoose}){
  let kind=null;return {show(next){kind=kind===next?null:next;return this.state();},close(){kind=null;},state(){return {open:kind!==null,kind};},choose(shape){const selected=kind;kind=null;onChoose(shape,selected);},setDisabled(){}};
 },changes:0,regionsChanged(){context.changes++;},toast(message){context.lastError=message;},number:id=>Number($(id).value)};
$('stockTop').value='0';
const code=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
vm.createContext(context);vm.runInContext(code.slice(code.indexOf('const drawHelpText='),code.indexOf("$('isoView').onclick")),context);
const event=(x,y)=>({clientX:x,clientY:y,button:0,pointerId:1,preventDefault(){}});
const begin=(shape,kind='keepout')=>{
 $(kind==='keepout'?'drawKeepout':'drawBoundary').onclick();
 assert.equal(context.regionPicker.state().open,true);assert.equal(context.drawMode,null);
 context.regionPicker.choose(shape);assert.equal(context.drawShape,shape);assert.equal(context.drawMode,kind);
};
begin('freehand');listeners.pointerdown(event(0,0));
for(const p of [[5,0],[10,0],[10,5],[10,10],[5,10],[0,10],[0,5]])listeners.pointermove(event(...p));
listeners.pointerup(event(0,0));
assert.equal($('regionDialog').open,true);assert.equal(context.pendingRegionShape,'freehand');
assert.equal(context.controls.enabled,true);assert.equal(captured,null);assert.equal(context.changes,0);
$('applyRegion').onclick();
assert.equal(context.changes,1);assert.equal(context.settings.exclusions_mm[0].length,4);
assert.equal($('regionDialog').open,false);

begin('polygon','boundary');
for(const p of [[0,0],[12,0],[12,12],[0,12]])listeners.pointerdown(event(...p));
keys.keydown({key:'Backspace',preventDefault(){}});assert.equal(context.draftPoints.length,3);
listeners.pointerdown(event(0,12));keys.keydown({key:'Enter',preventDefault(){}});
assert.equal(context.pendingRegionShape,'polygon');assert.equal($('regionDialog').open,true);
$('applyRegion').onclick();assert.equal(context.settings.boundaries_mm[0].length,4);

begin('circle');listeners.pointerdown(event(5,5));listeners.pointerup(event(15,5));
assert.equal($('regionRadiusX').value,'10.000');assert.equal($('regionRadiusYLabel').hidden,true);
$('applyRegion').onclick();assert.ok(context.settings.exclusions_mm[1].length>=32);
begin('ellipse');listeners.pointerdown(event(0,0));listeners.pointerup(event(20,10));
assert.equal($('regionRadiusX').value,'10.000');assert.equal($('regionRadiusY').value,'5.000');
$('applyRegion').onclick();assert.ok(context.settings.exclusions_mm[2].length>=32);

begin('rectangle');listeners.pointerdown(event(0,0));listeners.pointercancel(event(10,10));
assert.equal(context.drawMode,null);assert.equal(context.controls.enabled,true);assert.equal(captured,null);
begin('polygon');listeners.pointerdown(event(0,0));$('cutoutTab').onclick();
assert.equal(context.drawMode,null);assert.equal($('roughPanel').hidden,true);assert.equal($('cutoutPanel').hidden,false);
$('roughTab').onclick();assert.equal($('roughPanel').hidden,false);
begin('polygon');listeners.pointerdown(event(0,0));$('drillTab').onclick();
assert.equal(context.drawMode,null);assert.equal($('drillPanel').hidden,false);assert.equal($('roughPanel').hidden,true);assert.equal($('cutoutPanel').hidden,true);
$('drillTab').onkeydown({key:'ArrowRight',preventDefault(){}});assert.equal($('cutoutPanel').hidden,false);
$('cutoutTab').onkeydown({key:'ArrowRight',preventDefault(){}});assert.equal($('roughPanel').hidden,false);
$('roughTab').onkeydown({key:'ArrowLeft',preventDefault(){}});assert.equal($('cutoutPanel').hidden,false);
$('roughTab').onclick();
begin('polygon');for(const p of [[0,0],[20,20],[0,20],[20,0]])listeners.pointerdown(event(...p));
keys.keydown({key:'Enter',preventDefault(){}});assert.match(context.lastError,/cruza/);
assert.equal(context.drawMode,'keepout');keys.keydown({key:'Escape',preventDefault(){}});
assert.equal(context.drawMode,null);
console.log('Actual drawing handlers: closed freehand, polygon undo/Enter, circle/ellipse apply, pointer cancellation and Rough/Cutout tab isolation passed.');
