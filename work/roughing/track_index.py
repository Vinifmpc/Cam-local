"""Conservative XY broad phase for completed cutting tracks.

The index only filters disjoint bounding boxes. Callers still perform their
original exact collinearity/height tests; a bucket never proves clearance.
"""
import math


class CutTrackIndex:
    def __init__(self,cell_size=2.0,epsilon=1e-8):
        self.cell=max(float(cell_size),float(epsilon)*4)
        self.epsilon=float(epsilon)
        self.records=[];self.bounds=[];self.buckets={};self.large=[]

    def __len__(self):return len(self.records)

    def __iter__(self):return iter(self.records)

    def _bounds(self,a,b):
        e=self.epsilon
        return (min(a[0],b[0])-e,min(a[1],b[1])-e,
                max(a[0],b[0])+e,max(a[1],b[1])+e)

    def _cells(self,bounds):
        x0,y0,x1,y1=(math.floor(v/self.cell) for v in bounds)
        if (x1-x0+1)*(y1-y0+1)>4096:return None
        return ((x,y) for x in range(x0,x1+1) for y in range(y0,y1+1))

    def append(self,record):
        index=len(self.records);bounds=self._bounds(record[0],record[1])
        self.records.append(record);self.bounds.append(bounds)
        cells=self._cells(bounds)
        if cells is None:self.large.append(index)
        else:
            for cell in cells:self.buckets.setdefault(cell,[]).append(index)

    def overlapping(self,a,b):
        bounds=self._bounds(a,b);cells=self._cells(bounds)
        if cells is None:candidates=range(len(self.records))
        else:
            candidates=set(self.large)
            for cell in cells:candidates.update(self.buckets.get(cell,()))
            # Preserve source order, including the planner's proof provenance.
            candidates=sorted(candidates)
        x0,y0,x1,y1=bounds
        return (self.records[i] for i in candidates
                if self.bounds[i][0]<=x1 and self.bounds[i][2]>=x0
                and self.bounds[i][1]<=y1 and self.bounds[i][3]>=y0)


def overlapping(tracks,a,b):
    return tracks.overlapping(a,b) if isinstance(tracks,CutTrackIndex) else tracks
