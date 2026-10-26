// One outstanding long poll; no screenshots, DOM selectors or injected scripts.
export async function runCommandBridge(api, execute, {signal}={}){
 const client=crypto.randomUUID();
 const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 while(!signal?.aborted){
  try{
   const item=await api('/api/commands/next',{client,wait_s:20});
   if(!item.command_id)continue;
   let reply;
   try{reply={result:await execute(item.command)};}
   catch(error){reply={error:error.message||String(error)};}
   // A failed acknowledgement is retried with the same result, never the action.
   for(let attempt=0;attempt<4;attempt++){
    try{await api('/api/commands/complete',{client,command_id:item.command_id,...reply});break;}
    catch{await delay(500*(attempt+1));}
   }
  }catch{await delay(1500);}
 }
}
