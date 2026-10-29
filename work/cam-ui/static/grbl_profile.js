// Only the explicit apply action writes controller settings.
const PROFILE_KEYS=['machine_max_rate_mm_min','machine_acceleration_mm_s2'];
const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));
export function grblProfileValues(record){
 const values={};
 for(const key of PROFILE_KEYS){
  const axis=record?.[key];
  if(!Array.isArray(axis)||axis.length!==3)throw Error('Preencha os três eixos do perfil da máquina.');
  values[key]=axis.map(value=>{
   if((typeof value!=='number'&&typeof value!=='string')||String(value).trim()===''||!Number.isFinite(Number(value))||Number(value)<=0)throw Error('Velocidade máxima e aceleração precisam ser números positivos.');
   return Number(value);
  });
 }
 return values;
}
export function grblProfileRows(values){
 if(!values)return [];
 const profile=grblProfileValues(values);
 return ['X','Y','Z'].map((axis,i)=>({axis,maximum:profile.machine_max_rate_mm_min[i],acceleration:profile.machine_acceleration_mm_s2[i]}));
}
export function createGrblProfile({api,readProfile,onChange=()=>{},now=()=>Date.now()}){
 let ports=[],connection={port:'',baudrate:115200},busy=false,phase='idle',message='Leia a controladora antes de gravar.',current=null,readId=null,expires=0,lastReport=null;
 function state(){return {ports:clone(ports),connection:{...connection},busy,phase,message,read_id:readId,can_apply:!busy&&!!readId&&now()<expires,values:clone(current),last_report:clone(lastReport)};}
 function render(){onChange(state());}
 function select(next={}){
  if(busy)throw Error('Aguarde a transferência com o GRBL.');
  const selected={port:next.port??connection.port,baudrate:Number(next.baudrate??connection.baudrate)};
  if(!Number.isInteger(selected.baudrate)||selected.baudrate<=0)throw Error('Baud rate inválido.');
  if(typeof selected.port!=='string')throw Error('Porta serial inválida.');
  if(selected.port!==connection.port||selected.baudrate!==connection.baudrate){readId=null;expires=0;current=null;lastReport=null;phase='idle';message='Leia a controladora selecionada antes de gravar.';}
  connection=selected;render();return state();
 }
 function begin(nextPhase,text){if(busy)throw Error('Aguarde a transferência com o GRBL.');busy=true;phase=nextPhase;message=text;render();}
 async function refresh(){
  begin('ports','Procurando portas seriais…');
  try{const result=await api('/api/grbl/ports',{});ports=result.ports||[];phase='idle';message=ports.length?'Selecione a porta da CNC e leia os valores.':'Nenhuma porta serial encontrada. Confira o cabo USB.';return result;}
  catch(error){phase='error';message=error.message;throw error;}finally{busy=false;render();}
 }
 async function read(next){
  if(busy)throw Error('Aguarde a transferência com o GRBL.');
  if(busy)throw Error('Aguarde a transferência com o GRBL.');
  if(next)select(next);
  if(!connection.port)throw Error('Selecione a porta serial da CNC.');
  readId=null;expires=0;current=null;lastReport=null;begin('reading','Lendo estado e configurações do GRBL…');
  try{
   const result=await api('/api/grbl/read',{...connection});
   current=grblProfileValues(result.values);
   if(typeof result.read_id!=='string'||!result.read_id)throw Error('Leitura do GRBL sem identificação. Leia novamente.');
   readId=result.read_id;expires=now()+Math.max(0,Number(result.expires_in_s)||0)*1000;
   phase='read';message='Valores lidos. O perfil acima foi preservado; Gravar envia os valores editados.';lastReport=clone(result);return result;
  }catch(error){readId=null;expires=0;phase='error';message=error.message;throw error;}finally{busy=false;render();}
 }
 async function apply(command={}){
  if(command.port!==undefined||command.baudrate!==undefined)select(command);
  if(busy)throw Error('Aguarde a transferência com o GRBL.');
  if(!readId||now()>=expires){readId=null;render();throw Error('Leia os valores atuais do GRBL antes de gravar.');}
  if(command.read_id!==undefined&&command.read_id!==readId)throw Error('A leitura informada não corresponde à controladora selecionada.');
  const values=grblProfileValues(command.values??readProfile()),identifier=readId;
  begin('writing','Gravando e conferindo $110–$112 e $120–$122…');
  // Never retry a write: a timeout or partial response requires another read.
  readId=null;expires=0;
  try{
   const result=await api('/api/grbl/apply',{...connection,read_id:identifier,values});lastReport=clone(result);
   current=result.values?grblProfileValues(result.values):null;
   phase=result.status==='verified'&&result.verified===true?'verified':result.status==='partial'?'partial':'error';
   message=result.message||(phase==='verified'?'Valores gravados e confirmados no GRBL.':result.error||'A gravação não foi confirmada. Leia o GRBL novamente.');
   return result;
  }catch(error){current=null;phase='error';message='Gravação não confirmada: '+error.message+' Leia o GRBL antes de tentar novamente.';throw Error(message,{cause:error});}finally{busy=false;render();}
 }
 return {state,select,refresh,read,apply};
}
