import assert from 'node:assert/strict';
import {FeedClock} from './static/playback.js';

const line=(start,end)=>['cut',start,0,-1,end,0,-1,0,'roughing'];
const close=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-9,`${actual} != ${expected}`);
const triangle={entry_speed_mm_s:0,exit_speed_mm_s:0,peak_speed_mm_s:20,acceleration_mm_s2:4,
 length_mm:100,accel_distance_mm:50,cruise_distance_mm:0,decel_distance_mm:50,
 accel_time_s:5,cruise_time_s:0,decel_time_s:5,duration_s:10};
const triangleClock=new FeedClock([line(0,100)],[10],[triangle]);
// A 100 mm triangle reaches 20 mm/s after five seconds: x(1)=2 mm.
for(const [t,x] of [[0,0],[1,2],[2.5,12.5],[5,50],[7.5,87.5],[9,98],[10,100]]){
 close(triangleClock.at(t).position[0],x);
}
close(triangleClock.at(1).fraction,.02);
close(triangleClock.at(1).stockIndex,.02);
for(const [t,speed] of [[0,0],[1,240],[2.5,600],[5,1200],[7.5,600],[9,240],[10,0]]){
 close(triangleClock.at(t).speed_mm_min,speed);
}

const trapezoid={entry_speed_mm_s:0,exit_speed_mm_s:0,peak_speed_mm_s:20,acceleration_mm_s2:10,
 length_mm:100,accel_distance_mm:20,cruise_distance_mm:60,decel_distance_mm:20,
 accel_time_s:2,cruise_time_s:3,decel_time_s:2,duration_s:7};
const trapezoidClock=new FeedClock([line(0,100)],[7],[trapezoid]);
for(const [t,x] of [[1,5],[2,20],[3.5,50],[5,80],[6,95],[7,100]]){
 close(trapezoidClock.at(t).position[0],x);
}
for(const [t,speed] of [[1,600],[2,1200],[3.5,1200],[5,1200],[6,600],[7,0]]){
 close(trapezoidClock.at(t).speed_mm_min,speed);
}
// Both sides of the phase boundaries meet without position jumps.
for(const boundary of [2,5]){
 const left=trapezoidClock.at(boundary-1e-8).position[0];
 const middle=trapezoidClock.at(boundary).position[0];
 const right=trapezoidClock.at(boundary+1e-8).position[0];
 assert.ok(middle-left>0&&middle-left<3e-7);
 assert.ok(right-middle>0&&right-middle<3e-7);
}

const flowing={entry_speed_mm_s:10,exit_speed_mm_s:5,peak_speed_mm_s:20,acceleration_mm_s2:5,
 length_mm:107.5,accel_distance_mm:30,cruise_distance_mm:40,decel_distance_mm:37.5,
 accel_time_s:2,cruise_time_s:2,decel_time_s:3,duration_s:7};
const flowingClock=new FeedClock([line(0,107.5)],[7],[flowing]);
for(const [t,x] of [[1,12.5],[2,30],[4,70],[5,87.5],[7,107.5]]){
 close(flowingClock.at(t).position[0],x);
}
// Profile speeds are mm/s, while the cursor displays feed in mm/min.
for(const [t,speed] of [[0,600],[1,900],[2,1200],[4,1200],[5,900],[6,600],[7,0]]){
 close(flowingClock.at(t).speed_mm_min,speed);
}

// Splitting at the peak keeps the same motion and the established seek index.
const accelerating={...triangle,length_mm:50,exit_speed_mm_s:20,decel_distance_mm:0,decel_time_s:0,duration_s:5};
const decelerating={...triangle,length_mm:50,entry_speed_mm_s:20,accel_distance_mm:0,accel_time_s:0,duration_s:5};
const split=new FeedClock([line(0,50),line(50,100)],[5,5],[accelerating,decelerating]);
for(const t of [0,1,2.5,5,7.5,9,10])close(split.at(t).position[0],triangleClock.at(t).position[0]);
for(const t of [0,1,2.5,5,7.5,9,10])close(split.at(t).speed_mm_min,triangleClock.at(t).speed_mm_min);
assert.equal(split.at(5).index,1);assert.equal(split.at(5).fraction,0);
close(split.at(7.5).stockIndex,1.75);

// Seeking is stateless: negative, beyond-end and reverse times remain supported.
for(const [t,x] of [[20,100],[9,98],[1,2],[5,50],[-1,0],[7.5,87.5]]){
 close(triangleClock.at(t).position[0],x);
}
assert.equal(triangleClock.at(10).index,1);
assert.equal(triangleClock.at(10).stockIndex,1);
assert.equal(triangleClock.at(20).speed_mm_min,0);
close(triangleClock.at(9).speed_mm_min,240);close(triangleClock.at(1).speed_mm_min,240);

const zero={...triangle,length_mm:0,peak_speed_mm_s:0,acceleration_mm_s2:0,
 accel_distance_mm:0,decel_distance_mm:0,accel_time_s:0,decel_time_s:0,duration_s:0};
const skipped=new FeedClock([line(0,0),line(0,100),line(100,100)],[0,10,0],[zero,triangle,zero]);
assert.equal(skipped.at(0).index,1);close(skipped.at(1).position[0],2);
assert.equal(skipped.at(10).index,3);close(skipped.at(10).position[0],100);
assert.deepEqual(new FeedClock([],[],[]).at(0),{index:0,fraction:0,position:undefined,stockIndex:0,speed_mm_min:0});
const allZero=new FeedClock([line(0,0)],[0],[zero]);
assert.equal(allZero.at(0).index,1);assert.deepEqual(allZero.at(0).position,[0,0,-1]);
assert.equal(allZero.at(0).speed_mm_min,0);assert.equal(skipped.at(10).speed_mm_min,0);

// Legacy two-argument clocks, mixed old profiles and malformed optional data
// continue to interpolate by elapsed fraction, including XYZ and stock progress.
const diagonal=['ramp',0,2,0,100,12,-10,0,'roughing'];
for(const profiles of [undefined,null,[null],[{}],[{...triangle,duration_s:9}]]){
 const legacy=new FeedClock([diagonal],[10],profiles);
 assert.deepEqual(legacy.at(1).position,[10,3,-1]);
 close(legacy.at(1).stockIndex,.1);
 close(legacy.at(1).speed_mm_min,Math.sqrt(10200)*6);
 assert.equal(legacy.at(10).speed_mm_min,0);
}
const rampClock=new FeedClock([diagonal],[10],[triangle]);
assert.deepEqual(rampClock.at(1).position,[2,2.2,-.2]);
assert.throws(()=>new FeedClock([line(0,100)],[]));
assert.throws(()=>new FeedClock([line(0,100)],[NaN]));
console.log('Acceleration playback: analytical positions/feeds, continuity, flowing junctions, split paths, rewind, zero moves and legacy clocks passed.');
