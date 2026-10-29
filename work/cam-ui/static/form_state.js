// Form state is independent of rendering, so changing a mesh never resets feeds
// or silently restores the example's machining parameters.
import {operationListFromOptions,operationOptionsFromList,patchOperationList} from './operation_list.js';
import {effectiveMachiningOptions} from './smart_mode.js';
export function numericValue(raw,label,{required=true,fallback=null,min=-Infinity,max=Infinity}={}){
 const empty=raw==null||String(raw).trim()==='';
 const value=empty?NaN:Number(raw);
 if(Number.isFinite(value)&&value>=min&&value<=max)return value;
 if(!required)return fallback;
 throw Error(empty?`Preencha o campo: ${label}.`:`${label}: informe um número ${min>0?'positivo':min===0?'maior ou igual a zero':'válido'}${Number.isFinite(max)?`, até ${max}`:''}.`);
}
const positive=Number.MIN_VALUE;
export const TIMING_DEFAULTS=Object.freeze({timing_model:'acceleration',machine_max_rate_mm_min:Object.freeze([1500,1500,1500]),machine_acceleration_mm_s2:Object.freeze([10,10,10]),machine_steps_per_mm:Object.freeze([400,400,400]),machine_junction_deviation_mm:.01,machine_planner_blocks:15});
export const TIMING_AXIS_FIELDS=Object.freeze({machineMaxRate:['machineMaxRateX','machineMaxRateY','machineMaxRateZ'],machineAcceleration:['machineAccelerationX','machineAccelerationY','machineAccelerationZ'],machineSteps:['machineStepsX','machineStepsY','machineStepsZ']});
export const TIMING_SCALAR_FIELDS=Object.freeze(['timingModel','machineJunctionDeviation','machinePlannerBlocks']);
export const TIMING_FORM_IDS=Object.freeze([...TIMING_SCALAR_FIELDS,...Object.values(TIMING_AXIS_FIELDS).flat()]);
const timingArraySettings={machineMaxRate:['machine_max_rate_mm_min','Velocidade máxima'],machineAcceleration:['machine_acceleration_mm_s2','Aceleração'],machineSteps:['machine_steps_per_mm','Passos por milímetro']};
const timingNumber=(value,label,options)=>numericValue(typeof value==='number'||typeof value==='string'?value:NaN,label,options);
export function readTimingValues(values={},previous={}, {strict=true}={}){
 const timingModel=values.timingModel??previous.timing_model??TIMING_DEFAULTS.timing_model;
 if(!['acceleration','constant'].includes(timingModel))throw Error('Escolha o modelo de tempo: aceleração ou velocidade constante.');
 const result={timing_model:timingModel};
 for(const [formKey,[setting,label]]of Object.entries(timingArraySettings)){
  const saved=previous[setting]===undefined?TIMING_DEFAULTS[setting]:previous[setting],raw=values[formKey]===undefined?saved:values[formKey];
  if(!Array.isArray(saved)||saved.length!==3||!Array.isArray(raw)||raw.length!==3)throw Error(`${label}: informe os três eixos X, Y e Z.`);
  const fallback=saved.map((value,i)=>timingNumber(value,`${label} ${'XYZ'[i]}`,{min:positive}));
  result[setting]=raw.map((value,i)=>timingNumber(value,`${label} ${'XYZ'[i]}`,{required:strict,fallback:fallback[i],min:positive}));
 }
 const scalar=(formKey,setting,label,min=positive,max=Infinity)=>{
  const saved=timingNumber(previous[setting]??TIMING_DEFAULTS[setting],label,{min,max});
  return timingNumber(values[formKey]??saved,label,{required:strict,fallback:saved,min,max});
 };
 result.machine_junction_deviation_mm=scalar('machineJunctionDeviation','machine_junction_deviation_mm','Desvio de junção',0);
 const planner=scalar('machinePlannerBlocks','machine_planner_blocks','Blocos do planejador',2,128);
 if(!Number.isInteger(planner)){
  if(strict)throw Error('Blocos do planejador: informe um número inteiro de 2 a 128.');
  result.machine_planner_blocks=previous.machine_planner_blocks??TIMING_DEFAULTS.machine_planner_blocks;
 }else result.machine_planner_blocks=planner;
 return result;
}
export function timingFormValues(operations={}){
 const timing=readTimingValues({},operations),values={timingModel:timing.timing_model,machineJunctionDeviation:timing.machine_junction_deviation_mm,machinePlannerBlocks:timing.machine_planner_blocks};
 for(const [formKey,[setting]]of Object.entries(timingArraySettings))values[formKey]=[...timing[setting]];
 return values;
}
export function timingControlState(model='acceleration'){
 const acceleration=model!=='constant';
 return {rapidDisabled:acceleration,profileDisabled:!acceleration,
  rapidHint:acceleration?'O rápido estimado é usado apenas no modelo constante. G0 usa os limites por eixo abaixo.':'Este rápido estima G0 com velocidade constante. O controlador da máquina define o rápido real.',
  estimateHint:acceleration?'O tempo e a reprodução incluem aceleração, desaceleração e redução nos cantos, limitadas pelo perfil por eixo. Não inclui espera do spindle.':'Modelo legado: tempo e reprodução com velocidade constante, sem aceleração nem redução nos cantos. Não inclui espera do spindle.'};
}
export function cutoutPreferences(previous={},values={}){
 const contours=values.cutoutContours??previous.cutout_contours??'external';
 if(!['external','internal','all'].includes(contours))throw Error('Escolha os contornos do Cutout: somente externo, somente internos ou internos + externo.');
 return {cutout_use_roughing_regions:false,cutout_contours:contours,
  cutout_use_prior_roughing:values.cutoutUsePriorRoughing??previous.cutout_use_prior_roughing??true};
}
export function priorRoughingAvailable(rough,cutout,order,sequence=null,drillEnabled=false){
 if(!rough||!cutout)return false;
 if(sequence==null)return order==='roughing_then_cutout';
 const active=sequence.filter(id=>id==='roughing'||id==='cutout'||(id==='drill'&&drillEnabled));
 const cutoutIndex=active.indexOf('cutout');
 return cutoutIndex>0&&active[cutoutIndex-1]==='roughing';
}
export function isAutomaticStockBoundary(settings,bounds){
 const existing=settings.boundaries_mm;
 if(existing?.length!==1||existing[0].length!==4||!bounds)return false;
 const [x0,y0]=bounds.minimum.map(v=>v-5),[x1,y1]=bounds.maximum.map(v=>v+5);
 const automatic=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
 return existing[0].every((p,i)=>p.every((v,j)=>Math.abs(v-automatic[i][j])<1e-7));
}
export function addRoughingRegion(settings,kind,polygon,bounds){
 const key=kind==='keepout'?'exclusions_mm':'boundaries_mm';
 let existing=settings[key]||[];
 // The initial full-stock limit is a default, not a second Keep In that
 // should swallow the first region the user explicitly draws.
 if(key==='boundaries_mm'&&isAutomaticStockBoundary(settings,bounds))existing=[];
 return {...settings,[key]:[...existing,polygon]};
}
export function readOperationValues(v,previous={},tool={},stockTop=0,{strict=true}={}){
 const timing=readTimingValues(v,previous,{strict});
 const machiningMode=v.machiningMode??previous.machining_mode??'manual';
 if(!['manual','smart'].includes(machiningMode))throw Error('Escolha o modo Manual ou Inteligente.');
 const smart=machiningMode==='smart';
 const rough=smart||!!v.roughEnabled,cutout=smart||!!v.cutoutEnabled,drill=!!v.drillEnabled;
 if(strict&&!rough&&!cutout&&!drill)throw Error('Ative Roughing, Drill ou Cutout para calcular.');
 const n=(key,label,fallback,required,min=positive)=>numericValue(v[key],label,{fallback,required:strict&&required,min});
 const feed=(key,label,fallback,active)=>{
  if(v[key]==null||String(v[key]).trim()==='')return null;
  return n(key,label,fallback,active);
 };
 const previousDepth=stockTop-(previous.cutout_bottom_mm??stockTop-1);
 const depth=n('cutoutDepth','Profundidade do cutout',previousDepth>0?previousDepth:1,cutout&&!smart);
 const previousDrillDepth=stockTop-(previous.drill_bottom_mm??stockTop-1);
 const drillDepth=n('drillDepth','Profundidade do Drill',previousDrillDepth>0?previousDrillDepth:1,drill);
 const allowHelix=v.drillAllowHelix??previous.drill_allow_helix??false;
 const retractMode=v.drillRetractMode??previous.drill_retract_mode??'full';
 if(!['full','chip_break'].includes(retractMode))throw Error('Escolha a retirada completa ou curta do Drill.');
 const rapidReentry=v.drillRapidReentry??previous.drill_rapid_reentry??true;
 const drillNumber=(key,label,fallback,active)=>numericValue(v[key]??fallback,label,{fallback,required:strict&&active,min:positive});
 const list=operationListFromOptions({...previous,order:v.operationOrder||previous.order||'roughing_then_cutout',operation_sequence:v.operationSequence??previous.operation_sequence});
 const normalized=operationOptionsFromList(patchOperationList(list,{enabled:{roughing:rough,cutout,drill}}));
 const optionalSmart=(key,label,fallback,min=-Infinity)=>{
  const raw=v[key]===undefined?fallback:v[key];
  if(raw==null||String(raw).trim()==='')return null;
  return numericValue(raw,label,{required:strict&&smart,fallback,min});
 };
 return effectiveMachiningOptions({...normalized,...timing,
  machining_mode:machiningMode,
  smart_part_released:v.smartPartReleased??previous.smart_part_released??false,
  smart_stock_bottom_mm:optionalSmart('smartStockBottom','Fundo do bruto',previous.smart_stock_bottom_mm??null),
  smart_breakthrough_mm:numericValue(v.smartBreakthrough??previous.smart_breakthrough_mm??0,'Ultrapassagem do bruto',{required:strict&&smart,fallback:previous.smart_breakthrough_mm??0,min:0}),
  smart_skin_mm:optionalSmart('smartSkin','Pele externa',previous.smart_skin_mm??null,positive),
  roughing_order:v.roughingOrder||previous.roughing_order||'region_first',
  drill_bottom_mm:stockTop-drillDepth,
  drill_peck_mm:n('drillPeck','Passo de furação',previous.drill_peck_mm??1,drill),
  drill_retract_mode:retractMode,
  drill_retract_mm:drillNumber('drillRetract','Subida entre mergulhos',previous.drill_retract_mm??1,drill&&retractMode==='chip_break'),
  drill_rapid_reentry:rapidReentry,
  drill_reentry_gap_mm:drillNumber('drillReentryGap','Distância antes de retomar o mergulho',previous.drill_reentry_gap_mm??.25,drill&&rapidReentry),
  drill_tolerance_mm:n('drillTolerance','Tolerância circular',previous.drill_tolerance_mm??.03,drill),
  drill_allow_helix:allowHelix,
  drill_center_cutting:v.drillCenterCutting??previous.drill_center_cutting??false,
  drill_compensate_facets:v.drillCompensateFacets??previous.drill_compensate_facets??false,
  drill_feed_mm_min:feed('drillFeed','Feedrate do Drill',previous.drill_feed_mm_min??tool.feed_mm_min??null,drill&&allowHelix),
  cutout_bottom_mm:stockTop-depth,
  cutout_stepdown_mm:n('cutoutStepdown','Stepdown do cutout',previous.cutout_stepdown_mm||.635,cutout),
  cutout_smoothing_mm:numericValue(v.cutoutSmoothing??previous.cutout_smoothing_mm??0,'Fluidez do Cutout',{required:strict&&cutout,fallback:previous.cutout_smoothing_mm??0,min:0,max:.1}),
  cutout_direction:v.cutoutDirection||previous.cutout_direction||'climb',
  ...cutoutPreferences(previous,v),
  roughing_feed_mm_min:feed('roughFeed','Feedrate do desbaste',previous.roughing_feed_mm_min??tool.feed_mm_min??null,rough),
  cutout_feed_mm_min:feed('cutoutFeed','Feedrate do cutout',previous.cutout_feed_mm_min??tool.feed_mm_min??null,cutout),
  plunge_mm_min:feed('plungeFeed','Plunge rate',previous.plunge_mm_min??tool.plunge_mm_min??null,rough||cutout||drill),
  rapid_mm_min:n('rapidFeed','Rápido estimado',previous.rapid_mm_min||3000,timing.timing_model==='constant'&&(rough||cutout||drill)),
  spindle_rpm:feed('spindleRpm','Spindle',previous.spindle_rpm??tool.spindle_rpm??null,rough||cutout||drill)});
}
export function validateTimingFeeds(operations,tool={}){
 const missing=[];
 if(operations.roughing_enabled&&!(operations.roughing_feed_mm_min||tool.feed_mm_min))missing.push('Feedrate do desbaste');
 if(operations.cutout_enabled&&!(operations.cutout_feed_mm_min||tool.feed_mm_min))missing.push('Feedrate do cutout');
 if(operations.drill_enabled&&operations.drill_allow_helix&&!(operations.drill_feed_mm_min||tool.feed_mm_min))missing.push('Feedrate do Drill');
 if(!(operations.plunge_mm_min||tool.plunge_mm_min))missing.push('Plunge rate');
 if(missing.length)throw Error('Preencha '+missing.join(', ')+'. Os valores também podem vir da ferramenta selecionada.');
}
export function importedMachiningState(mesh,settings={},operations={},diameter=3.175){
 const top=mesh.bounds_mm.maximum[2],bottom=mesh.bounds_mm.minimum[2];
 if(!(top>bottom))throw Error('O STL precisa ter espessura em Z para usinar. Confira a unidade e a face.');
 const [x0,y0]=mesh.bounds_mm.minimum.map(v=>v-5),[x1,y1]=mesh.bounds_mm.maximum.map(v=>v+5);
 return {settings:{stepdown_mm:.7,stepover_mm:diameter*.4,sampling_mm:.2,tolerance_mm:0,
  radial_allowance_mm:0,axial_allowance_mm:0,boundary_margin_mm:.01,raster_origin_y_mm:0,
  entry_angle_deg:3,clearance_mm:2.54,approach_gap_mm:.25,strategy:'hybrid',surface_error_mm:.15,path_tolerance_mm:.02,optimize_entries:true,region_mode:'layer',
  cleanup_contours:true,domain_mode:'expanded',compress_collinear:true,raster_angle_deg:0,
  ...settings,boundaries_mm:[[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]],exclusions_mm:[],stock_top_mm:top,bottom_mm:bottom,obstacle_top_mm:top},
  operations:{...operations,...cutoutPreferences(operations),cutout_bottom_mm:bottom,drill_bottom_mm:bottom,smart_stock_bottom_mm:null},stock:{x0,y0,x1,y1,step:.25}};
}
export function calculationSummary(motion){
 const cuts=(motion?.moves||[]).filter(m=>m[0]==='cut');
 const activeNames=[...new Set(cuts.map(m=>m[8]))].map(id=>({cutout:'Cutout',drill:'Drill',roughing:'Roughing'})[id]||id);
 const summary=!cuts.length?'Nenhum corte necessário nesta configuração. Confira a área permitida, o bruto e as profundidades.':motion?.operations?.roughing&&!cuts.some(m=>m[8]==='roughing')?`${activeNames.join(' + ')} calculado e salvo. Roughing sem material a remover nesta configuração.`:'Percurso calculado e salvo localmente.';
 const notes=[summary];
 const cutout=motion?.operations?.cutout;
 if(motion?.operations?.roughing?.annular_pocket_layers)notes.push(`Rough anular: contornos contínuos em ${motion.operations.roughing.annular_pocket_layers} camada(s).`);
 const detours=Object.values(motion?.operations||{}).reduce((sum,op)=>sum+(op.fixture_detour_moves||0),0);
 if(detours)notes.push(`Travessias: ${detours} trecho(s) desviando da fixação.`);
 if(cutout?.contours_selection==='internal')notes.push('Cutout somente internos: o contorno externo não será cortado.');
 if(cutout?.contours_selection==='automatic_internal')notes.push('Peça já solta: somente recortes internos automáticos, sem recortar o exterior.');
 if(cutout?.contours_selection==='external'&&cutout.skipped_internal_contours>0)notes.push(`Cutout externo: ${cutout.skipped_internal_contours} contorno(s) interno(s) fora do recorte. Para incluí-los, escolha Internos + externo.`);
 if(cutout?.contours_selection==='automatic')notes.push(`Cutout inteligente: ${cutout.selected_internal_indices?.length||0} recorte(s) interno(s) antes do exterior. Miolos preservados como sobra, sem desbaste integral.`);
 const drill=motion?.operations?.drill;
 if(Number.isFinite(drill?.holes_count))notes.push(`Drill: ${drill.holes_count} furo(s)${drill.helix_count>0?`, ${drill.helix_count} em hélice`:''}.${drill.skipped_holes_count>0?` ${drill.skipped_holes_count} furo(s) ignorado(s); confira a compatibilidade na aba Drill.`:''}`);
 return notes.join(' ');
}
export function jobStatusText(state,elapsed=0){
 const seconds=Math.floor(Number.isFinite(state.elapsed_s)?state.elapsed_s:elapsed);
 const time=seconds<60?`${seconds}s`:`${Math.floor(seconds/60)}min ${seconds%60}s`;
 const phase=state.phase||'Calculando regiões, contornos e rampas';
 const progress=Number.isFinite(state.progress)?` · ${Math.round(Math.min(1,Math.max(0,state.progress))*100)}%`:'';
 return `${phase}${progress} · ${time}`;
}
