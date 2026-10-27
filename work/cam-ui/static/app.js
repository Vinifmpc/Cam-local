import * as THREE from 'three';
import {FeedClock,timeLabel} from './playback.js';
import {activeStockBottom,stockGridIndices,sampleStockGrid} from './stock_model.js';
import {smoothWallNormals} from './stock_shading.js';
import {numericValue,readOperationValues,validateTimingFeeds,importedMachiningState,jobStatusText,calculationSummary,cutoutPreferences,priorRoughingAvailable,addRoughingRegion,isAutomaticStockBoundary} from './form_state.js';
import {OrbitControls} from '/vendor/OrbitControls.js';
import {SHAPE_NAMES,MAX_REGION_VERTICES,rectanglePolygon,roundPolygon,freehandPolygon,validateRegionPolygon,parseRegionVertices} from './region_shapes.js';
import {runCommandBridge} from './command_bridge.js';
import {createDepthMaterial,depthScale,depthGradient} from './depth_shading.js';
import {createOperationList,operationListFromOptions,operationOptionsFromList,mergeOperationOptions} from './operation_list.js';
import {createRegionPicker} from './region_picker.js';
import {getCutoutRecovery} from './cutout_feedback.js';
import {effectiveMachiningOptions,validateSmartOperationPatch,smartPlanText,smartEntryHint,smartPolicyText} from './smart_mode.js';
import {createAutomaticRegionOverlay,smartPlanForState} from './automatic_regions.js';
import {placementAction,placementOrigin,samePlacement,nearestOutlinePoint,shiftWorkFrame,secondSideState} from './placement_controls.js';
import {machiningProfile,profilePatch} from './machining_presets.js';
const $=id=>document.getElementById(id),fmt=(v,d=2)=>Number(v).toLocaleString('pt-BR',{maximumFractionDigits:d});
const flip=[[1,0,0],[0,-1,0],[0,0,-1]];
const identity=[[1,0,0],[0,1,0],[0,0,1]];
const rect=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
let token='',tools=[],data=null,tool=null,settings={},placement={},motion=null,windows=null,operations={},feedClock=null,computedProject=null,exportBusy=false;
let presetStore={presets:[],last_used:null,selected_id:null},presetTimer=null,presetQueue=Promise.resolve(),presetSaving=false,presetError='';
let revision=0,playing=false,cursor=0,lastTime=0,busy=false,mode='paths',drawMode=null,dragStart=null,preview=null;
let drawShape=null,draftPoints=[],drawingPointer=null,pendingRegionShape='rectangle';
let calcProgressTimer=null,calcProgressStarted=0,calcProgressValue=null,activeCalculationJob=null,cancellationRequested=false;
let lastCalculationJob=null;
let regionPicker=null,cutoutRecovery=null,cutoutRecoveryApplying=false;
let depthColoring=true;
let smartPlanPreview=null,smartPlanPending=false,manualOperationState=null,manualCutoutPreferences=null;
let automaticRegionsSource=null,automaticRegionsZ=null;
let placementPanelTab=null,placementUiBusy=false,placementUndo=null;
let originPicking=false,originOutline=null,originReference=null,originRequest=0;
try{depthColoring=localStorage.getItem('cam-depth-colors')!=='false';}catch{}
let stockGeneration=0,stockBusy=false,stockReady=false,stockWanted=0,stockApplied=-1,stockLastSent=0,toastTimer;
let stockSampleSnapshot=null;
let solidWorker=null,solidBusy=false,solidMesh=null,solidIndex=-1,solidGeneration=-1,solidTimer=null,stockConfig=null,solidFailedIndex=null;
const worker=new Worker('/stock_worker.js',{type:'module'});
function toast(message,error=false,action=null){
 const host=$('toast');host.replaceChildren(document.createTextNode(message));host.className=error?'error':'';host.hidden=false;
 if(action){const button=document.createElement('button');button.id='toastAction';button.type='button';button.className='toast-action';button.textContent=action.label;button.onclick=action.run;host.append(button);}
 clearTimeout(toastTimer);toastTimer=setTimeout(()=>host.hidden=true,error?10000:5500);
}
function clearCutoutRecovery(){
 cutoutRecovery=null;$('cutoutRecovery').hidden=true;$('cutoutRecoveryApply').disabled=false;
 $('toast').querySelector?.('#toastAction')?.remove();
}
function presentCalculationError(message,context=null){
 clearCutoutRecovery();let recovery=null;
 if(context?.revision===revision&&getCutoutRecovery(message,context.operations)){
  try{recovery=getCutoutRecovery(message,readOperations({strict:false}));}catch{}
 }
 if(recovery){
  cutoutRecovery={...recovery,error:message,revision};$('cutoutRecoveryMessage').textContent=recovery.message;
  $('cutoutRecoveryApply').textContent=recovery.label;$('cutoutRecovery').hidden=false;
 }
 toast(message,true,recovery?{label:recovery.label,run:()=>applyCutoutRecovery().catch(error=>toast(error.message,true))}:null);
}
async function applyCutoutRecovery(){
 if(cutoutRecoveryApplying)throw Error('Aguarde a alteração do Cutout.');
 const recovery=cutoutRecovery;
 if(!recovery||busy||exportBusy||recovery.revision!==revision||!getCutoutRecovery(recovery.error,readOperations({strict:false}))){
  clearCutoutRecovery();throw Error('A configuração mudou. Confira o Cutout e calcule novamente.');
 }
 cutoutRecoveryApplying=true;$('cutoutRecoveryApply').disabled=true;
 try{
  await patchCommandConfig({operations:{cutout_contours:'external'}});
  selectOperationTab('cutout');$('cutoutContours').focus({preventScroll:true});
  toast('Cutout alterado para soltar a peça, somente pelo contorno externo. Calcule novamente.');
  return commandState();
 }finally{cutoutRecoveryApplying=false;if(cutoutRecovery===recovery)$('cutoutRecoveryApply').disabled=false;}
}
async function api(path,payload,raw=false){
 const response=await fetch(path,payload===undefined?{}:{method:'POST',headers:{'X-Cam-Token':token,...(raw?{}:{'Content-Type':'application/json'})},body:raw?payload:JSON.stringify(payload)});
 let result;try{result=await response.json();}catch{throw Error('O serviço local não retornou uma resposta válida. Confira o log do aplicativo.');}
 if(!response.ok)throw Error(result.error||'Falha na aplicação local.');return result;
}
function number(id,optional=false){const v=$(id).value;if(optional&&v==='')return null;return numericValue(v,$(id).parentElement.textContent.trim());}
function setCalculationJob(job=null){
 activeCalculationJob=job;cancellationRequested=false;
 $('cancelCalculation').disabled=!job;$('cancelCalculation').textContent='Cancelar cálculo';
}
function clearCalculationProgress(){clearInterval(calcProgressTimer);calcProgressTimer=null;setCalculationJob();$('calcProgress').hidden=true;}
function showCalculationProgress(state={},stale=false){
 const running=state.status==='running',failed=state.status==='failed',complete=state.status==='complete',cancelled=state.status==='cancelled';
 if(Number.isFinite(state.progress))calcProgressValue=Math.max(calcProgressValue??0,Math.min(99,Math.max(0,state.progress*100)));
 if(complete)calcProgressValue=100;
 $('calcProgress').hidden=false;$('calcProgress').dataset.state=cancelled?'cancelled':failed?'failed':stale?'stale':complete?'complete':'running';
 $('calcProgressLabel').textContent=cancelled?'Cálculo cancelado':failed?'Cálculo interrompido':stale?(complete?'Cálculo anterior concluído':'Calculando configuração anterior'):complete?'Cálculo concluído':'Calculando percursos';
 $('cancelCalculation').hidden=!running;
 $('calcProgressPercent').textContent=calcProgressValue==null?'…':Math.floor(calcProgressValue)+'%';
 if(running&&calcProgressValue==null)$('calcProgressBar').removeAttribute('value');
 else $('calcProgressBar').value=calcProgressValue??0;
 $('calcProgressBar').setAttribute('aria-valuetext',state.phase||$('calcProgressLabel').textContent);
 if(!running){clearInterval(calcProgressTimer);calcProgressTimer=null;setCalculationJob();}
 const elapsed=Number.isFinite(state.elapsed_s)?state.elapsed_s:(performance.now()-calcProgressStarted)/1000;
 $('calcProgressElapsed').textContent='Tempo decorrido: '+timeLabel(Math.max(0,elapsed));
}
function startCalculationProgress(){
 clearInterval(calcProgressTimer);setCalculationJob();calcProgressStarted=performance.now();calcProgressValue=null;
 showCalculationProgress({status:'running',phase:'Preparando o cálculo'});
 calcProgressTimer=setInterval(()=>{$('calcProgressElapsed').textContent='Tempo decorrido: '+timeLabel((performance.now()-calcProgressStarted)/1000);},500);
}
async function cancelCalculation(){
 if(!busy||!activeCalculationJob||cancellationRequested)return;
 const job=activeCalculationJob;cancellationRequested=true;
 $('cancelCalculation').disabled=true;$('cancelCalculation').textContent='Cancelando…';
 try{await api('/api/cancel',{job});}
 catch(e){
  // A delayed response must not revive the controls of a completed or newer job.
  if(activeCalculationJob!==job)return;
  cancellationRequested=false;$('cancelCalculation').disabled=false;$('cancelCalculation').textContent='Cancelar cálculo';
  toast('Não foi possível cancelar: '+e.message+'. Tente novamente.',true);
 }
}
function stop(){playing=false;$('play').textContent='▶ Reproduzir';$('play').setAttribute('aria-label','Reproduzir');$('play').setAttribute('aria-pressed','false');}
function showStockSurface(){
 const ready=solidMesh&&solidGeneration===stockGeneration&&solidIndex===stockWanted&&!playing&&stockReady;
 if(solidMesh)solidMesh.visible=mode==='stock'&&!!ready;
 if(stockMesh)stockMesh.visible=mode==='stock'&&stockReady&&!ready;
 if(stockWire)stockWire.visible=mode==='stock'&&stockReady;
 if(ready)$('surfaceStatus').textContent='Superfície sólida · bordas pelo percurso da fresa';
 else if(playing)$('surfaceStatus').textContent='Prévia rápida durante reprodução';
 else if(mode==='stock')$('surfaceStatus').textContent=solidBusy?'Reconstruindo superfície…':'Prévia em grade';
}
function cancelSolid(){
 clearTimeout(solidTimer);solidTimer=null;solidWorker?.terminate();solidWorker=null;solidBusy=false;
 showStockSurface();
}
function scheduleSolid(){
 clearTimeout(solidTimer);
 if(busy||mode!=='stock'||playing||!stockReady||stockApplied!==stockWanted||solidBusy||solidFailedIndex===stockWanted)return;
 if(solidMesh&&solidGeneration===stockGeneration&&solidIndex===stockWanted){showStockSurface();return;}
 solidTimer=setTimeout(()=>{
  if(busy||playing||!stockReady||stockApplied!==stockWanted||mode!=='stock')return;
  solidBusy=true;$('surfaceStatus').textContent='Reconstruindo superfície…';
  if(!solidWorker){
   solidWorker=new Worker('/solid_worker.js',{type:'module'});
   solidWorker.onmessage=({data:s})=>{
    if(s.generation!==stockGeneration)return;
    if(s.type==='progress'){if(s.target===stockWanted&&!playing)$('surfaceStatus').textContent=`Reconstruindo superfície · ${Math.round(s.progress*100)}%`;return;}
    solidBusy=false;
    if(s.target!==stockWanted||playing){scheduleSolid();return;}
    if(s.type==='error'){solidFailedIndex=s.target;$('surfaceStatus').textContent='Prévia em grade · '+s.error;return;}
    if(solidMesh){scene.remove(solidMesh);solidMesh.geometry.dispose();solidMesh.material.dispose();}
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(s.positions,3));geometry.setAttribute('normal',new THREE.BufferAttribute(s.normals,3));geometry.setIndex(new THREE.BufferAttribute(s.indices,1));geometry.computeBoundingSphere();
    solidMesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0xc9b388,roughness:.85,side:THREE.DoubleSide}));scene.add(solidMesh);
    solidIndex=s.target;solidGeneration=s.generation;showStockSurface();
   };
   solidWorker.onerror=()=>{solidBusy=false;solidFailedIndex=stockWanted;$('surfaceStatus').textContent='Prévia em grade · não foi possível reconstruir a superfície';};
  }
  solidWorker.postMessage({generation:stockGeneration,target:stockWanted,config:stockConfig,moves:motion?.moves||[]});
 },250);
}
function clearGroup(group){while(group.children.length){const item=group.children[0];group.remove(item);item.traverse(o=>{o.geometry?.dispose();o.material?.map?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();});}}

