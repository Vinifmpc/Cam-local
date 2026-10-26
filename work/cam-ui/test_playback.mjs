import assert from 'node:assert/strict';
import {FeedClock,timeLabel} from './static/playback.js';
import {StockModel,StockPlayback} from './static/stock_model.js';
const line=['cut',0,0,-1,100,0,-1,0,'roughing'];
let clock=new FeedClock([line],[10]);
assert.deepEqual(clock.at(5).position,[50,0,-1]);
assert.equal(clock.at(1).position[0],10);assert.equal(clock.at(1*2).position[0],20);assert.equal(clock.at(1*3).position[0],30);
assert.equal(clock.at(11).stockIndex,1);assert.equal(clock.at(-1).stockIndex,0);
// Splitting a line does not alter its position at a given clock time.
const split=new FeedClock([['cut',0,0,-1,30,0,-1],['cut',30,0,-1,100,0,-1]],[3,7]);
for(const t of [0,1,3,5,9,10])assert.deepEqual(split.at(t).position,clock.at(t).position);
clock=new FeedClock([line,line,line],[0,10,0]);assert.equal(clock.at(0).index,1);assert.equal(clock.at(10).index,3);
assert.throws(()=>new FeedClock([line],[null]));assert.equal(timeLabel(65),'01:05');assert.equal(timeLabel(3665),'1:01:05');
const c={x0:0,y0:-2,x1:100,y1:2,top:0,bottom:-2,step:1,diameter:2,boundaries:null,exclusions:[]};
const playback=new StockPlayback(c,[line]);
const half=playback.seek(.5),quarter=playback.seek(.25),full=playback.seek(1),back=playback.seek(.5);
const at=(s,x)=>s.heights[2*s.nx+x];
assert.equal(at(half,70),0);assert.equal(at(half,40),-1);assert.equal(at(quarter,40),0);
assert.equal(at(full,70),-1);assert.deepEqual(half.heights,back.heights);assert.equal(playback.seek(0).volume,0);
// Ramps also interpolate Z: no material can be removed by the future end.
const ramp=['ramp',0,0,0,100,0,-2,0,'roughing'];
const rp=new StockPlayback(c,[ramp]).seek(.5);assert.equal(at(rp,70),0);assert.ok(at(rp,49)>-1.01);
// Region diagnostics follow explicit operation scope, never hide removal.
const masked={...c,boundaries:[[[0,-2],[10,-2],[10,2],[0,2]]]};
const rough=new StockModel(masked),cut=new StockModel(masked);
rough.apply(line);cut.apply([...line.slice(0,8),'cutout']);assert.ok(rough.protectedCount>0);assert.equal(cut.protectedCount,0);assert.equal(cut.volume,rough.volume);
const linked=new StockModel(c);linked.apply(line);const priorVolume=linked.volume;
linked.apply(['link_cleared',100,0,-1,20,0,-1,0,'roughing']);assert.equal(linked.volume,priorVolume);
console.log('Playback: feed timing, 2x/3x, segment independence, zero duration, partial stock, rewind, ramps and region scope passed.');
