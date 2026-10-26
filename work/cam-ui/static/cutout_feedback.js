// Offer a setting change only for the internal-contour tool-fit preflight.
// Re-evaluate against current operations when rendering and before applying it;
// the application also checks its calculation snapshot/revision for stale errors.
const INTERNAL_TOOL_FIT=/^Cutout:\s+há contorno interno estreito demais para a fresa de diâmetro \d+(?:[.,]\d+)?(?:e[+-]?\d+)? mm\.(?:\s|$)/iu;
export function getCutoutRecovery(message,operations={}){
 if(typeof message!=='string'||!INTERNAL_TOOL_FIT.test(message.trim()))return null;
 if(operations?.cutout_enabled!==true||operations.cutout_contours!=='all')return null;
 return {action:'external_cutout',label:'Soltar a peça · somente externo',
  message:'Para apenas soltar a peça, use somente o contorno externo. Os contornos internos ficarão fora do Cutout. Se também precisar usiná-los, escolha uma fresa menor.'};
}