THREE.Object3D.DEFAULT_UP.set(0,0,1);
const scene=new THREE.Scene();scene.background=new THREE.Color('#e8eef3');
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;
$('canvasHost').append(renderer.domElement);
const camera=new THREE.OrthographicCamera(-60,60,60,-60,.1,10000);camera.position.set(130,-130,120);
let controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;
const hemi=new THREE.HemisphereLight(0xffffff,0x728399,2.5);hemi.position.set(0,0,200);scene.add(hemi);
const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(-80,-100,180);scene.add(light);
const modelGroup=new THREE.Group(),pathGroup=new THREE.Group(),rapidGroup=new THREE.Group(),regionGroup=new THREE.Group(),automaticRegionGroup=new THREE.Group(),toolGroup=new THREE.Group();
scene.add(modelGroup,pathGroup,rapidGroup,regionGroup,automaticRegionGroup,toolGroup);
const placementGizmo=new THREE.AxesHelper(1);
placementGizmo.setColors(0xbd6470,0x3b927e,0x4d82c1);
placementGizmo.material.depthTest=false;placementGizmo.material.depthWrite=false;placementGizmo.renderOrder=1000;placementGizmo.visible=false;
const placementBox=new THREE.Box3Helper(new THREE.Box3(),0x80aacb);
placementBox.material.transparent=true;placementBox.material.opacity=.55;placementBox.material.depthTest=false;placementBox.visible=false;
scene.add(placementGizmo,placementBox);
const originPreview=new THREE.Group(),originEdges=new THREE.Group();scene.add(originPreview,originEdges);
let grid=null,stockMesh=null,stockWire=null,span=100;
function resize(){const r=$('canvasHost').getBoundingClientRect();renderer.setSize(r.width,r.height,false);const a=r.width/r.height;camera.left=-span*a/2;camera.right=span*a/2;camera.top=span/2;camera.bottom=-span/2;camera.updateProjectionMatrix();}
new ResizeObserver(resize).observe($('canvasHost'));
function bounds(){return data?.mesh.bounds_mm||{minimum:[-10,-10,-5],maximum:[10,10,5],size:[20,20,10]};}
function view(which='iso',fit=true){
 if(originPicking)cancelOriginPick();
 let b=bounds();
 if(mode==='stock'){try{b={minimum:[number('stockX0'),number('stockY0'),simulationBottom()],maximum:[number('stockX1'),number('stockY1'),number('stockTop')]};b.size=b.maximum.map((v,i)=>v-b.minimum[i]);}catch{}}
 const center=new THREE.Vector3(...b.minimum).add(new THREE.Vector3(...b.maximum)).multiplyScalar(.5);
 const size=Math.max(b.size[0],b.size[1],b.size[2],10);
 if(fit){const r=$('canvasHost').getBoundingClientRect();span=size*1.6/Math.min(1,r.width/r.height);camera.zoom=1;}
 controls.dispose();camera.up.set(0,0,1);
 if(which==='top'){camera.up.set(0,1,0);camera.position.copy(center).add(new THREE.Vector3(0,0,size*3));}
 else if(which==='front')camera.position.copy(center).add(new THREE.Vector3(0,-size*3,0));
 else camera.position.copy(center).add(new THREE.Vector3(size*1.25,-size*1.65,size*1.4));
 camera.lookAt(center);controls?.dispose();controls=new OrbitControls(camera,renderer.domElement);controls.target.copy(center);controls.enableDamping=true;controls.enableRotate=!drawMode;controls.update();resize();
}
function setModel(triangles){
 clearGroup(modelGroup);const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(triangles,3));g.computeVertexNormals();
 modelGroup.add(new THREE.Mesh(g,modelMaterial()));
 const edges=new THREE.LineSegments(new THREE.EdgesGeometry(g,25),new THREE.LineBasicMaterial({color:0x172e52,transparent:true,opacity:.58,depthWrite:false}));
 edges.userData.depthEdges=true;edges.visible=depthColoring&&mode==='paths';modelGroup.add(edges);
 updateDepthLegend();
 if(grid){scene.remove(grid);grid.geometry.dispose();grid.material.dispose();}
 const b=bounds(),s=Math.ceil(Math.max(b.size[0],b.size[1],10)/10)*20;
 grid=new THREE.GridHelper(s,Math.round(s/10),0xb9c9d8,0xd2dde6);grid.rotation.x=Math.PI/2;
 grid.position.set((b.minimum[0]+b.maximum[0])/2,(b.minimum[1]+b.maximum[1])/2,b.minimum[2]-.1);scene.add(grid);
 makeTool();view();
}
function modelMaterial(){
 const b=bounds();
 if(depthColoring&&mode==='paths')return createDepthMaterial(THREE,b.minimum[2],b.maximum[2]);
 return new THREE.MeshStandardMaterial({color:0x6f98ba,metalness:.15,roughness:.55,side:THREE.DoubleSide,transparent:mode==='stock',opacity:mode==='stock'?.22:1,depthWrite:mode!=='stock'});
}
function applyModelAppearance(){
 for(const child of modelGroup.children){
  if(child.isMesh){child.material.dispose();child.material=modelMaterial();}
  if(child.userData.depthEdges)child.visible=depthColoring&&mode==='paths';
 }
 updateDepthLegend();
}
function updateDepthLegend(){
 const b=bounds(),scale=depthScale(b.minimum[2],b.maximum[2]);
 $('depthColors').checked=depthColoring;
 $('depthLegend').hidden=!data||!depthColoring||mode!=='paths'||!modelGroup.visible;
 $('depthScale').style.background=depthGradient();
 $('depthZero').textContent='0 mm';$('depthMiddle').textContent=fmt(scale.range_mm/2,2)+' mm';$('depthBottom').textContent=fmt(scale.range_mm,2)+' mm';
 $('depthReference').textContent='Topo Z '+fmt(scale.maximum_z,3)+' mm';
}
function setDepthColoring(enabled){
 depthColoring=enabled;
 try{localStorage.setItem('cam-depth-colors',String(enabled));}catch{}
 applyModelAppearance();
}
function makeTool(){
 clearGroup(toolGroup);if(!tool||!data)return;
 const length=tool.cutting_length_mm,r=tool.diameter_mm/2;
 const geo=new THREE.CylinderGeometry(r,r,length,32);geo.rotateX(Math.PI/2);geo.translate(0,0,length/2);
 toolGroup.add(new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:0xe1aa3f,metalness:.65,roughness:.3,transparent:true,opacity:.88})));
 const ring=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({length:65},(_,i)=>new THREE.Vector3(Math.cos(i/64*2*Math.PI)*r,Math.sin(i/64*2*Math.PI)*r,0))),new THREE.LineBasicMaterial({color:0x8d5815}));toolGroup.add(ring);
}
function displayToolSelect(){
 $('toolSelect').replaceChildren();if(tool){const o=new Option(tool.name+' · projeto','@project');$('toolSelect').add(o);}
 for(const t of tools)$('toolSelect').add(new Option(t.name,t.id));$('toolSelect').value=tool?'@project':tools[0]?.id;
 $('toolInfo').textContent=tool?`Ø ${fmt(tool.diameter_mm,3)} mm · corte ${fmt(tool.cutting_length_mm)} mm · topo reto`:'';
}
const fieldMap={stockTop:'stock_top_mm',stepdown:'stepdown_mm',angle:'raster_angle_deg',sampling:'sampling_mm',radial:'radial_allowance_mm',axial:'axial_allowance_mm',rampAngle:'entry_angle_deg',clearance:'clearance_mm'};
function smartModeEnabled(){return $('machiningMode').value==='smart';}
function roughBottom(){return smartModeEnabled()&&data?bounds().minimum[2]:number('stockTop')-number('bottom');}
function cutoutBottom(){return smartModeEnabled()&&data?numericValue($('smartStockBottom').value,'Fundo do bruto',{required:false,fallback:bounds().minimum[2]})-number('smartBreakthrough'):number('stockTop')-number('cutoutDepth');}
function drillBottom(){return number('stockTop')-number('drillDepth');}
function simulationBottom(){
 return activeStockBottom($('roughEnabled').checked,$('roughEnabled').checked?roughBottom():null,$('cutoutEnabled').checked,$('cutoutEnabled').checked?cutoutBottom():null,$('drillEnabled').checked,$('drillEnabled').checked?drillBottom():null);
}
function readStockSettings(){return {x0:number('stockX0'),y0:number('stockY0'),x1:number('stockX1'),y1:number('stockY1'),step:number('gridStep')};}
function currentSmartPlan(){return smartPlanPreview?.revision===revision?smartPlanPreview.report:motion?.smart_plan||null;}
function syncRegionVisibility(){
 const visible=$('showKeepout').checked;
 regionGroup.visible=visible;automaticRegionGroup.visible=visible&&automaticRegionGroup.children.length>0;
 $('automaticRegionLegend').hidden=!automaticRegionGroup.visible;
}
function renderAutomaticRegions(){
 const report=smartModeEnabled()?currentSmartPlan():null;
 const regions=report?.enabled?report.automatic_regions:null,z=Number($('stockTop').value)+.18;
 if(regions!==automaticRegionsSource||z!==automaticRegionsZ){
  clearGroup(automaticRegionGroup);automaticRegionsSource=regions;automaticRegionsZ=z;
  if(regions&&Number.isFinite(z)){const overlay=createAutomaticRegionOverlay(THREE,regions,z);if(overlay.children.length)automaticRegionGroup.add(overlay);}
 }
 syncRegionVisibility();
}
function automaticRegionsViewState(){
 let polygonCount=0;automaticRegionGroup.traverse(item=>{if(item.userData.automaticRegionOutline)polygonCount++;});
 return {visible:automaticRegionGroup.visible,legend_visible:!$('automaticRegionLegend').hidden,polygon_count:polygonCount};
}
function renderSmartPlan(){
 const smart=smartModeEnabled(),report=currentSmartPlan();
 $('smartModePanel').hidden=!smart;
 $('smartPlanSummary').dataset.state='';
 $('smartPlanSummary').textContent=smart&&report?.enabled?smartPlanText(report,value=>fmt(value,3)):'Confira o plano antes de calcular.';
 $('inspectSmartPlan').disabled=!data||smartPlanPending;
 if(smart){
  const policy=smartPolicyText(report);$('orderHint').textContent=policy.order;$('cutoutReuseHint').textContent=policy.reuse;
  $('regionNote').textContent=policy.regions+' Nenhuma região desenhada é necessária. Keep In / Keep Out limitam a área automática. Confira o plano para ver o envelope dos centros da fresa.';
 }
 renderAutomaticRegions();
}
function syncSmartOperationList(){
 const smart=smartModeEnabled();
 if(smart){
  const effective=operationListFromOptions(effectiveMachiningOptions({...operationOptionsFromList(operationList.getState()),machining_mode:'smart'}));
  operationList.setState(effective);$('roughEnabled').checked=true;$('cutoutEnabled').checked=true;$('operationOrder').value='roughing_then_cutout';
 }
 operationList.setLocked(smart);
 $('operationListHelp').textContent=smart?'Ordem automática: Drill (se ativo) → Rough → Cutout externo. Use Manual para reordenar ou desligar o Rough/Cutout.':'Marque as operações e arraste ⋮⋮ para mudar a ordem. Clique no nome para editar.';
 renderSmartPlan();
}
async function inspectSmartPlan(){
 if(smartPlanPending)throw Error('Aguarde a conferência do plano inteligente.');
 const atRevision=revision,payload=commandRequest({strict:true});smartPlanPending=true;$('inspectSmartPlan').disabled=true;
 $('smartPlanSummary').textContent='Conferindo bruto, ferramenta e ordem das operações…';
 try{
  const report=await api('/api/smart-plan',payload);
  if(atRevision!==revision)throw Error('A configuração mudou durante a conferência. Confira o plano novamente.');
  smartPlanPreview={revision,report};renderSmartPlan();return report;
 }catch(error){
  if(atRevision===revision){$('smartPlanSummary').dataset.state='error';$('smartPlanSummary').textContent=error.message;}
  throw error;
 }finally{smartPlanPending=false;$('inspectSmartPlan').disabled=!data;}
}
function updateHints(){
 const smart=smartModeEnabled();
 $('roughEntryHint').hidden=!smart;$('reviewCenterCutting').hidden=!smart;$('roughEntryHint').textContent=smart?smartEntryHint($('drillCenterCutting').checked):'';
 $('orderHint').textContent=smart?smartPolicyText(currentSmartPlan()).order:$('operationOrder').value==='cutout_then_roughing'?'Cutout primeiro: mantenha a peça presa após o recorte, para executar o desbaste.':'A simulação e o NC seguem a ordem selecionada.';
 try{$('cutHint').textContent=$('roughEnabled').checked?`Z final: ${fmt(roughBottom(),3)} mm · Stepover: ${fmt(number('stepover')/100*tool.diameter_mm,3)} mm entre passadas.`:'Desbaste desativado.';}catch{$('cutHint').textContent='Complete os parâmetros do desbaste.';}
 try{$('cutoutHint').textContent=$('cutoutEnabled').checked?`Z final: ${fmt(cutoutBottom(),3)} mm · ${smart?'descida limitada também pelo Stepdown do Rough.':Math.ceil(number('cutoutDepth')/number('cutoutStepdown'))+' camadas por contorno.'}`:'Cutout desativado.';}catch{$('cutoutHint').textContent='Complete os parâmetros do cutout.';}
 try{$('drillHint').textContent=$('drillEnabled').checked?`Z limite: ${fmt(drillBottom(),3)} mm · fresa Ø ${fmt(tool.diameter_mm,3)} mm · corte ${fmt(tool.cutting_length_mm)} mm.`:'Drill desativado. Você pode conferir os furos antes de ativar.';}catch{$('drillHint').textContent='Complete os parâmetros do Drill.';}
  $('cutoutContourHint').textContent=smart?'Inteligente: compara bolsões e recortes internos passantes. Miolos vantajosos são recortados antes do exterior; o Rough usina os demais detalhes. Confira a seleção no plano.':$('cutoutContours').value==='external'?'Somente o contorno externo: furos internos ficam fora do Cutout. Para recortá-los, escolha Internos + externo e uma fresa que caiba.':'Recorta os internos antes do externo. Se a fresa não couber em um interno, ajuste a ferramenta ou selecione somente o externo.';
 const canReuse=priorRoughingAvailable($('roughEnabled').checked,$('cutoutEnabled').checked,$('operationOrder').value,operationList.getState().order,$('drillEnabled').checked);
 $('cutoutReuseHint').textContent=smart?smartPolicyText(currentSmartPlan()).reuse:!canReuse?'Disponível quando Rough é a operação ativa imediatamente anterior ao Cutout. Na configuração atual, o recorte usa suas próprias camadas.':$('cutoutUsePriorRoughing').checked?'O Cutout aproveita áreas já removidas pelo Rough. Trechos ainda com material mantêm as camadas de corte.':'O Cutout usa suas próprias camadas, mesmo após o Rough.';
 renderSmartPlan();
}
function readOperations({strict=true}={}){
 const values={};for(const id of ['machiningMode','smartStockBottom','smartBreakthrough','smartSkin','operationOrder','roughingOrder','spindleRpm','roughEnabled','cutoutEnabled','drillEnabled','drillDepth','drillPeck','drillTolerance','drillFeed','drillAllowHelix','drillCenterCutting','drillCompensateFacets','cutoutDepth','cutoutStepdown','cutoutDirection','cutoutContours','cutoutUsePriorRoughing','roughFeed','cutoutFeed','plungeFeed','rapidFeed'])values[id]=$(id).type==='checkbox'?$(id).checked:$(id).value;
 values.operationSequence=operationList.getState().order;
 return readOperationValues(values,operations,tool,strict?number('stockTop'):numericValue($('stockTop').value,'Topo do bruto',{required:false,fallback:settings.stock_top_mm??0}),{strict});
}
function presetState(detail=false){return {selected_id:presetStore.selected_id,items:presetStore.presets.map(p=>detail?p:{id:p.id,name:p.name}),last_used_available:!!presetStore.last_used,saving:presetSaving,error:presetError||null};}
function renderPresets(){
 const select=$('presetSelect');select.replaceChildren(new Option('Últimos ajustes · automático',''));
 for(const p of presetStore.presets)select.add(new Option(p.name,p.id));select.value=presetStore.selected_id||'';
 $('presetTools').hidden=!presetStore.selected_id;
 $('presetStatus').dataset.error=String(!!presetError);
 $('presetStatus').textContent=presetError|| (presetSaving?'Salvando ajustes…':presetStore.last_used?'Ajustes salvos · restaurados ao reabrir.':'Avanços e ajustes serão lembrados automaticamente.');
}
function currentMachiningProfile(){return machiningProfile(tool,readSettings({strict:false}),readOperations({strict:false}));}
function storePreset(record){
 clearTimeout(presetTimer);presetTimer=null;presetSaving=true;presetError='';renderPresets();
 const operation=presetQueue.catch(()=>{}).then(()=>api('/api/presets',record));presetQueue=operation;
 return operation.then(saved=>{presetStore=saved;presetError='';return saved;}).catch(error=>{presetError='Ajustes não salvos: '+error.message;throw error;}).finally(()=>{presetSaving=false;renderPresets();});
}
async function rememberMachining(){
 if(!tool)return;clearTimeout(presetTimer);presetTimer=null;
 return storePreset({action:'remember',profile:currentMachiningProfile(),selected_id:presetStore.selected_id});
}
function scheduleRemember(){
 if(!token||!tool)return;clearTimeout(presetTimer);
 presetTimer=setTimeout(()=>rememberMachining().catch(error=>{presetError='Ajustes não salvos: '+error.message;renderPresets();}),400);
}
function applyMachiningProfile(profile){
 commandIdle();const stock=data?readStockSettings():null;
 const next=profilePatch(profile,data?readSettings({strict:false}):settings,data?readOperations({strict:false}):operations);
 tool=next.tool;settings=next.settings;operations=next.operations;
 fillFields();displayToolSelect();if(stock)for(const [id,key]of Object.entries({stockX0:'x0',stockY0:'y0',stockX1:'x1',stockY1:'y1',gridStep:'step'}))$(id).value=stock[key];
 if(data){makeTool();dirty('Preset aplicado. Confira a ferramenta e recalcule os percursos.');}
}
async function applyPreset(id){
 const p=presetStore.presets.find(p=>p.id===id);if(!p)throw Error('Escolha um preset salvo.');
 applyMachiningProfile(p.profile);presetStore.selected_id=id;await rememberMachining().catch(()=>{});return presetState(true);
}
async function savePreset(name,id=null){
 commandIdle();await storePreset({action:'save',name,profile:currentMachiningProfile(),...(id?{id}:{})});return presetState(true);
}
$('presetSelect').onchange=()=>{const id=$('presetSelect').value;if(id)applyPreset(id).catch(e=>toast(e.message,true));else{presetStore.selected_id=null;rememberMachining().catch(e=>toast(e.message,true));}};
$('savePreset').onclick=()=>{$('presetName').value='';$('presetDialog').showModal();$('presetName').focus();};
$('presetForm').onsubmit=async e=>{e.preventDefault();try{await savePreset($('presetName').value);$('presetDialog').close();toast('Preset salvo.');}catch(error){$('presetDialogError').textContent=error.message;}};
$('updatePreset').onclick=()=>{const p=presetStore.presets.find(p=>p.id===presetStore.selected_id);if(p)savePreset(p.name,p.id).then(()=>toast('Preset atualizado.')).catch(e=>toast(e.message,true));};
$('deletePreset').onclick=()=>storePreset({action:'delete',id:presetStore.selected_id}).catch(e=>toast(e.message,true));
function updateOperationControls(){
 const contourOption=[...($('cutoutContours').options||[])].find(option=>option.value==='external');
 if(contourOption)contourOption.textContent=smartModeEnabled()?'Automático · internos vantajosos + externo':'Soltar a peça · somente externo';
 const smart=smartModeEnabled();
 $('domainMode').disabled=smart||!$('roughEnabled').checked;
 $('domainHint').textContent=smart?'O modo inteligente define as áreas de Rough automaticamente.':$('domainMode').value==='silhouette'?'Peça já recortada: limita o Rough à silhueta da peça. Desenhe Keep In para selecionar os detalhes e Keep Out para proteger a fixação.':'Bruto retangular: a área permitida define onde o Rough pode remover material.';
 for(const id of ['bottom','stepdown','stepover','roughFeed','roughingOrder','strategy','angle','sampling','radial','axial','cleanup'])$(id).disabled=!$('roughEnabled').checked;
 for(const id of ['cutoutDepth','cutoutStepdown','cutoutFeed','cutoutDirection','cutoutContours'])$(id).disabled=!$('cutoutEnabled').checked;
 for(const id of ['drillDepth','drillPeck','drillTolerance','drillFeed','drillAllowHelix','drillCenterCutting','drillCompensateFacets'])$(id).disabled=!$('drillEnabled').checked;
 $('drillCenterCutting').disabled=!$('drillEnabled').checked&&!smart;
 $('cutoutUsePriorRoughing').disabled=!priorRoughingAvailable($('roughEnabled').checked,$('cutoutEnabled').checked,$('operationOrder').value,operationList.getState().order,$('drillEnabled').checked);
 if(smart)for(const id of ['bottom','cutoutDepth','cutoutContours','cutoutUsePriorRoughing'])$(id).disabled=true;
 for(const id of ['drawKeepout','drawBoundary','clearRegions','editWindows'])$(id).disabled=!$('roughEnabled').checked;
 regionPicker?.setDisabled(!$('roughEnabled').checked);
 if(!$('roughEnabled').checked&&drawMode)cancelDraw();
}
function fillFields(){
 operations={...operations,...cutoutPreferences(operations)};
 for(const [id,key]of Object.entries(fieldMap))$(id).value=settings[key]??0;
 $('bottom').value=settings.stock_top_mm-settings.bottom_mm;$('stepover').value=100*settings.stepover_mm/tool.diameter_mm;
 $('roughEnabled').checked=operations.roughing_enabled??true;$('cutoutEnabled').checked=operations.cutout_enabled??false;$('drillEnabled').checked=operations.drill_enabled??false;
 $('machiningMode').value=operations.machining_mode||'manual';
 $('smartStockBottom').value=operations.smart_stock_bottom_mm??'';$('smartBreakthrough').value=operations.smart_breakthrough_mm??0;$('smartSkin').value=operations.smart_skin_mm??'';
 const listState=operationListFromOptions(effectiveMachiningOptions(operations));operationList.setState(listState);syncSmartOperationList();
 $('operationOrder').value=operationOptionsFromList(listState).order;$('spindleRpm').value=operations.spindle_rpm??tool.spindle_rpm??'';
 $('roughingOrder').value=operations.roughing_order||'region_first';
 $('cutoutDepth').value=settings.stock_top_mm-(operations.cutout_bottom_mm??settings.bottom_mm);$('cutoutStepdown').value=operations.cutout_stepdown_mm??.635;
 $('drillDepth').value=settings.stock_top_mm-(operations.drill_bottom_mm??settings.bottom_mm);$('drillPeck').value=operations.drill_peck_mm??1;$('drillTolerance').value=operations.drill_tolerance_mm??.03;
 $('drillFeed').value=operations.drill_feed_mm_min??tool.feed_mm_min??'';$('drillAllowHelix').checked=operations.drill_allow_helix??false;$('drillCenterCutting').checked=operations.drill_center_cutting??false;
 $('drillCompensateFacets').checked=operations.drill_compensate_facets??false;
 $('drillInspection').replaceChildren();
 $('cutoutDirection').value=operations.cutout_direction||'climb';$('cutoutContours').value=smartModeEnabled()?'external':operations.cutout_contours;$('cutoutUsePriorRoughing').checked=smartModeEnabled()||operations.cutout_use_prior_roughing;
 $('roughFeed').value=operations.roughing_feed_mm_min??tool.feed_mm_min??'';$('cutoutFeed').value=operations.cutout_feed_mm_min??tool.feed_mm_min??'';
 $('plungeFeed').value=operations.plunge_mm_min??tool.plunge_mm_min??'';$('rapidFeed').value=operations.rapid_mm_min??3000;
 updateHints();updateOperationControls();
 $('strategy').value=settings.strategy;$('cleanup').checked=settings.cleanup_contours;
 $('domainMode').value=settings.domain_mode||'expanded';updateOperationControls();
 $('obstacleTop').value=settings.obstacle_top_mm??settings.stock_top_mm;
 $('units').value=placement.units;$('face').value='custom';$('xyOrigin').value=placement.xy_origin||'keep';$('zOrigin').value=placement.z_origin||'keep';
 if(placement.xy_origin==='minimum'&&placement.z_origin==='top')$('face').value=JSON.stringify(placement.rotation)===JSON.stringify(flip)?'flip':'normal';
 const b=bounds();$('stockX0').value=b.minimum[0]-5;$('stockY0').value=b.minimum[1]-5;$('stockX1').value=b.maximum[0]+5;$('stockY1').value=b.maximum[1]+5;
 $('gridStep').value=String(data?.stock?.step??.25);
 if(data?.stock)for(const[id,key]of Object.entries({stockX0:'x0',stockY0:'y0',stockX1:'x1',stockY1:'y1'}))$(id).value=data.stock[key];
}
function readSettings({strict=true}={}){
 const rough=strict&&$('roughEnabled').checked,s={...settings};
 const roughOnly=['stepdown','angle','sampling','radial','axial'];
 const minima={stepdown:Number.MIN_VALUE,sampling:Number.MIN_VALUE,radial:0,axial:0,clearance:Number.MIN_VALUE,rampAngle:Number.MIN_VALUE};
 for(const[id,key]of Object.entries(fieldMap))s[key]=numericValue($(id).value,$(id).parentElement.textContent.trim(),{required:roughOnly.includes(id)?rough:strict,fallback:settings[key],min:minima[id]??-Infinity,max:id==='rampAngle'?89.999:Infinity});
 const depth=numericValue($('bottom').value,'Profundidade total do desbaste',{required:rough&&!smartModeEnabled(),fallback:settings.stock_top_mm-settings.bottom_mm,min:Number.MIN_VALUE});
 s.bottom_mm=s.stock_top_mm-depth;
 s.stepover_mm=numericValue($('stepover').value,'Stepover do desbaste',{required:rough,fallback:100*settings.stepover_mm/tool.diameter_mm,min:Number.MIN_VALUE,max:100})/100*tool.diameter_mm;
 s.strategy=$('strategy').value;s.cleanup_contours=$('cleanup').checked;s.domain_mode=$('domainMode').value||settings.domain_mode||'expanded';s.region_mode='layer';s.compress_collinear=true;s.obstacle_top_mm=numericValue($('obstacleTop').value,'Altura máxima de obstáculos',{required:strict,fallback:settings.obstacle_top_mm??s.stock_top_mm});
 return s;
}
function regionsChanged(){renderRegions();regionList();dirty('Regiões alteradas. Recalcule antes de simular.');}
function polygonObject(p,color,fill=true){
 const shape=new THREE.Shape(p.map(q=>new THREE.Vector2(q[0],q[1])));
 if(fill){const mesh=new THREE.Mesh(new THREE.ShapeGeometry(shape),new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide,transparent:true,opacity:.12,depthWrite:false}));mesh.position.z=Number($('stockTop').value)+.12;regionGroup.add(mesh);}
 const line=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(p.map(q=>new THREE.Vector3(q[0],q[1],Number($('stockTop').value)+.15))),new THREE.LineBasicMaterial({color,transparent:true,opacity:.65}));regionGroup.add(line);
}
function renderRegions(){
 clearGroup(regionGroup);
 // Rasterized display mask only. Motor clipping remains exact Clipper2.
 // Union allowed areas first, then overlay all exclusions; overlapping allowed
 // windows never become protected merely because they overlap.
 const b=bounds(),x0=b.minimum[0]-5,y0=b.minimum[1]-5,x1=b.maximum[0]+5,y1=b.maximum[1]+5;
 const canvas=document.createElement('canvas');canvas.width=canvas.height=768;const ctx=canvas.getContext('2d');
 function paint(p){ctx.beginPath();p.forEach((q,i)=>{const x=(q[0]-x0)/(x1-x0)*768,y=(y1-q[1])/(y1-y0)*768;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fill();}
 const boundaries=smartModeEnabled()&&settings.boundaries_mm?.length===0?null:settings.boundaries_mm;
 if(boundaries!=null){ctx.fillStyle='rgba(200,86,105,0.16)';ctx.fillRect(0,0,768,768);ctx.globalCompositeOperation='destination-out';for(const p of boundaries)paint(p);ctx.globalCompositeOperation='source-over';}
 ctx.fillStyle='rgba(200,86,105,0.16)';for(const p of settings.exclusions_mm||[])paint(p);
 const texture=new THREE.CanvasTexture(canvas);const mask=new THREE.Mesh(new THREE.PlaneGeometry(x1-x0,y1-y0),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,side:THREE.DoubleSide}));mask.position.set((x0+x1)/2,(y0+y1)/2,Number($('stockTop').value)+.12);regionGroup.add(mask);
 if((settings.exclusions_mm||[]).length<=8)for(const p of settings.exclusions_mm||[])polygonObject(p,0xc76672,false);
 for(const p of settings.boundaries_mm||[])polygonObject(p,0x3c9b86,false);
 for(const b of windows||[])polygonObject(rect(...b),0x2d9f81,false);
 syncRegionVisibility();
}
function regionList(){
 const exclusions=settings.exclusions_mm||[],limits=settings.boundaries_mm,initial=isAutomaticStockBoundary(settings,bounds());
 $('regionList').textContent=`${exclusions.length} Keep Out · ${initial?'limite inicial do bruto':limits==null?'sem Keep In':limits.length+' Keep In'} · ${smartModeEnabled()?'Rough automático':'só Rough'}`;
 $('regionList').className='dim';$('editWindows').hidden=!windows;
 $('regionNote').textContent=smartModeEnabled()?smartPolicyText(currentSmartPlan()).regions+' Nenhuma região desenhada é necessária. Keep In / Keep Out limitam a área automática. Confira o plano para ver o envelope dos centros da fresa.':windows?'Keep In e Keep Out valem só para o Rough. As duas janelas do exemplo são estimadas pelo NC; os limites originais do MeshCAM não são conhecidos.':initial?'Só para o Rough: a área inicial acompanha o bruto. Desenhar Keep In substitui essa área; Keep Out protege o que você desenhar. O Cutout segue os contornos da peça.':'Só para o Rough: Keep In permite usinar dentro; várias Keep In somam áreas. Keep Out protege a área. O motor considera o raio inteiro da fresa. O Cutout segue os contornos da peça.';
 $('polygonList').replaceChildren();
 for(const[key,title]of [['exclusions_mm','Keep Out'],['boundaries_mm',initial?'Área inicial do bruto':'Keep In']])for(let i=0;i<(settings[key]||[]).length;i++){
  const row=document.createElement('div');row.className='region-item';const text=document.createElement('span');text.textContent=title+' '+(i+1)+' · '+settings[key][i].length+' pontos';
  const remove=document.createElement('button');remove.textContent='Excluir';remove.setAttribute('aria-label',`Excluir ${title.toLowerCase()} ${i+1}`);remove.onclick=()=>{settings[key].splice(i,1);windows=null;regionsChanged();};row.append(text,remove);$('polygonList').append(row);
 }
}
function displayPaths(){
 clearGroup(pathGroup);clearGroup(rapidGroup);if(!motion)return;
 const normal=[],cutout=[],drill=[],ramps=[],rapid=[];
 for(const m of motion.moves){const target=['travel','retract','clearance_adjust'].includes(m[0])?rapid:(m[8]==='drill'?drill:['ramp','ramp_return','plunge'].includes(m[0])?ramps:(m[8]==='cutout'?cutout:normal));target.push(...m.slice(1,7));}
 for(const[positions,color,group]of [[normal,0x239681,pathGroup],[cutout,0x307ac0,pathGroup],[drill,0x9050c0,pathGroup],[ramps,0xca9b3d,pathGroup],[rapid,0x94a6b8,rapidGroup]]){
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));group.add(new THREE.LineSegments(g,new THREE.LineBasicMaterial({color,transparent:true,opacity:.72})));
 }
 pathGroup.visible=$('showPaths').checked;rapidGroup.visible=$('showRapids').checked;
}
function setMotion(value,projectId=null,quietStock=false){
 stop();motion=value;feedClock=null;cursor=0;
 computedProject=projectId;$('exportNC').disabled=!motion?.moves.some(m=>m[0]==='cut')||!computedProject||exportBusy;
 const rough=motion?.operations?.roughing;
 $('regionScheduleInfo').textContent=rough?.path_order==='region_first'?`${rough.regions} região(ões) · ${rough.stay_down_entries} reentrada(s) sem retração completa`:(rough?'Sequência por camadas em todas as regiões.':'');
 if(motion?.timing?.available&&motion.moves.length)feedClock=new FeedClock(motion.moves,motion.durations_s);
 $('timeline').max=feedClock?.duration||1;$('timeline').value=0;
 $('moveCount').textContent=motion?fmt(motion.moves.length,0):'—';
 $('layerCount').textContent=motion?Object.entries(motion.operations||{}).map(([k,v])=>({roughing:'R ',drill:'D ',cutout:'C '}[k]||k+' ')+(v.depth_passes??v.holes?.length??0)).join(' · '):'—';
 for(const id of ['play','finish','restart','timeline'])$(id).disabled=!feedClock;
 displayPaths();updateCursor();resetStock(!quietStock);renderSmartPlan();
}
function dirty(reason='Configuração alterada. Recalcule os percursos.',quietStock=false){
 scheduleRemember();
 clearCutoutRecovery();
 $('drillInspection').replaceChildren();
 if(!busy)clearCalculationProgress();else showCalculationProgress({status:'running'},true);
 revision++;setMotion(null,null,quietStock);$('planState').textContent='Recalcular';$('planState').className='pill stale';$('calcStatus').textContent=reason;
}
function updateCursor(){
 const state=feedClock?.at(cursor),index=state?.index||0;
 $('timeline').value=cursor;$('progressLabel').textContent=`${timeLabel(cursor)} / ${timeLabel(feedClock?.duration)}`;
 const m=motion?.moves[Math.min(index,motion.moves.length-1)];
 const p=state?.position||motion?.initial||[bounds().minimum[0],bounds().minimum[1],Number($('stockTop').value)||0];
 toolGroup.position.set(...p);$('tipPosition').textContent=`X ${fmt(p[0])} · Y ${fmt(p[1])} · Z ${fmt(p[2])}`;
 const kinds={cut:'Corte',ramp:'Rampa',ramp_return:'Retorno da rampa',plunge:'Mergulho',travel:'Travessia',retract:'Retração',approach:'Aproximação',cleared_feed:'Entrada',link_backtrack:'Retorno',link_cleared:'Ligação em área removida'};
 $('moveInfo').textContent=m?`${({cutout:'Cutout',drill:'Drill',roughing:'Roughing'})[m[8]]||'Roughing'} · ${kinds[m[0]]||m[0]} · F ${fmt(motion.feeds_mm_min?.[Math.min(index,motion.moves.length-1)]||0,0)}`:'Início do percurso';
 stockWanted=state?.stockIndex||0;
 showStockSurface();
}
function resetStock(reportErrors=true){
 stockSampleSnapshot=null;stockGeneration++;
 if(!data||!tool){stockReady=false;return;}stockBusy=true;stockReady=false;stockWanted=0;stockApplied=-1;stockLastSent=0;$('stockStatus').textContent='REMOÇÃO · ATUALIZANDO';
 cancelSolid();solidFailedIndex=null;solidIndex=-1;solidGeneration=-1;$('surfaceStatus').textContent='Prévia em grade';
 if(solidMesh){scene.remove(solidMesh);solidMesh.geometry.dispose();solidMesh.material.dispose();solidMesh=null;}
 if(stockMesh)stockMesh.visible=false;if(stockWire)stockWire.visible=false;
 $('volume').textContent='—';$('protectedCount').textContent='—';$('stockSummary').textContent='Atualizando grade…';
 try{
  const config={...readStockSettings(),top:number('stockTop'),bottom:simulationBottom(),cutoutUseRegions:false,diameter:tool.diameter_mm,boundaries:smartModeEnabled()&&settings.boundaries_mm?.length===0?null:settings.boundaries_mm,exclusions:settings.exclusions_mm};
  stockConfig=config;
  worker.postMessage({type:'init',generation:stockGeneration,config,moves:motion?.moves||[]});
 }catch(e){stockBusy=false;$('stockStatus').textContent='GRADE INDISPONÍVEL';$('stockSummary').textContent=e.message;if(stockMesh)stockMesh.visible=false;if(stockWire)stockWire.visible=false;if(reportErrors)toast(e.message,true);}
}
function requestStock(){if(!stockReady)return;if(stockWanted!==stockApplied)$('stockStatus').textContent='REMOÇÃO · ATUALIZANDO';if(stockWanted===stockApplied){scheduleSolid();return;}if(stockBusy||!data)return;stockBusy=true;stockLastSent=performance.now();worker.postMessage({type:'seek',generation:stockGeneration,target:stockWanted});}
worker.onmessage=({data:s})=>{
 if(s.generation!==stockGeneration)return;stockBusy=false;
 if(s.type==='error'){stockSampleSnapshot=null;stockReady=false;$('stockStatus').textContent='GRADE INDISPONÍVEL';$('stockSummary').textContent=s.error;if(stockMesh)stockMesh.visible=false;if(stockWire)stockWire.visible=false;toast(s.error,true);return;}
 if(s.type!=='stock')return;
 stockApplied=s.index;stockReady=true;
 stockSampleSnapshot=s;
 if(!stockMesh||stockMesh.userData.nx!==s.nx||stockMesh.userData.ny!==s.ny){
  if(stockMesh){scene.remove(stockMesh);stockMesh.geometry.dispose();stockMesh.material.dispose();}
  const g=new THREE.BufferGeometry(),positions=new Float32Array(s.heights.length*3);
  for(let j=0;j<s.ny;j++)for(let i=0;i<s.nx;i++){const n=j*s.nx+i;positions[n*3]=s.config.x0+(i+.5)*s.dx;positions[n*3+1]=s.config.y0+(j+.5)*s.dy;}
  g.setAttribute('position',new THREE.BufferAttribute(positions,3));g.setIndex(stockGridIndices(s.nx,s.ny));
  stockMesh=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:0xc9b388,roughness:.85,side:THREE.DoubleSide}));stockMesh.userData={nx:s.nx,ny:s.ny};scene.add(stockMesh);
 }
 const position=stockMesh.geometry.getAttribute('position');
 for(let j=0;j<s.ny;j++)for(let i=0;i<s.nx;i++){const n=j*s.nx+i;position.array[n*3]=s.config.x0+(i+.5)*s.dx;position.array[n*3+1]=s.config.y0+(j+.5)*s.dy;position.array[n*3+2]=s.heights[n];}
 position.needsUpdate=true;stockMesh.geometry.computeVertexNormals();
 const normals=stockMesh.geometry.getAttribute('normal');smoothWallNormals(normals.array,s.nx,s.ny);normals.needsUpdate=true;
 stockMesh.geometry.computeBoundingSphere();stockMesh.visible=mode==='stock';
 if(stockWire){scene.remove(stockWire);stockWire.geometry.dispose();stockWire.material.dispose();}
 const box=new THREE.Box3(new THREE.Vector3(s.config.x0,s.config.y0,s.config.bottom),new THREE.Vector3(s.config.x1,s.config.y1,s.config.top));stockWire=new THREE.Box3Helper(box,0x9e8d72);stockWire.visible=mode==='stock';scene.add(stockWire);
 $('volume').textContent=fmt(s.volume,1)+' mm³';$('protectedCount').textContent=fmt(s.protectedCount,0);$('protectedCount').style.color=s.protectedCount?'#bd4f53':'';
 $('stockSummary').textContent=`Grade ${s.nx} × ${s.ny} · fundo Z ${fmt(s.config.bottom,3)} mm`;
 if(stockWanted!==s.index)requestStock();else $('stockStatus').textContent='REMOÇÃO NA GRADE';
 showStockSurface();scheduleSolid();
};
function setMode(next){mode=next;$('pathMode').classList.toggle('active',mode==='paths');$('stockMode').classList.toggle('active',mode==='stock');showStockSurface();scheduleSolid();modelGroup.visible=mode==='paths';pathGroup.visible=mode==='paths';$('showModel').checked=mode==='paths';$('showPaths').checked=mode==='paths';applyModelAppearance();view();}
function updateWorkspaceAvailability(){
 const ready=!!data;
 document.body.classList.toggle('workspace-empty',!ready);
 $('emptyScene').hidden=ready;
 $('placementDock').hidden=!ready;
 $('saveProject').disabled=!ready||busy||exportBusy;
 $('calculate').disabled=!ready||busy;
 for(const id of ['applyPlacement','inspectDrill','resetStock','stockMode'])$(id).disabled=!ready;
 $('toolSelect').disabled=!tool;$('editTool').disabled=!tool;
}
function adopt(sceneData){
 resetOriginReference();
 clearCutoutRecovery();cancelDraw();
 smartPlanPreview=null;manualOperationState=null;manualCutoutPreferences=null;
 if(!busy)clearCalculationProgress();
 cancelDraw();data=sceneData;tool=sceneData.tool||tools[0];settings=structuredClone(sceneData.settings||{});operations=structuredClone(sceneData.operations||{});placement=structuredClone(sceneData.placement);windows=sceneData.windows||null;revision++;
 $('partName').textContent=data.name;$('workspaceTitle').textContent=data.name;$('dimensions').textContent=data.mesh.bounds_mm.size.map(v=>fmt(v)).join(' × ')+' mm · '+fmt(data.mesh.triangle_count,0)+' triângulos';
 $('feedProvenance').textContent=sceneData.isDemo?'Peça geométrica de demonstração. Avanços e RPM são exemplos para simular; ajuste à ferramenta e ao material reais.':'';
 fillFields();displayToolSelect();setModel(data.triangles);renderRegions();regionList();setMotion(data.motion,data.project_id);
 $('sceneTag').textContent=sceneData.isDemo?'EXEMPLO · PLACA COM BOLSÃO':sceneData.approximate_regions?'REGIÕES APROXIMADAS':'PROJETO LOCAL';$('notice').textContent=sceneData.approximate_regions?'Regiões aproximadas · confira seus limites':'Motor experimental · sem conexão com máquina';
 $('planState').textContent=motion?'Percurso validado pelo motor':'Calcular percurso';$('planState').className='pill';$('calcStatus').textContent=motion?'Percurso carregado pronto para reprodução.':'Confira os parâmetros e calcule os percursos.';$('loadingScene').hidden=true;
 updateWorkspaceAvailability();syncPlacementUi();scheduleRemember();
}
function request(){if(!data)throw Error('Abra um STL primeiro.');settings=readSettings();operations=readOperations();return {asset:data.asset,placement,tool,settings,operations,notes:data.notes||'Projeto preparado pela interface local.',ui:{windows,stock:readStockSettings(),approximate_regions:!!data.approximate_regions}};}
function sceneForNewMesh(inspected,currentSettings,currentOperations){
 const state=importedMachiningState(inspected.mesh,currentSettings,currentOperations,tool?.diameter_mm);
 state.stock.step=Number($('gridStep').value)||.25;
 return {...inspected,...state,tool,notes:'STL preparado pela interface local. Área permitida inicial acompanha o bruto. Regiões anteriores removidas ao trocar o modelo ou posicionamento.'};
}
async function loadDemo(){stop();$('loadingScene').hidden=false;try{adopt(await api('/api/demo'));}finally{$('loadingScene').hidden=true;}}
$('demo').onclick=()=>loadDemo().catch(e=>toast(e.message,true));
$('openStl').onclick=()=>$('stlFile').click();
$('emptyOpenStl').onclick=()=>$('stlFile').click();
$('emptyOpenProject').onclick=()=>$('projectFile').click();
$('emptyDemo').onclick=()=>loadDemo().catch(e=>toast(e.message,true));
$('stlFile').onchange=async()=>{
 const file=$('stlFile').files[0];if(!file)return;
 try{
  const currentSettings=readSettings({strict:false}),currentOperations=readOperations({strict:false});
  const asset=await api('/api/upload?name='+encodeURIComponent(file.name),file,true);
  const p={units:$('units').value||'mm',rotation:$('face').value==='custom'?(placement.rotation||identity):($('face').value==='flip'?flip:identity),translation_mm:[0,0,0],xy_origin:$('xyOrigin').value||'minimum',z_origin:$('zOrigin').value||'top'};
  const sceneData=await api('/api/inspect',{asset:asset.asset,placement:p});
  adopt(sceneForNewMesh(sceneData,currentSettings,currentOperations));toast('STL aberto. Avanços e ajustes preservados; profundidades e área permitida ajustadas ao bruto do novo modelo.');
 }catch(e){toast(e.message,true);}finally{$('stlFile').value='';}
};
function placementUiState(detail=false){
 const result={panel:placementPanelTab,enabled:!!data&&!busy&&!exportBusy&&!placementUiBusy,
  undo_available:!!placementUndo&&placementUndo.revision===revision,origin:placementOrigin(data?.mesh.bounds_mm),
  reference:{picking:originPicking,picker_hides_panel:originPicking&&$('placementPanel').hidden,point_mm:originReference,contours:originOutline?.polygons_mm.length||0}};
 if(detail){
  const frame=$('viewport').getBoundingClientRect(),dock=$('placementDock').getBoundingClientRect();
  result.layout={in_viewport:!!data&&dock.left>=frame.left&&dock.right<=frame.right&&dock.top>=frame.top&&dock.bottom<=frame.bottom,
   panel_scrolls:$('placementPanel').scrollHeight>$('placementPanel').clientHeight};
 }
 return result;
}
function syncPlacementUi(){
 const state=placementUiState(),open=!!data&&!!placementPanelTab&&!originPicking;
 $('placementDock').hidden=!data;$('placementPanel').hidden=!open;
 $('placementDock').setAttribute('aria-busy',String(placementUiBusy));
 $('calculate').disabled=!data||busy||placementUiBusy;
 $('saveProject').disabled=!data||busy||exportBusy||placementUiBusy;
 for(const button of $('placementDock').querySelectorAll('button'))button.disabled=!state.enabled;
 $('closePlacement').disabled=false;$('undoPlacement').disabled=!state.enabled||!state.undo_available;
 for(const button of $('placementDock').querySelectorAll('[data-placement-panel]'))button.setAttribute('aria-expanded',String(open&&button.dataset.placementPanel===placementPanelTab));
 for(const content of $('placementDock').querySelectorAll('[data-placement-content]'))content.hidden=content.dataset.placementContent!==placementPanelTab;
 $('placementTitle').textContent={rotate:'Girar / segunda face',origin:'Zero da peça · G54',move:'Mover a peça'}[placementPanelTab]||'Posicionar peça';
 for(const button of $('placementDock').querySelectorAll('[data-placement-xy]'))button.setAttribute('aria-pressed',String(!!state.origin.xy&&button.dataset.placementXy===state.origin.xy.join(',')));
 for(const button of $('placementDock').querySelectorAll('[data-placement-z]'))button.setAttribute('aria-pressed',String(button.dataset.placementZ===state.origin.z));
 const xy=$('placementDock').querySelector('[data-placement-xy][aria-pressed="true"]');
 $('placementOriginLabel').textContent=`XY: ${xy?.title||'personalizada'} · Z: ${{top:'topo',center:'meio',bottom:'base'}[state.origin.z]||'personalizada'}`;
 $('placementDimensions').textContent=data?bounds().size.map(v=>fmt(v,2)).join(' × ')+' mm':'';
 placementGizmo.visible=!!data&&mode==='paths';placementBox.visible=open;
 if(data){
  placementGizmo.scale.setScalar(Math.max(2,Math.min(15,Math.max(...bounds().size)*.12)));
  placementBox.box.min.fromArray(bounds().minimum);placementBox.box.max.fromArray(bounds().maximum);
 }
}
function setPlacementPanel(panel){
 if(panel!==null&&!['rotate','origin','move'].includes(panel))throw Error('Painel de posicionamento inválido.');
 if(panel!==null){commandIdle();if(!data)throw Error('Abra um STL primeiro.');stop();if(mode!=='paths')setMode('paths');cancelDraw();}
 if(panel!=='origin')cancelOriginPick();
 placementPanelTab=panel;syncPlacementUi();
}
function placementSnapshot(){
 return {scene:{...data,tool:structuredClone(tool),settings:structuredClone(readSettings({strict:false})),
  operations:structuredClone(readOperations({strict:false})),placement:structuredClone(placement),
  windows:structuredClone(windows),stock:readStockSettings(),motion,project_id:computedProject},
  camera:{position:camera.position.toArray(),target:controls.target.toArray(),zoom:camera.zoom}};
}
function restorePlacementCamera(frame,recenter=false){
 if(recenter){
  const target=bounds().minimum.map((v,i)=>(v+bounds().maximum[i])/2);
  camera.position.fromArray(frame.position.map((v,i)=>v-frame.target[i]+target[i]));controls.target.fromArray(target);
 }else{camera.position.fromArray(frame.position);controls.target.fromArray(frame.target);}
 camera.zoom=frame.zoom;camera.updateProjectionMatrix();controls.update();
}
async function applyPlacementCandidate(candidate,{frameShift=false,secondSide=null}={}){
 commandIdle();if(!data)throw Error('Abra um STL primeiro.');
 if(candidate.xy_origin==='keep'&&candidate.z_origin==='keep'&&samePlacement(candidate,placement,data.mesh))return false;
 const saved=placementSnapshot(),atRevision=revision;placementUiBusy=true;syncPlacementUi();stop();
 try{
  const inspected=await api('/api/inspect',{asset:data.asset,placement:candidate});
  if(revision!==atRevision||busy||exportBusy)throw Error('A configuração mudou durante o posicionamento. Tente novamente.');
  const delta=candidate.translation_mm.map((v,i)=>v-saved.scene.mesh.transform.translation_mm[i]);
  let next=frameShift?shiftWorkFrame(saved.scene,inspected,delta):sceneForNewMesh(inspected,saved.scene.settings,saved.scene.operations);
  if(secondSide)next=secondSideState(next,secondSide);
  adopt(next);
  if(frameShift)restorePlacementCamera({...saved.camera,position:saved.camera.position.map((v,i)=>v+delta[i]),target:saved.camera.target.map((v,i)=>v+delta[i])});
  else restorePlacementCamera(saved.camera);
  placementUndo={...saved,revision};
  for(const axis of ['X','Y','Z'])$('placementDelta'+axis).value='0';
  toast(frameShift?'Zero redefinido. Regiões, fixação e profundidades preservadas; recalcule os percursos.':secondSide?'Segunda face: apenas Rough, sem Cutout, com a fixação central protegida. Escolha o zero na borda.':'Posição aplicada. Regiões limpas; use Desfazer posição para recuperá-las.');return true;
 }finally{placementUiBusy=false;syncPlacementUi();}
}
async function runPlacementAction(action){
 commandIdle();if(!data)throw Error('Abra um STL primeiro.');
 return applyPlacementCandidate(placementAction(placement,data.mesh,data.triangles,action),{frameShift:action.kind.startsWith('origin_')});
}
async function prepareSecondSide(axis='x',fixture){
 if(!['x','y'].includes(axis))throw Error('Escolha X ou Y para virar a peça.');
 commandIdle();if(!data)throw Error('Abra um STL primeiro.');
 secondSideState({settings,operations,mesh:data.mesh},fixture);
 const candidate=placementAction(placement,data.mesh,data.triangles,{kind:'rotate',axis,turns:2});
 await applyPlacementCandidate(candidate,{secondSide:fixture});selectOperationTab('rough');setPlacementPanel('origin');return commandState();
}
function cancelOriginPick(){
 const wasPicking=originPicking;originPicking=false;originRequest++;controls.enabled=!drawMode;
 clearGroup(originEdges);if(originReference)previewOriginPoint(originReference);else originPreview.visible=false;
 document.body.classList.remove('picking-origin');$('originPickHelp').hidden=true;
 $('pickOriginEdge').textContent='Selecionar borda no modelo';
 if(wasPicking)syncPlacementUi();
}
function resetOriginReference(){
 cancelOriginPick();originOutline=null;originReference=null;clearGroup(originPreview);
 $('originPointX').value=$('originPointY').value=$('originPointZ').value='0';
}
async function ensureOriginOutline(){
 if(originOutline)return originOutline;
 commandIdle();if(!data)throw Error('Abra um STL primeiro.');
 const atRevision=revision,outline=await api('/api/datum-outline',{asset:data.asset,placement});
 if(revision!==atRevision)throw Error('A peça mudou durante a leitura da borda. Selecione novamente.');
 originOutline=outline;return outline;
}
function previewOriginPoint(point){
 if(!originPreview.children.length){
  const radius=Math.max(.4,Math.max(...bounds().size)*.016),z=0;
  const line=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([
   new THREE.Vector3(-radius,0,z),new THREE.Vector3(radius,0,z),new THREE.Vector3(0,-radius,z),new THREE.Vector3(0,radius,z)]),
   new THREE.LineBasicMaterial({color:0xe58b18,depthTest:false,depthWrite:false}));
  line.renderOrder=1002;originPreview.add(line);
 }
 originPreview.position.set(point[0],point[1],bounds().maximum[2]+.1);originPreview.visible=true;
}
function selectOriginPoint(point){
 if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite))throw Error('Informe X e Y finitos em mm.');
 originReference=[...point];$('originPointX').value=point[0];$('originPointY').value=point[1];
 previewOriginPoint(point);cancelOriginPick();syncPlacementUi();return {point_mm:[...point]};
}
async function referenceOrigin(point,snap=true){
 commandIdle();if(!data)throw Error('Abra um STL primeiro.');
 const hit=snap?nearestOutlinePoint(point,(await ensureOriginOutline()).polygons_mm):{point_mm:point};
 return {...selectOriginPoint(hit.point_mm),...(snap?{distance_mm:hit.distance_mm}:{} )};
}
async function beginOriginPick(){
 setPlacementPanel('origin');cancelDraw();const ticket=++originRequest;
 const outline=await ensureOriginOutline();if(ticket!==originRequest)return placementUiState();commandIdle();
 view('top');controls.enabled=false;originPicking=true;
 document.body.classList.add('picking-origin');$('originPickHelp').hidden=false;$('pickOriginEdge').textContent='Cancelar seleção';
 clearGroup(originEdges);
 for(const polygon of outline.polygons_mm){
  const line=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(polygon.map(p=>new THREE.Vector3(...p,outline.z_top_mm+.05))),
   new THREE.LineBasicMaterial({color:0x08a2c8,depthTest:false,depthWrite:false}));line.renderOrder=1001;originEdges.add(line);
 }
 syncPlacementUi();
 return placementUiState();
}
function originHit(event){
 const point=worldPoint(event);if(!point||!originOutline)return null;
 const hit=nearestOutlinePoint([point.x,point.y],originOutline.polygons_mm);
 return hit.distance_mm<=unitsPerPixel()*14?hit:null;
}
$('pickOriginEdge').onclick=()=>{if(originPicking)cancelOriginPick();else beginOriginPick().catch(error=>toast(error.message,true));};
$('applyOriginXY').onclick=()=>{try{placementClick({kind:'origin_point',axes:'xy',point_mm:[number('originPointX'),number('originPointY'),0]});}catch(error){toast(error.message,true);}};
$('applyOriginZ').onclick=()=>{try{placementClick({kind:'origin_point',axes:'z',point_mm:[0,0,number('originPointZ')]});}catch(error){toast(error.message,true);}};
$('prepareSecondSide').onclick=()=>{try{prepareSecondSide($('secondSideAxis').value,{diameter_mm:number('secondSideDiameter'),height_mm:number('secondSideHeight')}).catch(error=>toast(error.message,true));}catch(error){toast(error.message,true);}};
renderer.domElement.addEventListener('pointermove',event=>{
 if(!originPicking)return;const hit=originHit(event);
 if(hit)previewOriginPoint(hit.point_mm);else originPreview.visible=false;
});
renderer.domElement.addEventListener('pointerdown',event=>{
 if(!originPicking||event.button!==0)return;event.preventDefault();
 const hit=originHit(event);if(hit)selectOriginPoint(hit.point_mm);else toast('Clique próximo da borda azul para escolher o zero.');
});
renderer.domElement.addEventListener('pointercancel',cancelOriginPick);
function undoPlacement(){
 commandIdle();if(!placementUndo||placementUndo.revision!==revision)throw Error('Nenhuma mudança de posição disponível para desfazer.');
 const saved=placementUndo;placementUndo=null;adopt(saved.scene);restorePlacementCamera(saved.camera);syncPlacementUi();
 toast('Posição e regiões anteriores recuperadas.');
}
const placementClick=action=>runPlacementAction(action).catch(error=>toast(error.message,true));
for(const button of $('placementDock').querySelectorAll('[data-placement-panel]'))button.onclick=()=>{
 try{setPlacementPanel(placementPanelTab===button.dataset.placementPanel?null:button.dataset.placementPanel);}catch(error){toast(error.message,true);}
};
for(const button of $('placementDock').querySelectorAll('[data-placement-rotate]'))button.onclick=()=>placementClick({kind:'rotate',axis:button.dataset.placementRotate,turns:Number(button.dataset.turns)});
for(const button of $('placementDock').querySelectorAll('[data-placement-xy]'))button.onclick=()=>placementClick({kind:'origin_xy',anchor:button.dataset.placementXy.split(',').map(Number)});
for(const button of $('placementDock').querySelectorAll('[data-placement-z]'))button.onclick=()=>placementClick({kind:'origin_z',anchor:button.dataset.placementZ});
$('closePlacement').onclick=()=>setPlacementPanel(null);
$('flipPlacement').onclick=()=>placementClick({kind:'flip'});$('resetPlacement').onclick=()=>placementClick({kind:'reset'});
$('movePlacement').onclick=()=>{
 try{placementClick({kind:'translate',delta_mm:['X','Y','Z'].map(axis=>numericValue($('placementDelta'+axis).value,'Deslocamento '+axis))});}catch(error){toast(error.message,true);}
};
$('undoPlacement').onclick=()=>{try{undoPlacement();}catch(error){toast(error.message,true);}};
$('applyPlacement').onclick=async()=>{
 try{
  const custom=$('face').value==='custom';
  await applyPlacementCandidate({units:$('units').value,rotation:custom?placement.rotation:($('face').value==='flip'?flip:identity),
   xy_origin:$('xyOrigin').value,z_origin:$('zOrigin').value,
   translation_mm:custom&&$('xyOrigin').value==='keep'&&$('zOrigin').value==='keep'?placement.translation_mm:[0,0,0]});
 }catch(error){toast(error.message,true);}
};
document.addEventListener('keydown',event=>{if(event.key==='Escape'){if(originPicking){event.preventDefault();cancelOriginPick();}else if(placementPanelTab)setPlacementPanel(null);}});
new MutationObserver(syncPlacementUi).observe($('calculate'),{attributes:true,attributeFilter:['aria-busy']});
new MutationObserver(syncPlacementUi).observe($('exportNC'),{attributes:true,attributeFilter:['disabled']});
const operationList=createOperationList($('operationList'),{
 onChange:state=>{
  const next=operationOptionsFromList(state);$('operationOrder').value=next.order;
  $('roughEnabled').checked=next.roughing_enabled;$('cutoutEnabled').checked=next.cutout_enabled;
  $('drillEnabled').checked=next.drill_enabled;
  const none=!next.roughing_enabled&&!next.cutout_enabled&&!next.drill_enabled;
  updateOperationControls();updateHints();dirty(none?'Nenhuma operação ativa. Marque Rough, Drill ou Cutout na lista.':'Operações alteradas. Recalcule para aplicar a ativação e a ordem.',none);
 },
 onSelect:id=>selectOperationTab(id==='roughing'?'rough':id),
 announce:text=>$('operationListStatus').textContent=text
});
$('machiningMode').onchange=()=>{
 if(smartModeEnabled()){
  manualOperationState=operationList.getState();manualCutoutPreferences={contours:$('cutoutContours').value,reuse:$('cutoutUsePriorRoughing').checked};
  $('cutoutContours').value='external';$('cutoutUsePriorRoughing').checked=true;
 }else{
  if(manualOperationState){operationList.setState(manualOperationState);$('operationOrder').value=operationOptionsFromList(manualOperationState).order;manualOperationState=null;}
  if(manualCutoutPreferences){$('cutoutContours').value=manualCutoutPreferences.contours;$('cutoutUsePriorRoughing').checked=manualCutoutPreferences.reuse;manualCutoutPreferences=null;}
 }
 syncSmartOperationList();updateOperationControls();regionList();dirty(smartModeEnabled()?'Modo inteligente ativo. Confira o plano ou calcule Rough e Cutout juntos.':'Modo manual ativo. Confira as operações e calcule novamente.');updateHints();
};
$('inspectSmartPlan').onclick=()=>inspectSmartPlan().catch(error=>toast(error.message,true));
$('reviewCenterCutting').onclick=()=>{selectOperationTab('rough');$('drillCenterCutting').focus({preventScroll:false});};
for(const id of [...Object.keys(fieldMap),'smartStockBottom','smartBreakthrough','smartSkin','bottom','stepover','strategy','domainMode','cleanup','obstacleTop','cutoutDepth','cutoutStepdown','cutoutDirection','cutoutContours','cutoutUsePriorRoughing','drillDepth','drillPeck','drillTolerance','drillFeed','drillAllowHelix','drillCenterCutting','drillCompensateFacets','roughFeed','cutoutFeed','plungeFeed','rapidFeed','spindleRpm','roughingOrder']){
 $(id).addEventListener('change',()=>{updateOperationControls();updateHints();dirty();if(id==='stockTop')renderRegions();});
 if($(id).type==='number')$(id).addEventListener('input',()=>{
  updateHints();
  // Invalidate immediately, including while an older calculation is running.
  // An incomplete number during typing is not an error to toast.
  if(motion||computedProject)dirty(undefined,true);else revision++;
  renderSmartPlan();scheduleRemember();
 });
}
$('toolSelect').onchange=()=>{if($('toolSelect').value==='@project')return;tool=structuredClone(tools.find(t=>t.id===$('toolSelect').value));$('drillCenterCutting').checked=false;displayToolSelect();makeTool();updateHints();dirty('Ferramenta alterada. Recalcule os percursos.');};
async function inspectDrill(){
 const rev=revision;$('inspectDrill').disabled=true;$('drillInspection').textContent='Analisando furos circulares…';
 try{
  const report=await api('/api/drill-inspect',commandRequest());
  if(rev!==revision)throw Error('Configuração alterada durante a inspeção. Confira os furos novamente.');
  $('drillInspection').replaceChildren();
  const holes=report.holes||[],heading=document.createElement('p');heading.className='hint';
  heading.textContent=holes.length?`${holes.length} furo(s) circular(es) detectado(s) · ${holes.filter(h=>h.compatible).length} compatível(is).`:'Nenhum furo circular vertical reconhecido nesta configuração.';
  $('drillInspection').append(heading);
  for(const hole of holes){
   const row=document.createElement('div');row.className='drill-hole '+(hole.compatible?'is-compatible':'is-skipped');
   const title=document.createElement('strong'),text=document.createElement('span'),detail=document.createElement('small');
   title.textContent=`Furo ${hole.id} · Ø ${fmt(hole.diameter_mm,3)} mm`;
   text.textContent=`X ${fmt(hole.center[0],3)} · Y ${fmt(hole.center[1],3)} · Ø útil ${fmt(hole.safe_diameter_mm,3)} mm`;
   if(hole.fit_basis==='nominal')text.textContent+=` · Ø usinado ${fmt(hole.machining_diameter_mm,3)} mm · Ajuste STL ${fmt(hole.facet_allowance_mm,5)} mm radial`;
   detail.textContent=hole.compatible?`${hole.method==='helix'?'Hélice':'Mergulhos'} · ${hole.through?'passante':'cego'}`:(hole.reason||'Furo incompatível com os parâmetros atuais.');
   row.append(title,text,detail);$('drillInspection').append(row);
  }
  return report;
 }catch(error){$('drillInspection').textContent=error.message;throw error;}
 finally{$('inspectDrill').disabled=false;}
}
$('inspectDrill').onclick=()=>inspectDrill().catch(error=>toast(error.message,true));
function fillTool(t){for(const[id,key]of Object.entries({toolId:'id',toolName:'name',toolDiameter:'diameter_mm',toolLength:'cutting_length_mm',toolOverall:'overall_length_mm',toolFeed:'feed_mm_min',toolPlunge:'plunge_mm_min',toolRpm:'spindle_rpm',toolFlutes:'flutes',toolNotes:'notes'}))$(id).value=t[key]??'';$('toolError').textContent='';}
$('editTool').onclick=()=>{fillTool(tool||{});$('toolDialog').showModal();};
$('newTool').onclick=()=>fillTool({id:'topo-'+Date.now(),name:'Nova fresa de topo reto',diameter_mm:3.175,cutting_length_mm:22});
$('toolForm').onsubmit=async e=>{e.preventDefault();try{
 const t={...tool,id:$('toolId').value,name:$('toolName').value,kind:'flat_end_mill',diameter_mm:number('toolDiameter'),cutting_length_mm:number('toolLength'),overall_length_mm:number('toolOverall',true),feed_mm_min:number('toolFeed',true),plunge_mm_min:number('toolPlunge',true),spindle_rpm:number('toolRpm',true),flutes:number('toolFlutes',true),notes:$('toolNotes').value};
 const saved=await api('/api/tools',{tool:t,replace:tools.some(old=>old.id===t.id)});tools=saved.tools;if(JSON.stringify(t)!==JSON.stringify(tool))$('drillCenterCutting').checked=false;tool=t;displayToolSelect();makeTool();updateHints();dirty('Ferramenta salva. Recalcule os percursos.');$('toolDialog').close();toast('Ferramenta salva na biblioteca local.');
 }catch(e){$('toolError').textContent=e.message;}};
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
$('cancelCalculation').onclick=cancelCalculation;
async function startCalculation(strict=false){
 if(busy){if(strict)throw Error('Já há um cálculo em andamento.');return;}let failureContext=null;clearCutoutRecovery();cancelDraw();try{
  const payload=request(),atRevision=revision;
  failureContext={revision:atRevision,operations:payload.operations};
  validateTimingFeeds(payload.operations,payload.tool);busy=true;startCalculationProgress();$('calculate').disabled=true;$('calculate').setAttribute('aria-busy','true');$('calcStatus').textContent='Preparando o cálculo…';stop();cancelSolid();
  await rememberMachining().catch(()=>{});
  const started=performance.now();
  const task=await api('/api/calculate',payload);
  if(!task.job)throw Error('O serviço local não informou o identificador do cálculo.');
  setCalculationJob(task.job);
  lastCalculationJob=task.job;
  let pollingErrors=0;
  const poll=async()=>{
   try{
    let state;
    try{state=await api('/api/jobs/'+task.job);pollingErrors=0;}
    catch(e){if(++pollingErrors>4)throw e;$('calcStatus').textContent='Reconectando ao serviço local… O cálculo continua em andamento.';setTimeout(poll,1500);return;}
    const processing=state.status==='running'&&state.worker_alive===true&&state.heartbeat_s>=15?' · Processando esta passada…':'';
    $('calcStatus').textContent=(revision!==atRevision?'Configuração anterior · ':'')+jobStatusText(state,(performance.now()-started)/1000)+processing;
    if(state.status==='running'){showCalculationProgress(state,revision!==atRevision);setTimeout(poll,700);return;}
    busy=false;$('calculate').disabled=false;$('calculate').setAttribute('aria-busy','false');
    if(state.status==='cancelled'){
     showCalculationProgress(state,revision!==atRevision);
     const message=motion&&computedProject&&revision===atRevision?'Cálculo cancelado. O percurso anterior continua disponível.':'Cálculo cancelado. Você pode ajustar a configuração e calcular novamente.';
     $('calcStatus').textContent=message;toast(message);scheduleSolid();return;
    }
    if(state.status==='failed')throw Error(state.error||'O motor não concluiu o cálculo.');
    if(state.status!=='complete'||!state.motion)throw Error('O serviço local devolveu um resultado de cálculo incompleto.');
    if(revision!==atRevision){showCalculationProgress(state,true);toast('O cálculo terminou, mas a configuração mudou. Recalcule para usar os novos valores.');$('calcStatus').textContent='Resultado anterior salvo; configuração atual precisa de novo cálculo.';return;}
    setMotion(state.motion,state.project_id);showCalculationProgress(state);const summary=calculationSummary(state.motion);$('calcStatus').textContent=summary;$('planState').textContent='Percurso validado pelo motor';$('planState').className='pill';toast(summary);
   }catch(e){busy=false;showCalculationProgress({status:'failed',phase:e.message});$('calculate').disabled=false;$('calculate').setAttribute('aria-busy','false');presentCalculationError(e.message,failureContext);$('calcStatus').textContent='Cálculo interrompido: '+e.message;scheduleSolid();}
  };poll();return task;
 }catch(e){if(busy)showCalculationProgress({status:'failed',phase:e.message});busy=false;$('calculate').disabled=!data;$('calculate').setAttribute('aria-busy','false');presentCalculationError(e.message,failureContext);$('calcStatus').textContent=e.message;scheduleSolid();if(strict)throw e;}
}
$('cutoutRecoveryApply').onclick=()=>applyCutoutRecovery().catch(error=>toast(error.message,true));
$('calculate').onclick=()=>startCalculation();
$('exportNC').onclick=async()=>{
 if(!computedProject||exportBusy)return;const atRevision=revision,id=computedProject;exportBusy=true;$('exportNC').disabled=true;
 $('calcStatus').textContent='Validando operações e relendo o NC gerado…';
 try{const result=await api('/api/export',{project_id:id});
  if(revision!==atRevision){toast('Exportação da configuração anterior salva. Recalcule para exportar os valores atuais.');return;}
  const a=document.createElement('a');a.href='/api/nc/'+result.export_id;a.download=result.filename;a.click();
  $('calcStatus').textContent='NC exportado · releitura conferida · GRBL mm / G54';toast('NC experimental exportado. Confira zero G54, ferramenta e fixação antes do uso.');
 }catch(e){toast(e.message,true);$('calcStatus').textContent='Exportação interrompida: '+e.message;}
 finally{exportBusy=false;$('exportNC').disabled=!motion?.moves.some(m=>m[0]==='cut')||!computedProject;}
};
$('saveProject').onclick=async()=>{try{const saved=await api('/api/save',request());const a=document.createElement('a');a.href='/api/download/'+saved.project_id;a.download='projeto-cam-local.zip';a.click();toast('Projeto salvo em disco e ZIP preparado. Inclui STL, ferramenta e regiões.');}catch(e){toast(e.message,true);}};
$('openProject').onclick=()=>$('projectFile').click();
$('projectFile').onchange=async()=>{const f=$('projectFile').files[0];if(!f)return;try{adopt(await api('/api/import-project',f,true));toast('Projeto aberto. Recalcule para gerar os percursos desta sessão.');}catch(e){toast(e.message,true);}finally{$('projectFile').value='';}};
$('editWindows').onclick=()=>{
 $('windowInputs').replaceChildren();(windows||[]).forEach((b,i)=>{const title=document.createElement('h3');title.textContent='Janela '+(i+1);$('windowInputs').append(title);const fields=document.createElement('div');fields.className='fields';b.forEach((v,j)=>{const label=document.createElement('label');label.textContent=['X mínimo','Y mínimo','X máximo','Y máximo'][j];const input=document.createElement('input');input.type='number';input.step='.01';input.value=v;input.id=`window${i}_${j}`;label.append(input);fields.append(label);});$('windowInputs').append(fields);});$('windowError').textContent='';$('windowDialog').showModal();
};
$('applyWindows').onclick=()=>{try{const next=windows.map((b,i)=>b.map((v,j)=>number(`window${i}_${j}`)));if(next.some(b=>b[2]<=b[0]||b[3]<=b[1]))throw Error('O máximo precisa ficar acima do mínimo.');windows=next;settings.boundaries_mm=next.map(b=>rect(...b));settings.exclusions_mm=[];regionsChanged();$('windowDialog').close();}catch(e){$('windowError').textContent=e.message;}};
$('clearRegions').onclick=()=>{settings.boundaries_mm=null;settings.exclusions_mm=[];windows=null;regionsChanged();};
const plane=new THREE.Plane(new THREE.Vector3(0,0,1),0),ray=new THREE.Raycaster();
function worldPoint(e){const r=renderer.domElement.getBoundingClientRect();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);plane.constant=-Number($('stockTop').value);const p=new THREE.Vector3();return ray.ray.intersectPlane(plane,p)?p:null;}
const drawHelpText=document.createElement('span'),finishRegionButton=document.createElement('button'),cancelRegionButton=document.createElement('button');
finishRegionButton.id='finishRegionDrawing';finishRegionButton.textContent='Fechar polígono';
cancelRegionButton.id='cancelRegionDrawing';cancelRegionButton.textContent='Cancelar';
$('drawHelp').replaceChildren(drawHelpText,finishRegionButton,cancelRegionButton);
function clearPreview(){if(preview){scene.remove(preview);preview.geometry.dispose();preview.material.dispose();preview=null;}}
function cancelDraw(){
 regionPicker?.close();
 const pointer=drawingPointer;drawingPointer=null;drawMode=null;drawShape=null;dragStart=null;draftPoints=[];
 if(pointer!=null&&renderer.domElement.hasPointerCapture(pointer))renderer.domElement.releasePointerCapture(pointer);
 controls.enabled=true;document.body.classList.remove('drawing');$('drawHelp').hidden=true;clearPreview();
}
function previewPoints(points,closed=true){
 clearPreview();if(points.length<2)return;
 const geometry=new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(p[0],p[1],Number($('stockTop').value)+.3)));
 const material=new THREE.LineBasicMaterial({color:drawMode==='keepout'?0xd66372:0x239681});
 preview=closed?new THREE.LineLoop(geometry,material):new THREE.Line(geometry,material);scene.add(preview);
}
function unitsPerPixel(){return (camera.top-camera.bottom)/(renderer.domElement.getBoundingClientRect().height*camera.zoom);}
function updateDrawHelp(){
 const label=drawMode==='keepout'?'Keep Out':'Keep In';
 const hint=drawShape==='polygon'?'clique nos vértices · feche no primeiro ponto, com duplo clique ou Enter · Backspace desfaz':drawShape==='freehand'?'segure e desenhe o contorno; solte para fechar':drawShape==='circle'?'arraste do centro até o raio':'arraste entre dois cantos';
 drawHelpText.textContent=`${label} · ${SHAPE_NAMES[drawShape]} · ${hint} · Esc cancela`;
 finishRegionButton.hidden=drawShape!=='polygon';finishRegionButton.disabled=draftPoints.length<3;
}
function beginDraw(kind,shape){
 if(!data||!$('roughEnabled').checked)return;
 if(!['keepout','boundary'].includes(kind)||!Object.keys(SHAPE_NAMES).includes(shape))throw Error('Tipo ou forma de região inválidos.');
 cancelOriginPick();cancelDraw();stop();drawMode=kind;drawShape=shape;view('top');controls.enabled=false;
 document.body.classList.add('drawing');$('drawHelp').hidden=false;updateDrawHelp();
}
function showRegionDialog(shape,kind,points,start,end){
 pendingRegionShape=shape;$('regionType').value=kind;$('regionShapeName').textContent=SHAPE_NAMES[shape]+' · somente no Rough';
 $('regionRectFields').hidden=shape!=='rectangle';$('regionRoundFields').hidden=!['circle','ellipse'].includes(shape);
 $('regionPolygonFields').hidden=!['polygon','freehand'].includes(shape);
 if(shape==='rectangle'){
  const box=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];
  ['regionX0','regionY0','regionX1','regionY1'].forEach((id,i)=>$(id).value=box[i].toFixed(3));
 }else if(shape==='circle'||shape==='ellipse'){
  const center=shape==='circle'?start:[(start[0]+end[0])/2,(start[1]+end[1])/2];
  const rx=shape==='circle'?Math.hypot(end[0]-start[0],end[1]-start[1]):Math.abs(end[0]-start[0])/2;
  const ry=shape==='circle'?rx:Math.abs(end[1]-start[1])/2;
  ['regionCenterX','regionCenterY','regionRadiusX','regionRadiusY'].forEach((id,i)=>$(id).value=[...center,rx,ry][i].toFixed(3));
  $('regionRadiusLabel').textContent=shape==='circle'?'Raio':'Raio X';$('regionRadiusYLabel').hidden=shape==='circle';
 }else $('regionVertices').value=points.map(p=>p.map(v=>v.toFixed(4)).join(' ')).join('\n');
 $('regionError').textContent='';$('regionDialog').showModal();
}
function finishRegionDrawing(){
 if(drawShape!=='polygon')return;
 try{const points=validateRegionPolygon(draftPoints),kind=drawMode;cancelDraw();showRegionDialog('polygon',kind,points);}
 catch(error){toast(error.message,true);}
}
finishRegionButton.onclick=finishRegionDrawing;cancelRegionButton.onclick=cancelDraw;
regionPicker=createRegionPicker($('regionShapePicker'),{onChoose:(shape,kind)=>beginDraw(kind,shape)});
function openRegionPicker(kind){
 if(!data||!$('roughEnabled').checked)throw Error('Ative o Rough para desenhar Keep In ou Keep Out.');
 if(!['keepout','boundary'].includes(kind))throw Error('Tipo de região inválido.');
 if(drawMode)cancelDraw();stop();
 return regionPicker.show(kind,$(kind==='keepout'?'drawKeepout':'drawBoundary'));
}
$('drawKeepout').onclick=()=>openRegionPicker('keepout');$('drawBoundary').onclick=()=>openRegionPicker('boundary');
renderer.domElement.addEventListener('pointerdown',e=>{
 if(!drawMode||e.button!==0)return;e.preventDefault();const p=worldPoint(e);if(!p)return;const point=[p.x,p.y];
 if(drawShape==='polygon'){
  if(draftPoints.length>=3&&Math.hypot(point[0]-draftPoints[0][0],point[1]-draftPoints[0][1])<8*unitsPerPixel()){finishRegionDrawing();return;}
  if(draftPoints.length&&Math.hypot(point[0]-draftPoints.at(-1)[0],point[1]-draftPoints.at(-1)[1])<2*unitsPerPixel())return;
  if(draftPoints.length>=MAX_REGION_VERTICES){toast('Limite de vértices atingido. Feche o polígono ou desfaça pontos.',true);return;}
  draftPoints.push(point);previewPoints(draftPoints);updateDrawHelp();return;
 }
 dragStart=point;draftPoints=[point];drawingPointer=e.pointerId;renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener('pointermove',e=>{
 if(!drawMode)return;const p=worldPoint(e);if(!p)return;const point=[p.x,p.y];
 if(drawShape==='polygon'){if(draftPoints.length)previewPoints([...draftPoints,point]);return;}
 if(!dragStart||e.pointerId!==drawingPointer)return;
 if(drawShape==='freehand'){
  if(Math.hypot(point[0]-draftPoints.at(-1)[0],point[1]-draftPoints.at(-1)[1])>=2*unitsPerPixel()){
   if(draftPoints.length>=4096){cancelDraw();toast('Traço muito longo. Desenhe um contorno mais simples.',true);return;}
   draftPoints.push(point);
  }
  previewPoints(draftPoints);return;
 }
 try{
  if(drawShape==='rectangle')previewPoints(rectanglePolygon(dragStart,point));
  else if(drawShape==='circle')previewPoints(roundPolygon(dragStart,Math.hypot(point[0]-dragStart[0],point[1]-dragStart[1]),undefined,drawMode));
  else previewPoints(roundPolygon([(dragStart[0]+point[0])/2,(dragStart[1]+point[1])/2],Math.abs(point[0]-dragStart[0])/2,Math.abs(point[1]-dragStart[1])/2,drawMode));
 }catch{previewPoints([dragStart,point],false);}
});
renderer.domElement.addEventListener('pointerup',e=>{
 if(!dragStart||e.pointerId!==drawingPointer)return;
 const p=worldPoint(e),start=[...dragStart],kind=drawMode,shape=drawShape,raw=draftPoints.map(p=>[...p]);
 cancelDraw();if(!p)return;const end=[p.x,p.y];
 try{
  const points=shape==='freehand'?freehandPolygon([...raw,end]):shape==='rectangle'?rectanglePolygon(start,end):shape==='circle'?roundPolygon(start,Math.hypot(end[0]-start[0],end[1]-start[1]),undefined,kind):roundPolygon([(start[0]+end[0])/2,(start[1]+end[1])/2],Math.abs(end[0]-start[0])/2,Math.abs(end[1]-start[1])/2,kind);
  showRegionDialog(shape,kind,points,start,end);
 }catch(error){toast(error.message,true);}
});
renderer.domElement.addEventListener('dblclick',e=>{if(drawShape==='polygon'){e.preventDefault();finishRegionDrawing();}});
renderer.domElement.addEventListener('pointercancel',cancelDraw);
document.addEventListener('keydown',e=>{
 if(!drawMode)return;
 if(e.key==='Escape'){e.preventDefault();cancelDraw();}
 else if(drawShape==='polygon'&&e.key==='Enter'){e.preventDefault();finishRegionDrawing();}
 else if(drawShape==='polygon'&&e.key==='Backspace'){e.preventDefault();draftPoints.pop();previewPoints(draftPoints);updateDrawHelp();}
});
$('applyRegion').onclick=()=>{
 try{
  const kind=$('regionType').value;let polygon;
  if(pendingRegionShape==='rectangle'){const b=['regionX0','regionY0','regionX1','regionY1'].map(id=>number(id));if(b[2]<=b[0]||b[3]<=b[1])throw Error('O máximo deve ficar acima do mínimo.');polygon=rectanglePolygon(b.slice(0,2),b.slice(2));}
  else if(['circle','ellipse'].includes(pendingRegionShape))polygon=roundPolygon([number('regionCenterX'),number('regionCenterY')],number('regionRadiusX'),pendingRegionShape==='circle'?number('regionRadiusX'):number('regionRadiusY'),kind);
  else polygon=parseRegionVertices($('regionVertices').value);
  settings=addRoughingRegion(settings,kind,polygon,bounds());windows=null;regionsChanged();$('regionDialog').close();
 }catch(e){$('regionError').textContent=e.message;}
};
function selectOperationTab(name){
 if(name!=='rough')cancelDraw();
 operationList.select(name==='rough'?'roughing':name);
 for(const tab of ['rough','drill','cutout']){const active=name===tab;$(tab+'Panel').hidden=!active;$(tab+'Tab').classList.toggle('active',active);$(tab+'Tab').setAttribute('aria-selected',String(active));$(tab+'Tab').tabIndex=active?0:-1;}
}
const operationTabs=['rough','drill','cutout'];
for(const name of operationTabs){
 $(name+'Tab').onclick=()=>selectOperationTab(name);
 $(name+'Tab').onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const index=operationTabs.indexOf(name),next=e.key==='Home'?operationTabs[0]:e.key==='End'?operationTabs.at(-1):operationTabs[(index+(e.key==='ArrowLeft'?-1:1)+operationTabs.length)%operationTabs.length];selectOperationTab(next);$(next+'Tab').focus();}};
}
$('isoView').onclick=()=>{cancelDraw();view('iso');};$('topView').onclick=()=>{cancelDraw();view('top');};$('frontView').onclick=()=>{cancelDraw();view('front');};$('fitView').onclick=()=>{cancelDraw();view();};
$('zoomIn').onclick=()=>{camera.zoom=Math.min(100,camera.zoom*1.5);camera.updateProjectionMatrix();};
$('zoomOut').onclick=()=>{camera.zoom=Math.max(.05,camera.zoom/1.5);camera.updateProjectionMatrix();};
$('pathMode').onclick=()=>setMode('paths');$('stockMode').onclick=()=>setMode('stock');
$('showModel').onchange=()=>{modelGroup.visible=$('showModel').checked;updateDepthLegend();};$('showPaths').onchange=()=>pathGroup.visible=$('showPaths').checked;$('showRapids').onchange=()=>rapidGroup.visible=$('showRapids').checked;$('showKeepout').onchange=syncRegionVisibility;
$('depthColors').onchange=()=>setDepthColoring($('depthColors').checked);
$('play').onclick=()=>{if(!feedClock)return;if(cursor>=feedClock.duration)cursor=0;lastTime=performance.now();playing=!playing;if(playing)cancelSolid();$('play').textContent=playing?'Ⅱ Pausar':'▶ Reproduzir';$('play').setAttribute('aria-label',playing?'Pausar':'Reproduzir');$('play').setAttribute('aria-pressed',String(playing));if(!playing)requestStock();};
$('restart').onclick=()=>{stop();cancelSolid();cursor=0;updateCursor();requestStock();};$('finish').onclick=()=>{stop();cancelSolid();cursor=feedClock?.duration||0;updateCursor();requestStock();};
$('timeline').oninput=()=>{stop();cancelSolid();cursor=Number($('timeline').value);updateCursor();requestStock();};
$('resetStock').onclick=()=>{stop();cursor=0;updateCursor();resetStock();};
function animate(time){requestAnimationFrame(animate);const dt=Math.max(0,(time-lastTime)/1000||0);lastTime=time;if(playing&&feedClock){cursor=Math.min(feedClock.duration,cursor+Number($('speed').value)*dt);updateCursor();if(cursor>=feedClock.duration){stop();requestStock();}}if(stockWanted>=0&&!stockBusy&&time-stockLastSent>150&&playing)requestStock();controls.update();renderer.render(scene,camera);}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
requestAnimationFrame(animate);
// Command actions operate on the same state and functions as the visible app.
function commandState(detail=false){
 const s=tool?readSettings({strict:false}):{},o=tool?readOperations({strict:false}):{};
 const regions={keepin:(s.boundaries_mm||[]).map((p,index)=>({index,vertices:p.length})),keepout:(s.exclusions_mm||[]).map((p,index)=>({index,vertices:p.length}))};
 if(!detail){delete s.boundaries_mm;delete s.exclusions_mm;}
 return {model:data?{name:data.name,asset:data.asset,...data.mesh}:null,tool,settings:s,operations:o,operation_list:operationList.getState(),placement,
  workspace:{empty:!data,empty_visible:!$('emptyScene').hidden,can_calculate:!$('calculate').disabled,can_save:!$('saveProject').disabled},
  placement_ui:placementUiState(detail),presets:presetState(detail),
  stock:data?readStockSettings():null,regions,notes:data?.notes||'',revision,smart_plan:smartPlanForState(currentSmartPlan(),detail),
  regions_ui:{picker:regionPicker?.state(),drawing:drawMode?{kind:drawMode==='boundary'?'keepin':'keepout',shape:drawShape,vertices:draftPoints.length}:null},
  feedback:{cutout_recovery:cutoutRecovery?{action:cutoutRecovery.action,label:cutoutRecovery.label,message:cutoutRecovery.message}:null},
  calculation:{busy,active_job:activeCalculationJob,last_job:lastCalculationJob,computed_project:computedProject,status:$('calcStatus').textContent},
  view:{mode,tab:operationTabs.find(name=>!$(name+'Panel').hidden),zoom:camera.zoom,position:camera.position.toArray(),target:controls.target.toArray(),depth_coloring:depthColoring,depth_scale:data?depthScale(bounds().minimum[2],bounds().maximum[2]):null,automatic_regions:automaticRegionsViewState(),
   layers:{model:modelGroup.visible,paths:pathGroup.visible,rapids:rapidGroup.visible,regions:regionGroup.visible}},
  simulation:{playing,speed:Number($('speed').value),time_s:cursor,duration_s:feedClock?.duration||0,
   moves:motion?.moves.length||0,position:toolGroup.position.toArray(),stock_ready:stockReady,stock_busy:stockBusy,
   stock_applied:stockApplied,stock_target:stockWanted,solid_busy:solidBusy,solid_ready:!!solidMesh&&solidIndex===stockWanted&&solidGeneration===stockGeneration,
   surface:$('surfaceStatus').textContent,removed_volume:$('volume').textContent,protected_cells:$('protectedCount').textContent}};
}
function commandObject(value,label){if(!value||typeof value!=='object'||Array.isArray(value))throw Error(label+': informe um objeto.');return value;}
function commandNumber(value,label,min=-Infinity,max=Infinity){if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max)throw Error(label+': número fora do intervalo.');return value;}
function commandVector(value,label,n=3){if(!Array.isArray(value)||value.length!==n)throw Error(label+': vetor inválido.');return value.map(v=>commandNumber(v,label));}
function commandIdle(){if(busy||exportBusy||placementUiBusy)throw Error('Aguarde ou cancele o cálculo/exportação ou posicionamento antes de alterar o projeto.');}
function commandRequest({strict=false}={}){if(!data)throw Error('Abra um STL primeiro.');return {asset:data.asset,placement,tool,settings:readSettings({strict}),operations:readOperations({strict}),notes:data.notes||'',ui:{windows,stock:readStockSettings(),approximate_regions:!!data.approximate_regions}};}
async function patchCommandConfig(command){
 commandIdle();const atRevision=revision,next=commandRequest();
 for(const key of ['settings','operations','tool'])if(command[key]!==undefined){
  const patch=commandObject(command[key],key);next[key]=key==='operations'?mergeOperationOptions(next[key],patch):{...next[key],...patch};
 }
 if(command.tool!==undefined&&JSON.stringify(next.tool)!==JSON.stringify(tool)&&command.operations?.drill_center_cutting===undefined)next.operations.drill_center_cutting=false;
 if(command.settings?.region_mode!==undefined&&command.settings.region_mode!=='layer')throw Error('A interface usa region_mode=layer.');
 if(command.settings?.compress_collinear!==undefined&&command.settings.compress_collinear!==true)throw Error('A interface usa compress_collinear=true.');
 if(command.stock!==undefined)next.ui.stock={...next.ui.stock,...commandObject(command.stock,'stock')};
 if(command.notes!==undefined){if(typeof command.notes!=='string')throw Error('notes deve ser texto.');next.notes=command.notes;}
 // Validate the candidate before changing any live values or invalidating motion.
 const valid=await api('/api/validate-config',next);
 if(revision!==atRevision||busy||exportBusy)throw Error('A configuração mudou durante a validação. Tente novamente.');
 settings=valid.settings;operations=valid.operations;tool=valid.tool;data.stock=valid.ui.stock;data.notes=next.notes;
 windows=null;fillFields();displayToolSelect();makeTool();renderRegions();regionList();dirty();
 await rememberMachining().catch(()=>{});
 return commandState();
}
async function executeCommand(command){
 commandObject(command,'Comando');const action=command.action;
 if(action==='state')return commandState(!!command.detail);
 if(action==='tools.list')return {tools,selected:tool?.id||null};
 if(action==='presets.list')return presetState(true);
 if(action==='presets.save')return savePreset(command.name,command.id);
 if(action==='presets.apply'){commandIdle();return applyPreset(command.id);}
 if(action==='presets.delete'){commandIdle();await storePreset({action:'delete',id:command.id});return presetState(true);}
 if(action==='presets.remember'){await rememberMachining();return presetState();}
 if(action==='drill.inspect')return inspectDrill();
 if(action==='machining.plan')return inspectSmartPlan();
 if(action==='cutout.recovery.apply')return applyCutoutRecovery();
 if(action==='regions.cancel'){cancelDraw();return commandState();}
 if(action==='regions.picker'||action==='regions.draw'){
  commandIdle();if(!['keepin','keepout'].includes(command.kind))throw Error('kind deve ser keepin ou keepout.');
  const kind=command.kind==='keepin'?'boundary':'keepout';
  if(action==='regions.picker')openRegionPicker(kind);
  else{
   if(!data||!$('roughEnabled').checked)throw Error('Ative o Rough para desenhar regiões.');
   if(!regionPicker.state().open||regionPicker.state().kind!==kind)openRegionPicker(kind);
   regionPicker.choose(command.shape);
  }
  return commandState();
 }
 if(action==='operations.set'){
  commandIdle();const patch={};for(const key of ['order','enabled'])if(command[key]!==undefined)patch[key]=command[key];
  if(smartModeEnabled())validateSmartOperationPatch(patch);
  operationList.setState(patch,{notify:true});return commandState();
 }
 if(action==='config.patch')return patchCommandConfig(command);
 if(action==='demo.open'){commandIdle();await loadDemo();return commandState();}
 if(action==='stl.open'){
  commandIdle();const oldSettings=readSettings({strict:false}),oldOperations=readOperations({strict:false});
  const inspected=await api('/api/inspect',{asset:command.asset,placement:command.placement||{units:'mm',rotation:identity,xy_origin:'minimum',z_origin:'top'}});
  adopt(sceneForNewMesh(inspected,oldSettings,oldOperations));return commandState();
 }
 if(action==='project.adopt'){commandIdle();adopt(command.scene);return commandState();}
 if(action==='placement.set'){
  commandIdle();if(!data)throw Error('Abra um STL primeiro.');
  const p={...placement,...commandObject(command.placement,'placement')};
  const inspected=await api('/api/inspect',{asset:data.asset,placement:p});
  adopt(sceneForNewMesh(inspected,readSettings({strict:false}),readOperations({strict:false})));return commandState();
 }
 if(action==='placement.panel'){setPlacementPanel(command.panel??null);return commandState();}
 if(action==='placement.outline')return ensureOriginOutline();
 if(action==='placement.pick'){
  if(command.enabled!==undefined&&typeof command.enabled!=='boolean')throw Error('enabled deve ser booleano.');
  if(command.enabled===false){cancelOriginPick();return placementUiState();}return beginOriginPick();
 }
 if(action==='placement.reference'){
  if(command.snap!==undefined&&typeof command.snap!=='boolean')throw Error('snap deve ser booleano.');
  return referenceOrigin(commandVector(command.point_mm,'point_mm',2),command.snap??true);
 }
 if(action==='placement.second_side')return prepareSecondSide(command.axis??'x',command.fixture);
 if(action==='placement.action'){await runPlacementAction(command);return commandState();}
 if(action==='placement.undo'){undoPlacement();return commandState();}
 if(action==='tool.set'||action==='tool.save'){
  commandIdle();const chosen=command.tool||tools.find(t=>t.id===command.id);if(!chosen)throw Error('Ferramenta não encontrada.');
  const candidate={...tool,...chosen};const next={...commandRequest(),tool:candidate};
  next.operations.drill_center_cutting=false;
  const valid=await api('/api/validate-config',next);
  if(action==='tool.save'){const saved=await api('/api/tools',{tool:valid.tool,replace:command.replace===true});tools=saved.tools;}
  return patchCommandConfig({tool:valid.tool,operations:{drill_center_cutting:false}});
 }
 if(action==='regions.add'){
  commandIdle();if(!data)throw Error('Abra um STL primeiro.');
  if(!['keepin','keepout'].includes(command.kind))throw Error('kind deve ser keepin ou keepout.');
  const kind=command.kind==='keepin'?'boundary':'keepout';let polygon;
  if(command.shape==='rectangle')polygon=rectanglePolygon(commandVector(command.min,'min',2),commandVector(command.max,'max',2));
  else if(['circle','ellipse'].includes(command.shape)){
   const rx=commandNumber(command.shape==='circle'?command.radius:command.radius_x,'radius',.05),ry=command.shape==='circle'?rx:commandNumber(command.radius_y,'radius_y',.05);
   polygon=roundPolygon(commandVector(command.center,'center',2),rx,ry,kind);
  }
  else if(command.shape==='polygon')polygon=validateRegionPolygon(command.points);
  else if(command.shape==='freehand')polygon=freehandPolygon(command.points,command.tolerance_mm??.05);
  else throw Error('shape: rectangle, circle, ellipse, polygon ou freehand.');
  settings=addRoughingRegion(readSettings({strict:false}),kind,polygon,bounds());windows=null;regionsChanged();return commandState();
 }
 if(action==='regions.remove'||action==='regions.clear'){
  commandIdle();if(!data)throw Error('Abra um STL primeiro.');
  const kinds=command.kind==='all'&&action==='regions.clear'?['keepin','keepout']:[command.kind];
  if(kinds.some(k=>!['keepin','keepout'].includes(k)))throw Error('kind deve ser keepin, keepout ou all para limpar.');
  if(action==='regions.remove'){
   const key=command.kind==='keepin'?'boundaries_mm':'exclusions_mm',items=settings[key]||[];
   if(!Number.isInteger(command.index)||command.index<0||command.index>=items.length)throw Error('Índice de região inválido.');
   items.splice(command.index,1);if(!items.length&&key==='boundaries_mm')settings[key]=null;
  }else for(const kind of kinds)settings[kind==='keepin'?'boundaries_mm':'exclusions_mm']=kind==='keepin'?null:[];
  windows=null;regionsChanged();return commandState();
 }
 if(action==='operation.tab'){if(!operationTabs.includes(command.tab))throw Error('tab deve ser rough, drill ou cutout.');selectOperationTab(command.tab);return {tab:command.tab};}
 if(action==='calculate.start'){if(placementUiBusy)throw Error('Aguarde o posicionamento da peça.');return startCalculation(true);}
 if(action==='calculate.cancel'){if(!activeCalculationJob)throw Error('Nenhum cálculo ativo.');return api('/api/cancel',{job:activeCalculationJob});}
 if(action==='project.save')return api('/api/save',request());
 if(action==='nc.export'){
  if(!computedProject||!motion?.moves.some(m=>m[0]==='cut'))throw Error('Calcule um percurso válido com cortes antes de exportar.');
  if(exportBusy||busy)throw Error('Aguarde o cálculo/exportação atual.');
  exportBusy=true;const rev=revision;try{const exported=await api('/api/export',{project_id:computedProject});if(rev!==revision)throw Error('A configuração mudou durante a exportação. Recalcule.');return exported;}
  finally{exportBusy=false;}
 }
 if(action==='view.set'){
  if(command.depth_coloring!==undefined&&typeof command.depth_coloring!=='boolean')throw Error('depth_coloring deve ser booleano.');
  if(command.preset!==undefined&&!['iso','top','front'].includes(command.preset))throw Error('preset deve ser iso, top ou front.');
  const position=command.position===undefined?null:commandVector(command.position,'position'),target=command.target===undefined?null:commandVector(command.target,'target');
  const zoom=command.zoom===undefined?null:commandNumber(command.zoom,'zoom',.05,100);
  cancelDraw();if(command.preset||command.fit)view(command.preset||'iso');
  if(position)camera.position.set(...position);if(target)controls.target.set(...target);if(zoom!==null)camera.zoom=zoom;
  if(command.depth_coloring!==undefined)setDepthColoring(command.depth_coloring);
  camera.updateProjectionMatrix();controls.update();return commandState().view;
 }
 if(action==='view.capture'){renderer.render(scene,camera);return {mime:'image/png',data_url:renderer.domElement.toDataURL('image/png')};}
 if(action==='simulation.sample'){
  if(!stockReady||stockBusy||stockApplied!==stockWanted||!stockSampleSnapshot||stockSampleSnapshot.generation!==stockGeneration||stockSampleSnapshot.index!==stockApplied)
   throw Error('Aguarde a grade da simulação atingir a posição atual antes de amostrar; use simulation.wait.');
  return {index:stockApplied,...sampleStockGrid(stockSampleSnapshot,command.points)};
 }
 if(action==='simulation.set'){
  if(command.mode!==undefined&&!['paths','stock'].includes(command.mode))throw Error('mode deve ser paths ou stock.');
  const speed=command.speed===undefined?null:commandNumber(command.speed,'speed',.1,100);
  if(command.layers!==undefined){commandObject(command.layers,'layers');for(const [k,v]of Object.entries(command.layers))if(!['model','paths','rapids','regions'].includes(k)||typeof v!=='boolean')throw Error('Camada inválida.');}
  if(command.mode)setMode(command.mode);
  if(speed!==null){if(![...$('speed').options].some(o=>Number(o.value)===speed))$('speed').add(new Option(speed+'×',speed));$('speed').value=String(speed);}
  for(const [k,v]of Object.entries(command.layers||{})){const [group,id]={model:[modelGroup,'showModel'],paths:[pathGroup,'showPaths'],rapids:[rapidGroup,'showRapids'],regions:[regionGroup,'showKeepout']}[k];group.visible=v;$(id).checked=v;}
  syncRegionVisibility();
  updateDepthLegend();
  return commandState().simulation;
 }
 if(action==='simulation.play'){if(!feedClock)throw Error('Calcule um percurso com feedrate antes de reproduzir.');if(!playing)$('play').onclick();return commandState().simulation;}
 if(action==='simulation.pause'){stop();requestStock();return commandState().simulation;}
 if(action==='simulation.seek'){
  if(!feedClock)throw Error('Nenhum percurso disponível.');
  const time=command.fraction!==undefined?commandNumber(command.fraction,'fraction',0,1)*feedClock.duration:commandNumber(command.time_s,'time_s',0,feedClock.duration);
  stop();cancelSolid();cursor=time;updateCursor();requestStock();return commandState().simulation;
 }
 if(action==='simulation.reset'){$('resetStock').onclick();return commandState().simulation;}
 throw Error('Comando desconhecido: '+action);
}
async function initializeWorkspace(){
 try{
  const boot=await api('/api/bootstrap');token=boot.token;tools=boot.tools;tool=tools[0]||null;
  presetStore=boot.presets||presetStore;presetError=presetStore.error||'';
  if(tool){
   const initial=importedMachiningState({bounds_mm:{minimum:[0,0,-1],maximum:[1,1,0]}});
   settings=initial.settings;operations=initial.operations;placement={units:'mm',rotation:identity,xy_origin:'minimum',z_origin:'top'};
   if(presetStore.last_used){const next=profilePatch(presetStore.last_used,settings,operations);tool=next.tool;settings=next.settings;operations=next.operations;}
   fillFields();displayToolSelect();
  }
  renderPresets();
  setMotion(null);updateWorkspaceAvailability();updateDepthLegend();view();
  $('loadingScene').hidden=true;$('partName').textContent='Nenhuma peça aberta';
  $('workspaceTitle').textContent='Prepare seu próximo percurso';$('sceneTag').textContent='PRONTO PARA COMEÇAR';
  $('planState').textContent='Aguardando peça';$('calcStatus').textContent='Abra um STL ou um projeto salvo para começar.';
  $('surfaceStatus').textContent='Simulação disponível após calcular os percursos.';$('tipPosition').textContent='X — · Y — · Z —';
 }catch(e){$('loadingScene').hidden=true;updateWorkspaceAvailability();toast(e.message,true);}
}
await initializeWorkspace();
if(token)runCommandBridge(api,executeCommand);
