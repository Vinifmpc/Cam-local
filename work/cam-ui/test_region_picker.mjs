import assert from 'node:assert/strict';
import {createRegionPicker} from './static/region_picker.js';

// This fixture exercises the real controller and event handlers without a GPU.
class Element{
 constructor(document){this.ownerDocument=document;this.events={};this.dataset={};this.attributes={};this.children=[];this.hidden=false;this.disabled=false;}
 addEventListener(name,handler){(this.events[name]??=[]).push(handler);}
 removeEventListener(name,handler){this.events[name]=this.events[name].filter(item=>item!==handler);}
 emit(name,event={}){for(const handler of this.events[name]??[])handler({target:this,...event});}
 setAttribute(name,value){this.attributes[name]=value;}
 focus(){this.ownerDocument.activeElement=this;}
 contains(node){return this===node||this.children.some(child=>child.contains(node));}
 querySelector(selector){return this.lookup?.[selector]??null;}
 querySelectorAll(){return this.children.filter(child=>child.dataset.regionShape);}
}
const document=new Element();document.activeElement=null;
const container=new Element(document);container.id='regionPicker';
const shapes=['rectangle','circle','ellipse','polygon','freehand'];
const buttons=shapes.map(shape=>{const button=new Element(document);button.dataset.regionShape=shape;return button;});
const title=new Element(document),cancel=new Element(document);
container.children=[...buttons,title,cancel];
container.lookup={'[data-region-picker-title]':title,'[data-region-picker-cancel]':cancel};
const keepIn=new Element(document),keepOut=new Element(document),outside=new Element(document);
const chosen=[],cancellations=[];
const picker=createRegionPicker(container,{onChoose:(shape,kind)=>chosen.push({shape,kind}),onCancel:kind=>cancellations.push(kind)});
const key=(button,value)=>{const event={key:value,prevented:false,preventDefault(){this.prevented=true;}};button.emit('keydown',event);return event;};
assert.equal(container.hidden,true);
assert.deepEqual(picker.state(),{open:false,kind:null,disabled:false});
assert.equal(chosen.length,0);

picker.show('boundary',keepIn);
assert.equal(container.hidden,false);assert.equal(container.dataset.kind,'boundary');
assert.equal(title.textContent,'Keep In · escolha a forma');assert.equal(document.activeElement,buttons[0]);
assert.equal(keepIn.attributes['aria-expanded'],'true');assert.equal(keepIn.attributes['aria-controls'],'regionPicker');
assert.equal(chosen.length,0,'Opening Keep In must not start drawing or mutate regions.');
key(buttons[0],'ArrowRight');assert.equal(document.activeElement,buttons[1]);
key(buttons[1],'ArrowDown');assert.equal(document.activeElement,buttons[2]);
key(buttons[2],'End');assert.equal(document.activeElement,buttons[4]);
key(buttons[4],'ArrowRight');assert.equal(document.activeElement,buttons[0]);
key(buttons[0],'ArrowLeft');assert.equal(document.activeElement,buttons[4]);
key(buttons[4],'Home');assert.equal(document.activeElement,buttons[0]);
key(buttons[0],'ArrowUp');assert.equal(document.activeElement,buttons[4]);

picker.show('keepout',keepOut);
document.emit('click',{target:keepOut});
assert.equal(picker.state().kind,'keepout');assert.equal(title.textContent,'Keep Out · escolha a forma');
assert.equal(keepIn.attributes['aria-expanded'],'false');assert.equal(keepOut.attributes['aria-expanded'],'true');
assert.equal(cancellations.length,0,'Switching region kind is not a cancelled drawing.');
assert.equal(chosen.length,0,'Switching kinds must await an explicit shape.');
buttons[1].emit('click');
assert.deepEqual(chosen,[{shape:'circle',kind:'keepout'}]);
assert.equal(container.hidden,true);assert.equal(keepOut.attributes['aria-expanded'],'false');
assert.equal(cancellations.length,0,'A shape choice is not a cancellation.');
buttons[0].emit('click');assert.equal(chosen.length,1,'Hidden buttons must not start another drawing.');

for(const shape of shapes){
 picker.show('boundary',keepIn);buttons[shapes.indexOf(shape)].emit('click');
 assert.deepEqual(chosen.at(-1),{shape,kind:'boundary'});
}
picker.show('boundary',keepIn);picker.show('boundary',keepIn);
assert.equal(picker.state().open,false);assert.equal(document.activeElement,keepIn);assert.equal(cancellations.at(-1),'boundary');
picker.show('keepout',keepOut);key(document,'Escape');
assert.equal(container.hidden,true);assert.equal(document.activeElement,keepOut);assert.equal(cancellations.at(-1),'keepout');
picker.show('boundary',keepIn);cancel.emit('click');
assert.equal(container.hidden,true);assert.equal(document.activeElement,keepIn);

picker.show('boundary',keepIn);document.emit('click',{target:buttons[2]});assert.equal(picker.state().open,true);
document.emit('click',{target:keepIn});assert.equal(picker.state().open,true);
document.emit('click',{target:outside});assert.equal(picker.state().open,false);
picker.show('keepout',keepOut);const priorCancellations=cancellations.length;picker.close();
assert.equal(cancellations.length,priorCancellations,'Programmatic close must not recurse into cancellation.');

picker.show('boundary',keepIn);picker.setDisabled(true);
assert.deepEqual(picker.state(),{open:false,kind:null,disabled:true});assert.ok(buttons.every(button=>button.disabled));
picker.show('boundary',keepIn);assert.equal(container.hidden,true);assert.equal(chosen.length,6);
picker.setDisabled(false);picker.show('boundary',keepIn);assert.equal(container.hidden,false);assert.ok(buttons.every(button=>!button.disabled));
const snapshot=picker.state();snapshot.kind='keepout';assert.equal(picker.state().kind,'boundary');
assert.throws(()=>picker.show('wrong',keepIn),/Tipo de região/);assert.equal(picker.state().kind,'boundary');
assert.throws(()=>picker.choose('unknown'),/Forma de região/);assert.equal(picker.state().kind,'boundary');
assert.deepEqual(picker.choose('freehand'),{open:false,kind:null,disabled:false});
assert.deepEqual(chosen.at(-1),{shape:'freehand',kind:'boundary'});
assert.equal(chosen.length,7,'Supported commands use the same selection handler as shape buttons.');
picker.choose('circle');assert.equal(chosen.length,7,'A command needs an open region picker.');
picker.setDisabled(true);picker.choose('polygon');assert.equal(chosen.length,7);
picker.setDisabled(false);
picker.destroy();picker.show('boundary',keepIn);assert.equal(container.hidden,true);
picker.choose('circle');buttons[0].emit('click');assert.equal(chosen.length,7);assert.equal(document.events.click.length,0);assert.equal(document.events.keydown.length,0);
const invalid=new Element(document);invalid.children=buttons.slice(0,4);assert.throws(()=>createRegionPicker(invalid),/cinco formas/);
console.log('Region picker passed: five choices, deferred drawing, kind switching, toggle/cancel/outside click, keyboard/focus, disable, immutable state and cleanup.');
