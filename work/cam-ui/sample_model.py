"""Small, original demonstration solid generated without user files."""
import struct


def pocket_plate_stl():
    """20 x 20 x 5 mm plate with a 10 x 10 x 2 mm blind pocket."""
    triangles=[]
    def quad(a,b,c,d):triangles.extend(((a,b,c),(a,c,d)))
    grid=(0.,5.,15.,20.)
    for i in range(3):
        for j in range(3):
            x0,x1=grid[i:i+2];y0,y1=grid[j:j+2]
            if (i,j)!=(1,1):quad((x0,y0,0),(x1,y0,0),(x1,y1,0),(x0,y1,0))
            quad((x0,y0,-5),(x0,y1,-5),(x1,y1,-5),(x1,y0,-5))
    outer=[(x,0.) for x in grid]+[(20.,y) for y in grid[1:]]
    outer += [(x,20.) for x in grid[-2::-1]]+[(0.,y) for y in grid[-2:0:-1]]
    def walls(loop,bottom,top):
        for a,b in zip(loop,loop[1:]+loop[:1]):
            quad((*a,bottom),(*b,bottom),(*b,top),(*a,top))
    walls(outer,-5.,0.)
    # Clockwise loop puts the inner wall normals into the pocket.
    walls([(5.,5.),(5.,15.),(15.,15.),(15.,5.)],-2.,0.)
    quad((5.,5.,-2.),(15.,5.,-2.),(15.,15.,-2.),(5.,15.,-2.))
    header=b'CAM Local - generated demonstration pocket plate'.ljust(80,b' ')
    return header+struct.pack('<I',len(triangles))+b''.join(
        struct.pack('<12fH',0,0,0,*(v for point in triangle for v in point),0)
        for triangle in triangles)
