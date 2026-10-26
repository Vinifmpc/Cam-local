import assert from 'node:assert/strict';
import {getCutoutRecovery} from './static/cutout_feedback.js';

const operations={roughing_enabled:true,cutout_enabled:true,drill_enabled:true,cutout_contours:'all'};
const prefix='Cutout: há contorno interno estreito demais para a fresa de diâmetro 3,175 mm.';
const screenshot=prefix+' Selecione somente contornos externos para recortar a peça ou use uma fresa menor para usinar os internos.';
const legacy=prefix+' Escolha uma fresa menor ou desative o Cutout para calcular somente o desbaste.';
const updated=prefix+' Para apenas soltar a peça, escolha Soltar a peça · somente externo (contornos externos) ou use uma fresa menor para usinar os internos.';
const expected={action:'external_cutout',label:'Soltar a peça · somente externo',
 message:'Para apenas soltar a peça, use somente o contorno externo. Os contornos internos ficarão fora do Cutout. Se também precisar usiná-los, escolha uma fresa menor.'};
for(const message of [screenshot,legacy,updated,prefix,screenshot.replace('3,175','3.175'),screenshot.toUpperCase(),' '+screenshot+'\n']){
 assert.deepEqual(getCutoutRecovery(message,operations),expected);
}
// A stale failure cannot offer a change after the user has already changed
// contour selection, disabled Cutout or loaded an incompatible/default state.
for(const state of [{...operations,cutout_contours:'external'},{...operations,cutout_enabled:false},
 {...operations,cutout_contours:'ALL'},{...operations,cutout_enabled:'true'},
 {roughing_enabled:true,drill_enabled:true},{},null]){
 assert.equal(getCutoutRecovery(screenshot,state),null);
}
for(const message of ['',null,undefined,new Error(screenshot),
 'Cutout bloqueado pelas regiões: o contorno completo não cabe na área permitida',
 'Cutout excede o comprimento de corte da ferramenta',
 'Silhueta sem contorno externo usinável com esta fresa',
 'Cutout: falha ao calcular o percurso.',
 screenshot.replace('interno estreito','externo estreito'),
 screenshot.replace('Cutout:','Drill:'),
 screenshot.replace('3,175','desconhecido'),
 'Outro erro: '+screenshot]){
 assert.equal(getCutoutRecovery(message,operations),null);
}
// The helper is pure; showing the suggestion never edits machining settings.
assert.deepEqual(operations,{roughing_enabled:true,cutout_enabled:true,drill_enabled:true,cutout_contours:'all'});
const first=getCutoutRecovery(screenshot,operations);first.label='changed';
assert.deepEqual(getCutoutRecovery(screenshot,operations),expected);
console.log('Cutout feedback passed: exact preflight category, legacy/current text, diameter formats, operation gates, stale settings and no automatic edits.');
