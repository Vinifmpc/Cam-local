// Ideal feed clock, independent of segment count and render frequency.
export class FeedClock {
 constructor(moves,durations){
  if(moves.length!==durations.length||durations.some(d=>!Number.isFinite(d)||d<0))throw Error('Preencha os avanços de corte e mergulho e recalcule para reproduzir em tempo real.');
  this.moves=moves;this.ends=new Float64Array(moves.length+1);
  durations.forEach((d,i)=>this.ends[i+1]=this.ends[i]+d);this.duration=this.ends.at(-1);
 }
 at(seconds){
  const t=Math.max(0,Math.min(this.duration,seconds));let lo=0,hi=this.moves.length;
  // Right bound skips zero-duration rows and lands on the active segment.
  while(lo<hi){const m=(lo+hi)>>>1;if(this.ends[m+1]<=t)lo=m+1;else hi=m;}
  const index=lo,m=this.moves[index],fraction=m?(t-this.ends[index])/(this.ends[index+1]-this.ends[index]):0;
  const position=m?m.slice(1,4).map((v,i)=>v+(m[i+4]-v)*fraction):this.moves.at(-1)?.slice(4,7);
  return {index,fraction,position,stockIndex:index+fraction};
 }
}
export function timeLabel(seconds){const s=Math.max(0,Math.floor(seconds||0));return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
