"""Plan and independently prove safe-plane detours around physical Keep Out."""
import heapq
import math
import numpy as np
from region_core import SCALE,boolean,normalize_solids,offset,pyclipr


def fixture_travel_policy(settings,tool,options):
    if options.machining_mode!='smart' or not options.smart_part_released or not settings.exclusions_mm:return None
    return {'mode':'avoid_keepout_xy','regions_mm':settings.exclusions_mm,
            'cutter_radius_mm':tool.diameter_mm/2,'margin_mm':settings.boundary_margin_mm}


class FixtureTravel:
    def __init__(self,policy):
        self.enabled=policy is not None;self.cache={};self.nodes=[];self.forbidden=[];self.fallback=[]
        if not self.enabled:return
        if not isinstance(policy,dict) or policy.get('mode')!='avoid_keepout_xy':raise ValueError('Política de desvio da fixação inválida')
        radius=policy['cutter_radius_mm'];margin=policy['margin_mm']
        if not math.isfinite(radius) or radius<=0 or not math.isfinite(margin) or margin<0:raise ValueError('Raio/folga da fixação inválidos')
        solids=boolean(normalize_solids(policy['regions_mm']),[],pyclipr.Union)
        # The NC uses five decimals. Keep both raw and rounded centre lines
        # outside a larger guard, then put candidate vertices farther away.
        self.forbidden=offset(solids,radius+.00002)
        self.enabled=bool(self.forbidden)
        outlines=offset(solids,radius+margin+.05)
        for path in outlines:
            low=path.min(axis=0)-.01;high=path.max(axis=0)+.01
            self.nodes.extend([(low[0],low[1]),(low[0],high[1]),(high[0],low[1]),(high[0],high[1])])
            self.fallback.extend(tuple(p) for p in path)
        self.nodes=list(dict.fromkeys(self.nodes));self.fallback=list(dict.fromkeys(self.fallback))

    def _inside(self,p):
        # Canonical union paths include oriented holes; use winding rather
        # than treating every offset loop as an independent filled obstacle.
        winding=0;x,y=p
        for path in self.forbidden:
            for a,b in zip(path,np.roll(path,-1,axis=0)):
                cross=(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])
                if abs(cross)<=1e-7 and min(a[0],b[0])-1e-7<=x<=max(a[0],b[0])+1e-7 and min(a[1],b[1])-1e-7<=y<=max(a[1],b[1])+1e-7:return True
                if a[1]<=y<b[1] and cross>0:winding+=1
                elif b[1]<=y<a[1] and cross<0:winding-=1
        return winding!=0

    def _clear_xy(self,a,b):
        if self._inside(a) or self._inside(b):return False
        if math.dist(a,b)<1e-10:return True
        clip=pyclipr.Clipper();clip.scaleFactor=SCALE;clip.addPath([a,b],pyclipr.Subject,True)
        clip.addPaths(self.forbidden,pyclipr.Clip)
        _,inside=clip.execute(pyclipr.Intersection,pyclipr.FillRule.NonZero,returnOpenPaths=True)
        return not any(sum(math.dist(p,q) for p,q in zip(path,path[1:]))>1e-8 for path in inside)

    def clear(self,a,b):
        if not self.enabled:return True
        u,v=tuple(a[:2]),tuple(b[:2]);key=(u,v)
        if key not in self.cache:
            p=tuple(float(f'{x:.5f}') for x in u);q=tuple(float(f'{x:.5f}') for x in v)
            self.cache[key]=self._clear_xy(u,v) and self._clear_xy(p,q)
        return self.cache[key]

    def route(self,a,b):
        if not self.enabled or self.clear(a,b):return [list(a),list(b)]
        if abs(a[2]-b[2])>1e-8:raise ValueError('Desvio da fixação exige travessia no plano seguro')
        if self._inside(a[:2]) or self._inside(b[:2]):raise ValueError('Travessia começa ou termina dentro da fixação protegida')
        start,goal=tuple(a[:2]),tuple(b[:2])
        def search(candidates):
            vertices=list(dict.fromkeys([start,goal,*candidates]));end=vertices.index(goal)
            if len(vertices)>514:raise ValueError('Fixação complexa demais para calcular um desvio seguro; simplifique a região protegida')
            distances={0:0.};parents={};queue=[(0.,0)]
            while queue:
                cost,i=heapq.heappop(queue)
                if cost!=distances[i]:continue
                if i==end:
                    indices=[end]
                    while indices[-1]!=0:indices.append(parents[indices[-1]])
                    return [[*vertices[j],a[2]] for j in reversed(indices)]
                for j,p in enumerate(vertices):
                    if j==i:continue
                    new=cost+math.dist(vertices[i],p)
                    if new>=distances.get(j,math.inf):continue
                    if not self.clear(vertices[i],p):continue
                    distances[j]=new;parents[j]=i;heapq.heappush(queue,(new,j))
            return None
        # Bounding corners make the common central screw inexpensive. A
        # bounded polygon visibility search also handles concave fixtures.
        route=search(self.nodes)
        if route is None:route=search([*self.nodes,*self.fallback])
        if route is None:raise ValueError('Não foi possível contornar a fixação; reveja o ponto inicial e as regiões protegidas')
        if any(not self.clear(p,q) for p,q in zip(route,route[1:])):raise ValueError('Desvio da fixação sem prova geométrica')
        return route
