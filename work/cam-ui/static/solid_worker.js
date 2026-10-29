import factory from '/vendor/manifold.js';
import {buildSolid,SolidMeshCache} from './stock_solid.js';
const ready=factory({locateFile:()=>'/vendor/manifold.wasm'}).then(module=>{module.setup();return module;});
let context=null,queue=Promise.resolve();

function initialize(data){
 const {generation,config,moves}=data;
 if(!Number.isInteger(generation)||generation<0||!config||!Array.isArray(moves))throw Error('Configuração da reconstrução inválida.');
 const own={generation,cache:null,module:null};
 own.cache=new SolidMeshCache((settings,paths,target,progress)=>buildSolid(own.module,settings,paths,target,progress),config,moves);
 context=own;return own;
}

onmessage=({data})=>{
 const {generation,request_id,purpose='display'}=data;
 try{
  if(data.type==='init'){
   const own=initialize(data);
   postMessage({type:'ready',generation,stats:own.cache.stats()});return;
  }
  // Preserve the former one-message protocol for existing callers. Repeated
  // requests of one generation now keep their meshes instead of rebuilding.
  if((!context||context.generation!==generation)&&data.config&&Array.isArray(data.moves))initialize(data);
  const own=context,target=data.target??own?.cache.moves.length;
  if(!own||own.generation!==generation)throw Error('A reconstrução pertence a outro cálculo.');
  queue=queue.catch(()=>{}).then(async()=>{
   if(context!==own)return;
   try{
    own.module=await ready;if(context!==own)return;
    const mesh=own.cache.get(target,progress=>postMessage({type:'progress',generation,target,request_id,purpose,progress,stats:own.cache.stats()}));
    // get returns cloned arrays; transfer never invalidates the cache entry.
    postMessage({type:'solid',generation,target,request_id,purpose,...mesh},[mesh.positions.buffer,mesh.normals.buffer,mesh.indices.buffer]);
   }catch(error){postMessage({type:'error',generation,target,request_id,purpose,error:error.message||String(error),stats:own.cache.stats()});}
  });
 }catch(error){postMessage({type:'error',generation,target:data.target,request_id,purpose,error:error.message||String(error),stats:context?.cache.stats()});}
};
