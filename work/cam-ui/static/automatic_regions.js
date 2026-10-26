// The backend reports the effective XY domain of tool centers. This overlay is
// a planning envelope; it does not claim that every point is cut at every Z.
export const AUTOMATIC_REGION_COLOR=0x087f9f;
export function automaticRegionLoops(regions){
 const loops=regions?.polygons_mm;
 if(!Array.isArray(loops))return [];
 return loops.filter(loop=>Array.isArray(loop)&&loop.length>=3&&loop.every(p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(p[0])&&Number.isFinite(p[1])))
  .map(loop=>loop.map(p=>[p[0],p[1]]));
}
export function automaticRegionText(plan,format=value=>String(value)){
 const regions=plan?.automatic_regions;
 if(!regions)return '';
 const fullContour=plan.exterior_strategy?.mode==='features_then_cutout';
 let text=`Rough automático: área dos centros da fresa de ${format(regions.area_mm2)} mm²${fullContour?'. Os cortes seguem as formas 3D, bolsões e rebaixos por profundidade, inclusive abertos à borda.':`; faixa de planejamento de ${format(regions.offset_mm)} mm ao redor da peça.`}`;
 if(regions.manual_limits_applied)text+=' Keep In / Keep Out limitam essa área.';
 text+=' O envelope XY não representa remoção em todas as profundidades; a fresa também varre seu raio ao redor dos centros.';
 if(!fullContour&&plan.preparation_contours?.blocked>0)text+=' Limites manuais impedem preparar parte do exterior; Cutout terá passadas adicionais.';
 return text;
}
export function smartPlanForState(plan,detail=false){
 if(!plan||detail||!plan.automatic_regions)return plan;
 const regions={...plan.automatic_regions},loops=regions.polygons_mm||[];
 regions.polygon_count=loops.length;regions.vertex_count=loops.reduce((count,p)=>count+p.length,0);
 delete regions.polygons_mm;
 delete regions.source_polygons_mm;
 const internal=plan.internal_cutouts?{...plan.internal_cutouts,features:(plan.internal_cutouts.features||[]).map(feature=>{
  const compact={...feature};delete compact.excluded_center_polygons_mm;delete compact.core_polygons_mm;return compact;
 })}:undefined;
 return {...plan,automatic_regions:regions,...(internal?{internal_cutouts:internal}:{})};
}
export function createAutomaticRegionOverlay(THREE,regions,z){
 const group=new THREE.Group(),loops=automaticRegionLoops(regions);
 if(!loops.length)return group;
 const shapePath=new THREE.ShapePath();
 for(const loop of loops){
  shapePath.moveTo(...loop[0]);for(const point of loop.slice(1))shapePath.lineTo(...point);shapePath.currentPath.closePath();
 }
 // Canonical Clipper loops use positive (CCW) exteriors and negative holes.
 // ShapePath also assigns disjoint components and holes to their proper shell.
 for(const shape of shapePath.toShapes(true)){
  const fill=new THREE.Mesh(new THREE.ShapeGeometry(shape),new THREE.MeshBasicMaterial({color:AUTOMATIC_REGION_COLOR,side:THREE.DoubleSide,transparent:true,opacity:.075,depthWrite:false}));
  fill.position.z=z;fill.userData.automaticRegionFill=true;group.add(fill);
 }
 const b=regions.bounds_mm,span=Array.isArray(b)&&b.length===4?Math.max(b[2]-b[0],b[3]-b[1],1):100;
 const dash=Math.max(.2,span/100);
 for(const loop of loops){
  const geometry=new THREE.BufferGeometry().setFromPoints([...loop,loop[0]].map(point=>new THREE.Vector3(point[0],point[1],z+.025)));
  const line=new THREE.Line(geometry,new THREE.LineDashedMaterial({color:AUTOMATIC_REGION_COLOR,transparent:true,opacity:.85,dashSize:dash,gapSize:dash*.6,depthWrite:false}));
  line.computeLineDistances();line.userData.automaticRegionOutline=true;group.add(line);
 }
 return group;
}
