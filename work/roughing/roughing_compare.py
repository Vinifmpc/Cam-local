"""Discrete tool-swept floor comparison; no mesh/stock collision certificate.

For a flat cylindrical tool moving along a straight XYZ segment, compute the
lowest tip Z whose XY disk covers each query point. This is exact at the query
points for the supplied linear paths; the XY grid is a discrete approximation.
"""
import math
import numpy as np


def swept_floor(points,segments,*,diameter,stock_top=0.0):
    xy=np.asarray(points,float)
    moves=np.asarray(segments,float)
    if xy.ndim!=2 or xy.shape[1:]!=(2,) or not np.isfinite(xy).all():
        raise ValueError('Expected finite XY query points')
    if not math.isfinite(diameter) or diameter<=0 or not math.isfinite(stock_top):
        raise ValueError('Invalid diameter/stock top')
    if len(xy)>250_000:raise ValueError('Grid limit: 250,000 query points')
    result=np.full(len(xy),float(stock_top))
    if not len(moves):return result
    if moves.ndim!=3 or moves.shape[1:]!=(2,3) or not np.isfinite(moves).all():
        raise ValueError('Expected finite XYZ segments')
    radius2=(diameter/2)**2
    for a,b in moves:
        d=b[:2]-a[:2];length2=float(d@d);offset=xy-a[:2]
        if length2==0:
            mask=np.sum(offset*offset,axis=1)<=radius2
            result[mask]=np.minimum(result[mask],min(a[2],b[2]))
            continue
        center=(offset@d)/length2
        distance2=np.maximum(0,np.sum(offset*offset,axis=1)-center*center*length2)
        mask=distance2<=radius2
        index=np.flatnonzero(mask)
        if not len(index):continue
        reach=np.sqrt(np.maximum(0,(radius2-distance2[index])/length2))
        lo=np.maximum(0,center[index]-reach);hi=np.minimum(1,center[index]+reach)
        valid=lo<=hi;index=index[valid];lo=lo[valid];hi=hi[valid]
        t=lo if b[2]>=a[2] else hi
        floor=a[2]+t*(b[2]-a[2])
        result[index]=np.minimum(result[index],floor)
    return result


def compare_sweeps(reference,generated,*,diameter,stock_top=0,spacing=.25,bounds=None):
    ref=np.asarray(reference,float);new=np.asarray(generated,float)
    if not math.isfinite(spacing) or spacing<=0:raise ValueError('Invalid grid spacing')
    if bounds is None:
        xy=np.concatenate([p.reshape(-1,3)[:,:2] for p in (ref,new) if len(p)])
        low=xy.min(axis=0)-diameter/2-spacing
        high=xy.max(axis=0)+diameter/2+spacing
    else:
        low,high=np.asarray(bounds,float)
    if low.shape!=(2,) or high.shape!=(2,) or not np.isfinite([low,high]).all() or np.any(high<=low):
        raise ValueError('Invalid grid bounds')
    with np.errstate(over='ignore'):
        requested=np.ceil((high-low)/spacing)
    if not np.isfinite(requested).all() or np.any(requested>250_000) or float(np.prod(requested))>250_000:
        raise ValueError('Grid limit: 250,000 query points')
    counts=requested.astype(int)
    # Full cells of width spacing, anchored at low. Last cell can extend past
    # requested high by < spacing; actual sampled rectangle is recorded.
    x=low[0]+(np.arange(counts[0])+.5)*spacing
    y=low[1]+(np.arange(counts[1])+.5)*spacing
    xx,yy=np.meshgrid(x,y);points=np.column_stack([xx.ravel(),yy.ravel()])
    old=swept_floor(points,ref,diameter=diameter,stock_top=stock_top)
    current=swept_floor(points,new,diameter=diameter,stock_top=stock_top)
    selected=(old<stock_top-1e-8)|(current<stock_top-1e-8)
    delta=current-old
    relevant=delta[selected]
    area=spacing**2
    summary={'units':'mm','grid_spacing_mm':spacing,'grid_points':len(points),
        'grid_shape_yx':[int(counts[1]),int(counts[0])],
        'sampled_bounds_mm':[low.tolist(),(low+counts*spacing).tolist()],
        'assumed_tool_diameter_mm':diameter,'assumed_uniform_stock_top_mm':stock_top,
        'selected_points_cut_by_either':int(selected.sum()),
        'reference_sampled_footprint_mm2':float(np.count_nonzero(old<stock_top-1e-8)*area),
        'generated_sampled_footprint_mm2':float(np.count_nonzero(current<stock_top-1e-8)*area),
        'reference_sampled_swept_volume_mm3':float(np.sum(stock_top-old)*area),
        'generated_sampled_swept_volume_mm3':float(np.sum(stock_top-current)*area),
        'generated_deeper_by_more_than_0_1_mm_points':int(np.count_nonzero(relevant<-.1)),
        'generated_shallower_by_more_than_0_1_mm_points':int(np.count_nonzero(relevant>.1)),
        'absolute_floor_difference_mm':{'median':float(np.median(abs(relevant))) if len(relevant) else 0,
            'p95':float(np.percentile(abs(relevant),95)) if len(relevant) else 0,
            'maximum':float(np.max(abs(relevant))) if len(relevant) else 0},
        'scope':'Discrete XY grid of swept flat-tip floors under a uniform stock top. '
                'No STL clipping, initial stock shape, holder, collision, material simulation or MeshCAM equivalence certificate.'}
    return summary,{'x':x,'y':y,'reference':old.reshape(xx.shape),
                    'generated':current.reshape(xx.shape),'delta':delta.reshape(xx.shape)}
