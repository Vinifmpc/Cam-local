// One bounded stdin/stdout request. No G-code, network, machine or file writes.
const ocl=require('../geometry-runtime/node_modules/@opencamlib/opencamlib');
let input='';
process.stdin.setEncoding('utf8');
process.stdin.on('data',chunk=>{
 input+=chunk;
 if(input.length>64*1024*1024){console.error('Request exceeds 64 MiB');process.exit(1);}
});
process.stdin.on('end',()=>{
 try{
  const job=JSON.parse(input);
  const {triangles,segments,diameter,length,sampling,floor}=job;
  if(!Array.isArray(triangles)||!triangles.length||!Array.isArray(segments)||
   ![diameter,length,sampling].every(x=>Number.isFinite(x)&&x>0)||!Number.isFinite(floor))throw Error('Invalid contact request');
  if(triangles.length>1_000_000||segments.length>100_000)throw Error('Prototype request limit exceeded');
  const surf=new ocl.STLSurf();surf.triangles=triangles;
  const route=new ocl.Path();const counts=[];
  let total=0;
  for(const segment of segments){
   const {start:a,end:b}=segment;
   if(!a||!b||a.length!==2||b.length!==2||![...a,...b].every(Number.isFinite))throw Error('Invalid XY segment');
   const distance=Math.hypot(b[0]-a[0],b[1]-a[1]);
   if(!(distance>0))throw Error('Zero-length XY segment');
   const count=Math.floor(distance/sampling+1)+1;
   counts.push(count);total+=count;
   if(total>1_000_000)throw Error('Prototype sample limit exceeded');
   route.append(new ocl.Line(new ocl.Point(...a,0),new ocl.Point(...b,0)));
  }
  if(!total){process.stdout.write(JSON.stringify({paths:[],samples:0}));return;}
  const drop=new ocl.PathDropCutter();drop.setSTL(surf);
  drop.setCutter(new ocl.CylCutter(diameter,length));
  drop.setPath(route);drop.setSampling(sampling);drop.setZ(floor);drop.run();
  const points=drop.getCLPoints();
  if(points.length!==total)throw Error(`Unexpected native sample count ${points.length}/${total}`);
  let cursor=0;const paths=[];
  for(let index=0;index<segments.length;index++){
   const pointsForLine=points.slice(cursor,cursor+counts[index]);cursor+=counts[index];
   const {start:a,end:b}=segments[index];
   for(let i=0;i<pointsForLine.length;i++){
    const p=pointsForLine[i],f=i/(pointsForLine.length-1);
    if(!p.every(Number.isFinite)||Math.hypot(p[0]-a[0]-(b[0]-a[0])*f,p[1]-a[1]-(b[1]-a[1])*f)>1e-6)
     throw Error('Native point order/coordinates do not match requested route');
   }
   paths.push(pointsForLine);
  }
  process.stdout.write(JSON.stringify({paths,samples:points.length,engine:'OpenCAMLib 2023.1.11 Node-API'}));
 }catch(error){console.error(error.stack??error.message);process.exitCode=1;}
});
