import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as THREE from '../ui-runtime/node_modules/three/build/three.module.js';
import {DEPTH_COLORS,depthScale,depthFraction,depthGradient,createDepthMaterial} from './static/depth_shading.js';

const scale=depthScale(-17,0);
assert.equal(depthFraction(0,scale),0);assert.equal(depthFraction(-17,scale),1);
assert.equal(depthFraction(-4,scale),4/17);assert.equal(depthFraction(-6,scale),6/17);
assert.equal(depthFraction(10,scale),0);assert.equal(depthFraction(-20,scale),1);
assert.equal(depthFraction(5,depthScale(5,5)),0);
assert.equal(depthFraction(8,depthScale(0,17)),9/17);
assert.throws(()=>depthScale(2,1));assert.throws(()=>depthScale(NaN,2));
for(const color of DEPTH_COLORS)assert.ok(depthGradient().includes(color));
const brightness=DEPTH_COLORS.map(color=>{const c=new THREE.Color(color);return .2126*c.r+.7152*c.g+.0722*c.b;});
assert.ok(brightness.every((v,i)=>!i||v<brightness[i-1]),'Depth must consistently darken, without a false bright deep band');
const material=createDepthMaterial(THREE,-17,0);
assert.equal(material.transparent,false);assert.equal(material.depthWrite,true);assert.equal(material.toneMapped,false);
const shader={vertexShader:THREE.ShaderLib.basic.vertexShader,fragmentShader:THREE.ShaderLib.basic.fragmentShader,uniforms:{}};
material.onBeforeCompile(shader);
assert.equal(shader.uniforms.camDepthTop.value,0);assert.equal(shader.uniforms.camDepthRange.value,17);
assert.match(shader.vertexShader,/camModelZ = position.z/);assert.match(shader.fragmentShader,/camDepthTop - camModelZ/);
assert.equal(shader.uniforms.camDepthPalette.value.length,5);
assert.deepEqual(shader.uniforms.camDepthPalette.value[0],new THREE.Color(DEPTH_COLORS[0]));
const flatShader={vertexShader:THREE.ShaderLib.basic.vertexShader,fragmentShader:THREE.ShaderLib.basic.fragmentShader,uniforms:{}};
createDepthMaterial(THREE,5,5).onBeforeCompile(flatShader);assert.ok(flatShader.uniforms.camDepthRange.value>0);

// Exercise actual appearance and legend handlers with the real Three.js classes.
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{style:{},hidden:false,checked:true,textContent:''});return nodes.get(id);};
const group=new THREE.Group(),mesh=new THREE.Mesh(new THREE.BoxGeometry(10,10,17),new THREE.MeshStandardMaterial());
const edges=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry),new THREE.LineBasicMaterial());edges.userData.depthEdges=true;group.add(mesh,edges);
const context={THREE,createDepthMaterial,depthScale,depthGradient,$,depthColoring:true,mode:'paths',data:{},modelGroup:group,
 bounds:()=>({minimum:[0,0,-17],maximum:[84,84,0]}),fmt:v=>String(v),localStorage:{setItem(){}}};
vm.createContext(context);
const source=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
vm.runInContext(source.slice(source.indexOf('function modelMaterial()'),source.indexOf('function makeTool()')),context);
context.applyModelAppearance();
assert.equal(mesh.material.type,'MeshBasicMaterial');assert.equal($('depthLegend').hidden,false);
assert.equal($('depthBottom').textContent,'17 mm');assert.equal($('depthReference').textContent,'Topo Z 0 mm');
let disposed=false;mesh.material.addEventListener('dispose',()=>disposed=true);
context.setDepthColoring(false);
assert.ok(disposed);assert.equal(mesh.material.type,'MeshStandardMaterial');assert.equal(mesh.material.opacity,1);assert.equal(mesh.material.depthWrite,true);
assert.equal(edges.visible,false);assert.equal($('depthLegend').hidden,true);
context.setDepthColoring(true);context.mode='stock';context.applyModelAppearance();
assert.equal(mesh.material.opacity,.22);assert.equal(mesh.material.transparent,true);assert.equal(edges.visible,false);assert.equal($('depthLegend').hidden,true);
context.mode='paths';context.applyModelAppearance();assert.equal(mesh.material.type,'MeshBasicMaterial');assert.equal(edges.visible,true);
group.visible=false;context.updateDepthLegend();assert.equal($('depthLegend').hidden,true);
console.log('Depth shading passed: model-space Z, exact -4/-6 mm scale, monotonic palette/legend, flat models, opaque depth buffer, material disposal and unchanged stock ghost display.');
