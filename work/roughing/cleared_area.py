"""Conservative cleared XY area at a height, for flat cylindrical cutters.

Only completed cutting edges are credited. Their entire linear tip profile
must lie at/below the requested height. Old footprints are under-approximated;
new swept disks are over-approximated, with 0.005 mm geometry guards.
Not a general volumetric simulator; stock is bounded by a uniform top plane.
"""
from collections import OrderedDict
import math
import numpy as np
from region_core import boolean,pyclipr,SCALE
from track_index import CutTrackIndex


GUARD=.005
MAX_UNION_ENTRIES=256
MAX_UNION_BYTES=32*1024*1024


def capsule(a,b,radius):
    a=np.asarray(a[:2],float);b=np.asarray(b[:2],float)
    if np.linalg.norm(b-a)<1e-12:
        angles=np.linspace(0,2*np.pi,128,endpoint=False)
        return [a+radius*np.column_stack([np.cos(angles),np.sin(angles)])]
    engine=pyclipr.ClipperOffset();engine.scaleFactor=SCALE
    engine.arcTolerance=.001*SCALE
    engine.addPath([a,b],pyclipr.JoinType.Round,pyclipr.EndType.Round)
    return engine.execute(radius)


class ClearedArea:
    def __init__(self,diameter,stock_top):
        if not math.isfinite(diameter) or diameter<=0 or not math.isfinite(stock_top):
            raise ValueError('Invalid flat cutter or stock top')
        self.radius=diameter/2;self.top=stock_top;self.cuts=CutTrackIndex(diameter)
        self.cache=OrderedDict();self.proofs=0;self.xy_records={};self.proven=set()
        self.union_cache=OrderedDict();self.union_cache_bytes=0
        self.union_cache_hits=0;self.union_cache_misses=0

    def _union(self,subjects):
        # Reuse only byte-identical ordered operands. Height eligibility and
        # completed-cut chronology are still checked by covers on every call.
        # The cache is local to this proof state, including its tool radius.
        arrays=[np.asarray(p) for p in subjects]
        if (any(a.dtype.hasobject for a in arrays) or MAX_UNION_ENTRIES<=0 or
                sum(a.nbytes for a in arrays)>MAX_UNION_BYTES):
            return boolean(subjects,[],pyclipr.Union)
        key=tuple((a.shape,a.dtype,a.tobytes(order='C')) for a in arrays)
        try:
            result,size=self.union_cache.pop(key)
        except KeyError:
            self.union_cache_misses+=1
            result=boolean(subjects,[],pyclipr.Union)
            # Both retained input bytes and result buffers count towards the
            # byte budget; entry count separately bounds Python metadata.
            size=sum(len(p[2]) for p in key)+sum(np.asarray(p).nbytes for p in result)
            if MAX_UNION_ENTRIES>0 and size<=MAX_UNION_BYTES:
                while self.union_cache and (len(self.union_cache)>=MAX_UNION_ENTRIES or
                                             self.union_cache_bytes+size>MAX_UNION_BYTES):
                    _,(_,old_size)=self.union_cache.popitem(last=False)
                    self.union_cache_bytes-=old_size
                self.union_cache[key]=(result,size);self.union_cache_bytes+=size
        else:
            self.union_cache[key]=(result,size);self.union_cache_hits+=1
        # As with capsule footprints, consumers pass these arrays to Clipper
        # read-only. Neither the cached container nor its arrays are modified.
        return result

    def add(self,a,b):
        key=tuple(sorted((tuple(a[:2]),tuple(b[:2]))))
        # The footprint is XY-only and eligibility uses the highest endpoint.
        # Of repeated traversals of exactly the same XY segment only the one
        # with the lowest highest endpoint can add any clearance proof.
        previous=self.xy_records.get(key)
        if previous is not None:
            c,e,_=self.cuts.records[previous]
            if max(a[2],b[2])<max(c[2],e[2]):
                self.cuts.records[previous]=(list(a),list(b),key)
            return
        self.xy_records[key]=len(self.cuts)
        self.cuts.append((list(a),list(b),key))

    def covers(self,a,b,height,*,require_cut=False):
        if height>=self.top and not require_cut:return True
        if self.radius<=GUARD:return False
        query=(tuple(a[:2]),tuple(b[:2]),height)
        if query in self.proven:return True
        # Circumscribed point disk: apothem exceeds the true tool radius.
        r=(self.radius+GUARD)/math.cos(math.pi/128) if math.dist(a[:2],b[:2])<1e-12 else self.radius+GUARD
        # Only nearby old footprints can cover this request. The sum of old
        # and required radii gives a conservative centerline bounding box;
        # the index merely drops disjoint cuts, never establishes clearance.
        padding=r+self.radius-GUARD
        low=[min(a[i],b[i])-padding for i in range(2)]
        high=[max(a[i],b[i])+padding for i in range(2)]
        eligible=[]
        for c,e,key in self.cuts.overlapping(low,high):
            if max(c[2],e[2])<=height:eligible.append((c,e,key))
        if not eligible:return False
        required=capsule(a,b,r)
        if not required:return False
        # A few vertices of the required polygon must at least fall inside
        # the analytic (slightly enlarged) old capsules. This is rejection
        # only; the original polygon difference still proves every success.
        # Clipper rounds integer offset coordinates: allow two grid units in
        # this bounding volume so no rounded footprint can be discarded.
        vertices=np.concatenate(required)
        directions=np.array(((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1)))
        samples=vertices[np.argmax(vertices@directions.T,axis=0)]
        starts=np.array([c[:2] for c,_,_ in eligible]);ends=np.array([e[:2] for _,e,_ in eligible])
        vectors=ends-starts;squared=np.einsum('ij,ij->i',vectors,vectors)
        relative=samples[:,None,:]-starts
        fraction=np.divide(np.einsum('sij,ij->si',relative,vectors),squared,
                           out=np.zeros((len(samples),len(starts))),where=squared>0)
        distance=relative-np.clip(fraction,0,1)[:,:,None]*vectors
        if np.any(np.all(np.einsum('sij,sij->si',distance,distance)>
                         (self.radius-GUARD+2/SCALE)**2,axis=1)):return False
        additions=[]
        for c,e,key in eligible:
            # Geometry depends on XY only. Repeated passes at deeper levels
            # share the same conservative capsule, but eligibility is tested
            # against the exact requested height for every completed cut.
            footprint=self.cache.pop(key,None)
            if footprint is None:footprint=capsule(c,e,self.radius-GUARD)
            self.cache[key]=footprint
            if len(self.cache)>10000:self.cache.popitem(last=False)
            additions.extend(footprint)
        # NonZero clips represent the union of these positive-winding
        # capsules, including any holes preserved by the batched unions.
        # Dense groups of overlapping capsules have many coincident arcs.
        # Collapse small groups first, so Clipper never has to compare every
        # pair of the original tens of thousands of round-arc vertices.
        if len(additions)>32:
            additions=[p for index in range(0,len(additions),32)
                       for p in self._union(additions[index:index+32])]
        remainder=boolean(required,additions,pyclipr.Difference)
        valid=not remainder
        if valid:self.proofs+=1;self.proven.add(query)
        return valid
