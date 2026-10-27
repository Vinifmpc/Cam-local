"""Give clipped raster slivers a proved entry from their cleanup contour.

The short connector fits inside the expanded OCL contact disk at a cleanup
vertex. The lead follows an existing contact edge, at the same or higher Z.
No fixture/domain proof, stock-depth proof or central cutting is inferred.
"""
import copy
import math
from motion_planner import _branches,EPS


def extend_short_entries(layers,*,diameter,contact_diameter,stock_top,angle,contains):
    guard=(contact_diameter-diameter)/2-.005
    if guard<=0:return 0
    count=0;tangent=math.tan(math.radians(angle))
    for layer in layers:
        cleanups=[p['points'] for p in layer['polylines'] if p['kind']=='cleanup']
        for path in layer['polylines']:
            if path['kind']!='raster':continue
            points=path['points'];peak,branches=_branches(points)
            length=sum(math.dist(a[:2],b[:2]) for a,b in zip(branches[0][0],branches[0][0][1:]))
            if (stock_top-peak[2])<=500*tangent*length:continue
            # Reverse only a whole path whose highest point is an endpoint.
            if peak==points[-1]:points=points[::-1]
            elif peak!=points[0]:continue
            candidates=[]
            for contour in cleanups:
                for i,q in enumerate(contour):
                    distance=math.dist(q[:2],peak[:2])
                    if not 1e-7<distance<=guard or q[2]>peak[2]+EPS:continue
                    for j in (i-1,i+1):
                        if not 0<=j<len(contour):continue
                        u=contour[j]
                        if math.dist(u[:2],q[:2])<.01:continue
                        raised=[*q[:2],peak[2]]
                        if contains(raised,peak):candidates.append((distance,u,q,raised))
            if not candidates:continue
            _,u,q,raised=min(candidates,key=lambda c:c[0])
            path['entry_bridge']={'cleanup_edge':[copy.deepcopy(u),copy.deepcopy(q)],
                                  'original_points':copy.deepcopy(points)}
            path['points']=[copy.deepcopy(u),raised]+copy.deepcopy(points)
            count+=1
    return count


def validate_short_entries(layers,*,diameter,contact_diameter):
    if not any(p.get('entry_bridge') for layer in layers for p in layer['polylines']):return
    guard=(contact_diameter-diameter)/2-.005
    # References always name real primary cleanup edges, never generated
    # bridges, auxiliary passes or future geometric guesses.
    edges={tuple(sorted((tuple(a),tuple(b)))) for layer in layers
           for p in layer['polylines'] if p['kind']=='cleanup'
           for a,b in zip(p['points'],p['points'][1:])}
    for layer in layers:
        for path in layer['polylines']:
            proof=path.get('entry_bridge')
            if proof is None:continue
            try:
                u,q=proof['cleanup_edge'];original=proof['original_points'];peak=original[0]
                expected=[u,[*q[:2],peak[2]]]+original
                valid=(tuple(sorted((tuple(u),tuple(q)))) in edges and
                    1e-7<math.dist(q[:2],peak[:2])<=guard and q[2]<=peak[2]+EPS and
                    len(path['points'])==len(expected) and all(
                        a[:2]==b[:2] and a[2]>=b[2]-EPS
                        for a,b in zip(path['points'],expected)))
            except (KeyError,TypeError,ValueError,IndexError):valid=False
            if not valid:raise ValueError('Entrada curta sem prova do contato da fresa; recalcule')
