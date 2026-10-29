import assert from 'node:assert/strict';
import fs from 'node:fs';
import {TIMING_DEFAULTS,TIMING_AXIS_FIELDS,TIMING_SCALAR_FIELDS,TIMING_FORM_IDS,readTimingValues,timingFormValues,timingControlState,readOperationValues} from './static/form_state.js';
import {PRESET_OPERATIONS,machiningProfile,profilePatch} from './static/machining_presets.js';

// A project from before machine profiles receives the 3018 estimate defaults.
assert.deepEqual(readTimingValues(),TIMING_DEFAULTS);
assert.equal(TIMING_DEFAULTS.machine_planner_blocks,15,'The GRBL profile uses the 15 available planner blocks');
assert.deepEqual(readTimingValues(timingFormValues()),TIMING_DEFAULTS);
const oldForm={roughEnabled:true,roughFeed:'700',plungeFeed:'150',rapidFeed:'3200'};
const tool={id:'flat',diameter_mm:3.175,feed_mm_min:700,plunge_mm_min:150};
const oldOperations=readOperationValues(oldForm,{},tool);
for(const [key,value]of Object.entries(TIMING_DEFAULTS))assert.deepEqual(oldOperations[key],value);
assert.equal(oldOperations.rapid_mm_min,3200,'The legacy rapid choice remains stored when disabled');
assert.equal(readOperationValues({...oldForm,rapidFeed:''},{},tool).rapid_mm_min,3000,'Acceleration timing never requires the unused legacy rapid');
assert.throws(()=>readOperationValues({...oldForm,timingModel:'constant',rapidFeed:''},{},tool),/Rápido estimado/);

const profile={timing_model:'acceleration',machine_max_rate_mm_min:[1500,1400,800],machine_acceleration_mm_s2:[10,11,8],machine_steps_per_mm:[400,400,800],machine_junction_deviation_mm:.02,machine_planner_blocks:32};
const restored=timingFormValues(profile);
assert.deepEqual(restored,{timingModel:'acceleration',machineMaxRate:[1500,1400,800],machineAcceleration:[10,11,8],machineSteps:[400,400,800],machineJunctionDeviation:.02,machinePlannerBlocks:32});
const typed=Object.fromEntries(Object.entries(restored).map(([key,value])=>[key,Array.isArray(value)?value.map(String):String(value)]));
assert.deepEqual(readTimingValues(typed),profile,'Axis arrays survive form read/fill without reordering or changing units');
const edited=readOperationValues({...oldForm,...typed},{},tool);
for(const [key,value]of Object.entries(profile))assert.deepEqual(edited[key],value);
restored.machineMaxRate[0]=999;
assert.equal(profile.machine_max_rate_mm_min[0],1500,'Form arrays never mutate the saved profile');
assert.deepEqual(readTimingValues({},profile),profile,'Omitted controls preserve an existing profile');
assert.deepEqual(readTimingValues({machineMaxRate:['','bad','-1'],machinePlannerBlocks:'2.5',machineJunctionDeviation:''},profile,{strict:false}),profile,'Incomplete typing keeps valid stored values for automatic persistence');

for(const field of Object.keys(TIMING_AXIS_FIELDS)){
 for(const invalid of [null,{},'1,2,3',[],[1,2],[1,2,3,4],[1,0,1],[1,-1,1],[1,Infinity,1],[1,NaN,1],[1,true,1],[1,[2],1],[1,'',1],[1,'bad',1]]){
  assert.throws(()=>readTimingValues({[field]:invalid}),undefined,`${field} rejects ${JSON.stringify(invalid)}`);
 }
}
for(const key of ['machine_max_rate_mm_min','machine_acceleration_mm_s2','machine_steps_per_mm']){
 for(const invalid of [null,[1,2],[1,0,1],[1,NaN,1]])assert.throws(()=>timingFormValues({...profile,[key]:invalid}));
}
for(const invalid of ['bad','',-1,Infinity,true])assert.throws(()=>readTimingValues({machineJunctionDeviation:invalid}),/Desvio de junção/);
assert.equal(readTimingValues({machineJunctionDeviation:'0'}).machine_junction_deviation_mm,0,'Zero junction deviation permits exact-stop timing');
for(const invalid of ['bad','',1,129,2.5,Infinity,true])assert.throws(()=>readTimingValues({machinePlannerBlocks:invalid}),/Blocos do planejador/);
for(const value of [2,16,128])assert.equal(readTimingValues({machinePlannerBlocks:String(value)}).machine_planner_blocks,value);
assert.throws(()=>readTimingValues({timingModel:'unknown'}),/modelo de tempo/);

