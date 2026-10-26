// Smooth only wall lighting. Positions, heights and removal diagnostics stay
// untouched; flat floors and opposite sides of narrow slots remain separate.
export function smoothWallNormals(normals,nx,ny){
 const source=normals.slice();
 for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){
  const k=(y*nx+x)*3;
  if(source[k+2]>=.95)continue;
  let sx=0,sy=0,sz=0;
  for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){
   if(x+dx<0||x+dx>=nx||y+dy<0||y+dy>=ny)continue;
   const q=((y+dy)*nx+x+dx)*3;
   if(source[q+2]>=.95)continue;
   const dot=source[k]*source[q]+source[k+1]*source[q+1]+source[k+2]*source[q+2];
   if(dot<-.1)continue;
   const weight=(3-Math.abs(dx))*(3-Math.abs(dy));
   sx+=weight*source[q];sy+=weight*source[q+1];sz+=weight*source[q+2];
  }
  const length=Math.hypot(sx,sy,sz);
  if(length>1e-12){normals[k]=sx/length;normals[k+1]=sy/length;normals[k+2]=sz/length;}
 }
 return normals;
}
