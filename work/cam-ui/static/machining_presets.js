// Only reusable machining choices. Part coordinates, regions and final depths
// stay with each project and are never transferred by a preset.
export const PRESET_SETTINGS=['stepdown_mm','sampling_mm','tolerance_mm','radial_allowance_mm','axial_allowance_mm','boundary_margin_mm','entry_angle_deg','clearance_mm','approach_gap_mm','strategy','raster_angle_deg','cleanup_contours','surface_error_mm','path_tolerance_mm','optimize_entries'];
export const PRESET_OPERATIONS=['order','roughing_order','roughing_enabled','cutout_enabled','cutout_stepdown_mm','cutout_smoothing_mm','cutout_direction','cutout_contours','cutout_use_prior_roughing','roughing_feed_mm_min','cutout_feed_mm_min','plunge_mm_min','rapid_mm_min','spindle_rpm','drill_enabled','drill_allow_helix','drill_center_cutting','drill_compensate_facets','drill_peck_mm','drill_retract_mode','drill_retract_mm','drill_rapid_reentry','drill_reentry_gap_mm','drill_tolerance_mm','drill_feed_mm_min','operation_sequence','machining_mode','smart_part_released','smart_breakthrough_mm','smart_skin_mm','timing_model','machine_max_rate_mm_min','machine_acceleration_mm_s2','machine_steps_per_mm','machine_junction_deviation_mm','machine_planner_blocks'];
const pick=(record,keys)=>Object.fromEntries(keys.filter(k=>record[k]!==undefined).map(k=>[k,structuredClone(record[k])]));
export function machiningProfile(tool,settings,operations){
 return {tool:structuredClone(tool),settings:pick(settings,PRESET_SETTINGS),operations:pick(operations,PRESET_OPERATIONS),stepover_percent:100*settings.stepover_mm/tool.diameter_mm};
}
export function profilePatch(profile,settings,operations){
 if(!profile?.tool||!Number.isFinite(profile.stepover_percent)||profile.stepover_percent<=0||profile.stepover_percent>100)throw Error('Preset inválido.');
 return {tool:structuredClone(profile.tool),settings:{...settings,...pick(profile.settings,PRESET_SETTINGS),stepover_mm:profile.tool.diameter_mm*profile.stepover_percent/100},operations:{...operations,...pick(profile.operations,PRESET_OPERATIONS)}};
}
export function rememberProfileRequest(profile,store,{updateSelected=true}={}){
 const selected=store.presets.find(p=>p.id===store.selected_id);
 return selected&&updateSelected
  ?{action:'save',id:selected.id,name:selected.name,profile:structuredClone(profile)}
  :{action:'remember',selected_id:selected?.id??null,profile:structuredClone(profile)};
}