const settings={stepdown_mm:.7,stepover_mm:1.27,stock_top_mm:0,bottom_mm:-10};
const saved=machiningProfile(tool,settings,edited);
for(const key of Object.keys(profile)){
 assert.ok(PRESET_OPERATIONS.includes(key));
 assert.deepEqual(saved.operations[key],profile[key]);
}
saved.operations.machine_max_rate_mm_min[0]=1200;
assert.equal(edited.machine_max_rate_mm_min[0],1500,'Saving a preset clones machine arrays');
const applied=profilePatch(saved,settings,{cutout_bottom_mm:-20});
assert.equal(applied.operations.machine_max_rate_mm_min[0],1200);
assert.equal(applied.operations.cutout_bottom_mm,-20);
assert.deepEqual(readTimingValues({},applied.operations),{...profile,machine_max_rate_mm_min:[1200,1400,800]});
assert.deepEqual(readTimingValues({},profilePatch(machiningProfile(tool,settings,{}),settings,{}).operations),TIMING_DEFAULTS,'Legacy presets remain valid');

const acceleration=timingControlState('acceleration'),constant=timingControlState('constant');
assert.equal(acceleration.rapidDisabled,true);assert.equal(acceleration.profileDisabled,false);
assert.match(acceleration.estimateHint,/aceleração, desaceleração e redução nos cantos/);
assert.match(acceleration.rapidHint,/limites por eixo/);
assert.equal(constant.rapidDisabled,false);assert.equal(constant.profileDisabled,true);
assert.match(constant.estimateHint,/Modelo legado/);
assert.equal(readOperationValues({...oldForm,...typed,timingModel:'constant'},profile,tool).timing_model,'constant');
assert.deepEqual(readTimingValues({...typed,timingModel:'constant'}).machine_acceleration_mm_s2,profile.machine_acceleration_mm_s2,'Switching models preserves the machine profile');

// Check the real form contract and listener wiring without a browser DOM.
const html=fs.readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
for(const id of [...TIMING_FORM_IDS,'machineTiming','machineTimingProfile','timingEstimateHint','rapidEstimateHint'])assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,`One control for ${id}`);
assert.equal(TIMING_FORM_IDS.length,TIMING_SCALAR_FIELDS.length+9);
assert.match(html,/Editar estima o tempo · Gravar altera o GRBL/);
assert.doesNotMatch(html,/\$\/mm|rápido estimado, sem aceleração/);
assert.match(html,/id="machineJunctionDeviation"[^>]*min="0"/);
assert.match(app,/for\(const id of TIMING_SCALAR_FIELDS\)values\[id\]=\$\(id\)\.value/);
assert.match(app,/TIMING_AXIS_FIELDS\)\)values\[key\]=ids\.map\(id=>\$\(id\)\.value\)/);
assert.match(app,/\$\('rapidFeed'\)\.disabled=timing\.rapidDisabled/);
assert.match(app,/\$\('machineTimingProfile'\)\.disabled=timing\.profileDisabled/);
assert.match(app,/Object\.keys\(fieldMap\),\.\.\.TIMING_FORM_IDS/,'Profile changes use the calculation invalidation listeners');
assert.match(app,/new FeedClock\(motion\.moves,motion\.durations_s,motion\.timing_profiles\)/,'Playback receives the calculated phase profiles');
console.log('Time estimate form: machine defaults, roundtrip, validation, presets, mode controls, invalidation and playback wiring passed.');
