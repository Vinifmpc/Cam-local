import factory from '/vendor/manifold.js';
import {buildSolid} from './stock_solid.js';
const ready=factory({locateFile:()=>'/vendor/manifold.wasm'}).then(module=>{module.setup();return module;});
onmessage=async({data})=>{
 const {generation,target,config,moves}=data;
 try{
  const module=await ready;
  const mesh=buildSolid(module,config,moves,target,progress=>postMessage({type:'progress',generation,target,progress}));
  postMessage({type:'solid',generation,target,...mesh},[mesh.positions.buffer,mesh.normals.buffer,mesh.indices.buffer]);
 }catch(error){postMessage({type:'error',generation,target,error:error.message||String(error)});}
};
