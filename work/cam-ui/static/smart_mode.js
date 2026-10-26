// Smart mode chooses operation policy; cutting data still comes from the tool
// and the user's feeds. Geometry and stock decisions belong to the backend.
import {automaticRegionText} from './automatic_regions.js';
export const SMART_SEQUENCE=['drill','roughing','cutout'];
export function isSmartMachining(options={}){return options.machining_mode==='smart';}
export function effectiveMachiningOptions(options={}){
 if(!isSmartMachining(options))return {...options};
 return {...options,order:'roughing_then_cutout',operation_sequence:[...SMART_SEQUENCE],
  roughing_enabled:true,cutout_enabled:true,cutout_contours:'external',cutout_use_prior_roughing:true};
}
export function validateSmartOperationPatch(command={}){
 if(command.order!==undefined||command.enabled?.roughing===false||command.enabled?.cutout===false)
  throw Error('No modo inteligente, Rough e Cutout ficam ativos e o recorte é o último. Selecione Manual para mudar a ordem ou desativá-los.');
}
export function smartEntryHint(centerCutting){
 return centerCutting?'Corte pelo centro confirmado: quando a rampa não couber, o Rough inteligente pode usar mergulho de até um Stepdown, com o Plunge rate.':'Mergulho central desativado. Se a fresa cortar pelo centro, confira a confirmação na aba Drill para permitir essa alternativa à rampa no Rough inteligente.';
}
export function smartPolicyText(plan){
 const mode=plan?.exterior_strategy?.mode;
 if(plan?.internal_cutouts?.selected_count>0)return {
  order:'Rough: rebaixos e bolsões com fundo. Cutout: recortes internos passantes antes do contorno externo completo.',
  regions:'Miolos passantes vantajosos ficam preservados como sobra e são recortados pelo Cutout. O Rough usina os demais detalhes 3D.',
  reuse:'O Cutout conclui cada recorte interno antes de soltar o exterior; só omite camadas comprovadamente já removidas.'};
 if(mode==='features_then_cutout')return {
  order:'Rough: rebaixos e bolsões, inclusive abertos à borda. Cutout: contorno externo completo, em camadas, após o Rough.',
  regions:'O Rough segue furos, bolsões, rebaixos e formas 3D da peça, inclusive abertos à borda. O contorno externo completo fica para o Cutout.',
  reuse:'O Cutout calcula o contorno externo completo em camadas, reutilizando apenas material comprovadamente já removido.'};
 if(mode==='rough_prepare_then_release')return {
  order:'Rough: formas da peça e preparo do canal de acesso com pele de retenção. Cutout: liberação do contorno externo no final.',
  regions:'O Rough segue as formas 3D e prepara o canal de acesso definido no plano. O Cutout termina a liberação.',
  reuse:'O Cutout verifica quais camadas o preparo do Rough já removeu e executa as que restarem até soltar a peça.'};
 return {
  order:'Rough: formas 3D, rebaixos e bolsões, inclusive abertos à borda. Cutout: contorno externo completo em camadas. Confira a viabilidade no plano.',
  regions:'O Rough calcula as formas 3D da peça, inclusive rebaixos abertos à borda. O perfil externo completo fica para o Cutout; confira a viabilidade no plano.',
  reuse:'O Cutout calcula o perfil completo em camadas. O motor verifica as entradas e o material já removido; só passadas comprovadamente realizadas podem ser omitidas.'};
}
export function smartPlanText(plan,format=v=>String(v)){
 if(!plan?.enabled)return '';
 const labels={drill:'Drill',roughing:'Rough',cutout:'Cutout'};
 const sequence=(plan.sequence||[]).map(id=>labels[id]||id).join(' → ');
 const strategy=plan.exterior_strategy,fullContour=strategy?.mode==='features_then_cutout';
 const details=[sequence];
 if(fullContour){
  details.push(`Rough: rebaixos e bolsões, inclusive abertos à borda, e furos compatíveis; limite Z ${format(plan.roughing_bottom_mm)} mm. O perfil externo completo fica para o Cutout.`,
   `Cutout: contorno externo completo até Z ${format(plan.cutout_bottom_mm)} mm, em camadas de até ${format(plan.cutout_stepdown_mm)} mm.`,
   'Peças sem furos ou rebaixos podem ficar sem cortes de Rough.');
  if(plan.internal_cutouts?.selected_count>0)details.push(
   `${plan.internal_cutouts.selected_count} miolo(s) passante(s) recortado(s): o Rough preserva essas sobras, sem desbastar todo o interior. O Cutout termina os internos antes do exterior.`,
   'A simulação mantém o miolo como sobra recortada; apoie essa sobra e remova-a após a usinagem.');
 }else if(strategy?.mode==='rough_prepare_then_release'){
  details.push(`Rough: formas da peça e preparo do canal externo de acesso; limite Z ${format(plan.roughing_bottom_mm)} mm e pele externa de ${format(plan.skin_mm)} mm, até Z ${format(plan.retention_z_mm)} mm.`,
   `Cutout: liberação do contorno externo até Z ${format(plan.cutout_bottom_mm)} mm; descida máxima de ${format(plan.cutout_stepdown_mm)} mm.`);
 }else{
  // Retain the meaning of plans saved before exterior strategy was explicit.
  details.push(`Rough até Z ${format(plan.roughing_bottom_mm)} mm; pele externa de ${format(plan.skin_mm)} mm, até Z ${format(plan.retention_z_mm)} mm.`,
   `Cutout externo até Z ${format(plan.cutout_bottom_mm)} mm; descida máxima de ${format(plan.cutout_stepdown_mm)} mm.`);
 }
 details.push('Keep In / Keep Out continuam valendo para o Rough. O recorte solta o exterior no final.');
 if(typeof strategy?.reason==='string'&&strategy.reason&&!plan.assumptions?.includes(strategy.reason))details.push(strategy.reason);
 const automatic=automaticRegionText(plan,format);if(automatic)details.push(automatic);
 if(plan.assumptions?.length)details.push(...plan.assumptions);
 return details.join(' ');
}
