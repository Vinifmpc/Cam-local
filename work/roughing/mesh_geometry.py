"""Strict ASCII/binary STL import, explicit units, and rigid alignment.

STL normals are not trusted. Topology checks use exactly equal vertices;
they diagnose edge connectivity, not watertightness/self-intersection.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import numpy as np
import math
from cam_tools import unit_scale

MAX_TRIANGLES = 1_000_000
MAX_BYTES = 128 * 1024 * 1024


@dataclass
class Mesh:
    triangles: np.ndarray
    source_sha256: str
    rotation: list
    translation: list
    source_units: str = 'mm'
    source_format: str = 'binary'

    def summary(self):
        vertices = self.triangles.reshape(-1, 3)
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        return {'source_sha256': self.source_sha256, 'source_units': self.source_units,
                'source_format': self.source_format, 'units': 'mm',
                'triangle_count': len(self.triangles),
                'bounds_mm': {'minimum': low.tolist(), 'maximum': high.tolist(),
                              'size': (high-low).tolist()},
                'transform': {'rotation': self.rotation, 'translation_mm': self.translation,
                              'equation': 'p_mm = rotation @ (p_stl * unit_scale) + translation_mm'}}


def _alignment(rotation, translation):
    matrix=np.asarray(rotation if rotation is not None else np.eye(3),dtype=float)
    offset=np.asarray(translation if translation is not None else [0,0,0],dtype=float)
    if matrix.shape!=(3,3) or offset.shape!=(3,) or not np.isfinite(matrix).all() or not np.isfinite(offset).all():
        raise ValueError('Invalid rigid alignment')
    if not np.allclose(matrix@matrix.T,np.eye(3),atol=1e-10,rtol=0) or abs(np.linalg.det(matrix)-1)>1e-10:
        raise ValueError('Rotation must preserve lengths and handedness')
    return matrix, offset


def _binary(data):
    if len(data)<84:
        raise ValueError('Expected binary STL with an 84-byte header')
    count=int.from_bytes(data[80:84],'little')
    if not 0<count<=MAX_TRIANGLES or len(data)!=84+count*50:
        raise ValueError('Invalid binary STL size, empty mesh or triangle limit exceeded')
    dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')])
    return np.frombuffer(data,dtype=dtype,count=count,offset=84)['vertices'].astype(float)


def _ascii(data):
    try:
        lines=iter(line.strip() for line in data.decode('utf-8-sig').splitlines() if line.strip())
    except UnicodeDecodeError as error:
        raise ValueError('STL ASCII com codificação inválida') from error
    triangles=[]; opened=False
    def expect(word):
        line=next(lines)
        if line.lower()!=word:
            raise ValueError('STL ASCII: esperado '+word)
    try:
        for line in lines:
            tokens=line.split(); keyword=tokens[0].lower()
            if keyword=='solid' and not opened:
                opened=True
            elif keyword=='endsolid' and opened:
                opened=False
            elif keyword=='facet' and opened:
                if len(tokens)!=5 or tokens[1].lower()!='normal' or not all(math.isfinite(float(x)) for x in tokens[2:]):
                    raise ValueError('STL ASCII: normal inválida')
                expect('outer loop'); triangle=[]
                for _ in range(3):
                    tokens=next(lines).split()
                    if len(tokens)!=4 or tokens[0].lower()!='vertex':
                        raise ValueError('STL ASCII: esperado vertex x y z')
                    triangle.append([float(x) for x in tokens[1:]])
                expect('endloop'); expect('endfacet')
                triangles.append(triangle)
                if len(triangles)>MAX_TRIANGLES:
                    raise ValueError('Limite de triângulos excedido')
            else:
                raise ValueError('STL ASCII: estrutura inválida')
    except StopIteration as error:
        raise ValueError('STL ASCII truncado') from error
    if opened or not triangles:
        raise ValueError('STL ASCII vazio ou sem endsolid')
    return np.asarray(triangles, float)


def _load(path, units, rotation, translation, binary_only=False):
    path=Path(path)
    if path.stat().st_size>MAX_BYTES:
        raise ValueError('STL excede o limite de 128 MiB')
    data=path.read_bytes()
    binary_size=(len(data)>=84 and len(data)==84+int.from_bytes(data[80:84],'little')*50)
    fmt='binary' if binary_only or binary_size else 'ascii'
    triangles=_binary(data) if fmt=='binary' else _ascii(data)
    matrix,offset=_alignment(rotation,translation)
    triangles=(triangles*unit_scale(units))@matrix.T+offset
    if not np.isfinite(triangles).all():
        raise ValueError('Non-finite STL vertices')
    area=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]),axis=1)
    if not np.isfinite(area).all() or np.any(area==0):
        raise ValueError('STL com triângulos degenerados ou dimensões fora da faixa numérica')
    return Mesh(triangles,hashlib.sha256(data).hexdigest(),matrix.tolist(),offset.tolist(),units,fmt)


def read_stl(path, *, units, rotation=None, translation=None):
    """No unit guessing; translation is always in millimetres after scaling."""
    return _load(path, units, rotation, translation)


def read_binary_stl(path, rotation=None, translation=None):
    """Compatibility wrapper for earlier millimetre-only experiments."""
    return _load(path, 'mm', rotation, translation, binary_only=True)


def place_stl(path, *, units, rotation=None, xy_origin='keep', z_origin='keep', translation_mm=(0,0,0)):
    """Rotate, anchor bounds, then apply explicit extra translation in mm.

    xy: keep / minimum (lower-left=0) / center. z: keep / top (max=0) / bottom.
    Does not guess the machining side or rotate based on dimensions.
    """
    if xy_origin not in ('keep','minimum','center') or z_origin not in ('keep','top','bottom'):
        raise ValueError('Origem XY/Z inválida')
    mesh=read_stl(path,units=units,rotation=rotation)
    low=mesh.triangles.reshape(-1,3).min(axis=0)
    high=mesh.triangles.reshape(-1,3).max(axis=0)
    _,shift=_alignment(None,translation_mm)
    shift=shift.copy()
    if xy_origin=='minimum':shift[:2]-=low[:2]
    if xy_origin=='center':shift[:2]-=(low[:2]+high[:2])/2
    if z_origin=='top':shift[2]-=high[2]
    if z_origin=='bottom':shift[2]-=low[2]
    mesh.triangles+=shift; mesh.translation=shift.tolist()
    return mesh


def topology_report(mesh):
    """Exact vertex edge diagnostic only; never silently weld/repair a mesh."""
    flat=mesh.triangles.reshape(-1,3)
    vertices,ids=np.unique(flat,axis=0,return_inverse=True)
    faces=ids.reshape(-1,3)
    directed=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    edges=np.sort(directed,axis=1)
    _,inverse,counts=np.unique(edges,axis=0,return_inverse=True,return_counts=True)
    signs=np.where(directed[:,0]<directed[:,1],1,-1)
    balance=np.bincount(inverse,weights=signs,minlength=len(counts))
    boundary=int(np.count_nonzero(counts==1))
    nonmanifold=int(np.count_nonzero(counts>2))
    inconsistent=int(np.count_nonzero((counts==2)&(balance!=0)))
    _,duplicates=np.unique(np.sort(faces,axis=1),axis=0,return_counts=True)
    return {'unique_vertices':len(vertices),'boundary_edges':boundary,
            'nonmanifold_edges':nonmanifold,'inconsistent_winding_edges':inconsistent,
            'duplicate_faces':int(np.sum(duplicates-1)),
            'closed_consistent_edges':boundary==0 and nonmanifold==0 and inconsistent==0,
            'scope':'Igualdade exata de vértices; não verifica autointerseções nem certifica sólido fechado'}
