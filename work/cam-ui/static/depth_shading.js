// Height is evaluated per fragment: the palette follows model Z, never camera Z.
// The same sRGB stops drive the legend; shader uniforms use linear RGB.
export const DEPTH_COLORS=['#ffed9c','#a7c5c6','#5b8db8','#40529b','#252457'];
export function depthScale(minimum,maximum){
 if(!Number.isFinite(minimum)||!Number.isFinite(maximum)||maximum<minimum)throw Error('Limites Z inválidos para a escala de profundidade.');
 return {minimum_z:minimum,maximum_z:maximum,range_mm:maximum-minimum};
}
export function depthFraction(z,scale){
 if(!Number.isFinite(z))throw Error('Altura Z inválida.');
 return scale.range_mm>0?Math.max(0,Math.min(1,(scale.maximum_z-z)/scale.range_mm)):0;
}
export function depthGradient(){return `linear-gradient(to bottom,${DEPTH_COLORS.map((color,i)=>`${color} ${i*25}%`).join(',')})`;}
export function createDepthMaterial(THREE,minimum,maximum){
 const scale=depthScale(minimum,maximum);
 const material=new THREE.MeshBasicMaterial({color:0xffffff,side:THREE.DoubleSide,depthWrite:true});
 material.toneMapped=false;
 material.userData.depthScale=scale;
 material.customProgramCacheKey=()=> 'cam-model-depth-v1';
 material.onBeforeCompile=shader=>{
  shader.uniforms.camDepthTop={value:scale.maximum_z};
  shader.uniforms.camDepthRange={value:Math.max(scale.range_mm,1e-9)};
  shader.uniforms.camDepthPalette={value:DEPTH_COLORS.map(color=>new THREE.Color(color))};
  shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying float camModelZ;')
   .replace('#include <begin_vertex>','#include <begin_vertex>\ncamModelZ = position.z;');
  shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
varying float camModelZ;
uniform float camDepthTop;
uniform float camDepthRange;
uniform vec3 camDepthPalette[5];
vec3 camDepthColor(float t) {
 float band = clamp(t, 0.0, 1.0) * 4.0;
 if (band < 1.0) return mix(camDepthPalette[0], camDepthPalette[1], band);
 if (band < 2.0) return mix(camDepthPalette[1], camDepthPalette[2], band - 1.0);
 if (band < 3.0) return mix(camDepthPalette[2], camDepthPalette[3], band - 2.0);
 return mix(camDepthPalette[3], camDepthPalette[4], band - 3.0);
}`)
   .replace('#include <color_fragment>','#include <color_fragment>\ndiffuseColor.rgb = camDepthColor((camDepthTop - camModelZ) / camDepthRange);');
 };
 return material;
}
