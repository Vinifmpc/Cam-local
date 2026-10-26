import {StockPlayback} from './stock_model.js';
let playback=null,generation=0;
onmessage=({data})=>{
 try{
  if(data.type==='init'){
   playback=new StockPlayback(data.config,data.moves);generation=data.generation;
  }
  if(!playback)return;
  const target=data.type==='init'?0:Math.max(0,Math.min(playback.moves.length,data.target));
  if(data.generation!==generation)return;
  const state=playback.seek(target);
  postMessage({type:'stock',generation,index:target,...state},[state.heights.buffer]);
 }catch(e){postMessage({type:'error',generation:data.generation,error:e.message});}
};
