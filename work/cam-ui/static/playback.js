// Feed clock, independent of render frequency. Older plans remain linear.
function profileState(profile,elapsed,duration){
 if(!profile||!(profile.length_mm>0)||!Number.isFinite(profile.length_mm))return null;
 const {entry_speed_mm_s:v0,peak_speed_mm_s:peak,acceleration_mm_s2:a,
  accel_distance_mm:da,cruise_distance_mm:dc,accel_time_s:ta,cruise_time_s:tc,decel_time_s:td,duration_s:total}=profile;
 // A missing/incomplete optional profile must not make an older plan unplayable.
 if([v0,peak,a,da,dc,ta,tc,td,total].some(v=>!Number.isFinite(v)||v<0)
  ||Math.abs(total-duration)>1e-8*Math.max(1,duration)
  ||Math.abs(ta+tc+td-total)>1e-8*Math.max(1,total))return null;
 let distance,speed;
 if(elapsed<ta){distance=v0*elapsed+.5*a*elapsed*elapsed;speed=v0+a*elapsed;}
 else if(elapsed<ta+tc){distance=da+peak*(elapsed-ta);speed=peak;}
 else{const t=Math.min(td,Math.max(0,elapsed-ta-tc));distance=da+dc+peak*t-.5*a*t*t;speed=peak-a*t;}
 return {fraction:Math.max(0,Math.min(1,distance/profile.length_mm)),speed_mm_min:Math.max(0,speed)*60};
}
export class FeedClock {
 constructor(moves,durations,profiles){
  if(moves.length!==durations.length||durations.some(d=>!Number.isFinite(d)||d<0))throw Error('Preencha os avanços de corte e mergulho e recalcule para reproduzir em tempo real.');
  this.moves=moves;this.profiles=Array.isArray(profiles)?profiles:null;this.ends=new Float64Array(moves.length+1);
  durations.forEach((d,i)=>this.ends[i+1]=this.ends[i]+d);this.duration=this.ends.at(-1);
 }
 at(seconds){
  const t=Math.max(0,Math.min(this.duration,seconds));let lo=0,hi=this.moves.length;
  // Right bound skips zero-duration rows and lands on the active segment.
  while(lo<hi){const m=(lo+hi)>>>1;if(this.ends[m+1]<=t)lo=m+1;else hi=m;}
  const index=lo,m=this.moves[index],elapsed=t-this.ends[index],duration=this.ends[index+1]-this.ends[index];
  const profiled=m?profileState(this.profiles?.[index],elapsed,duration):null;
  const fraction=m?(profiled?.fraction??elapsed/duration):0;
  const speed_mm_min=m?(profiled?.speed_mm_min??Math.hypot(m[4]-m[1],m[5]-m[2],m[6]-m[3])/duration*60):0;
  const position=m?m.slice(1,4).map((v,i)=>v+(m[i+4]-v)*fraction):this.moves.at(-1)?.slice(4,7);
  return {index,fraction,position,stockIndex:index+fraction,speed_mm_min};
 }
}
export function timeLabel(seconds){const s=Math.max(0,Math.floor(seconds||0));return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
