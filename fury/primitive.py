"""Module dedicated for basic primitive."""
import math
from os.path import join as pjoin
from packaging.version import parse

import numpy as np
from scipy.spatial import ConvexHull, transform
from scipy.version import short_version

from fury.data import DATA_DIR
from fury.transform import cart2sphere
from fury.utils import fix_winding_order

SCIPY_1_4_PLUS = parse(short_version) >= parse('1.4.0')

SPHERE_FILES = {
    'symmetric362': pjoin(DATA_DIR, 'evenly_distributed_sphere_362.npz'),
    'symmetric642': pjoin(DATA_DIR, 'evenly_distributed_sphere_642.npz'),
    'symmetric724': pjoin(DATA_DIR, 'evenly_distributed_sphere_724.npz'),
    'repulsion724': pjoin(DATA_DIR, 'repulsion724.npz'),
    'repulsion100': pjoin(DATA_DIR, 'repulsion100.npz'),
    'repulsion200': pjoin(DATA_DIR, 'repulsion200.npz')
}


def faces_from_sphere_vertices(vertices):
    """
    Triangulate a set of vertices on the sphere.

    Parameters
    ----------
    vertices : (M, 3) ndarray
        XYZ coordinates of vertices on the sphere.

    Returns
    -------
    faces : (N, 3) ndarray
        Indices into vertices; forms triangular faces.

    """
    hull = ConvexHull(vertices, qhull_options='Qbb Qc')
    faces = np.ascontiguousarray(hull.simplices)
    if len(vertices) < 2 ** 16:
        return np.asarray(faces, np.uint16)
    else:
        return faces


def repeat_primitive_function(func, centers, func_args=[],
                              directions=(1, 0, 0), colors=(1, 0, 0),
                              scales=1):
    """Repeat Vertices and triangles of a specific primitive function.

    It could be seen as a glyph. The primitive function should generate and
    return vertices and faces

    Parameters
    ----------
    func : callable
        primitive functions
    centers : ndarray, shape (N, 3)
        Superquadrics positions
    func_args : args
        primitive functions arguments/parameters
    directions : ndarray, shape (N, 3) or tuple (3,), optional
        The orientation vector of the cone.
    colors : ndarray (N,3) or (N, 4) or tuple (3,) or tuple (4,)
        RGB or RGBA (for opacity) R, G, B and A should be at the range [0, 1]
    scales : ndarray, shape (N) or (N,3) or float or int, optional
        The height of the cone.

    Returns
    -------
    big_vertices: ndarray
        Expanded vertices at the centers positions
    big_triangles: ndarray
        Expanded triangles that composed our shape to duplicate
    big_colors : ndarray
        Expanded colors applied to all vertices/faces

    """
    # Get faces
    _, faces = func()
    if len(func_args) == 1:
        func_args = np.squeeze(np.array([func_args] * centers.shape[0]))
    elif len(func_args) != centers.shape[0]:
        raise IOError("sq_params should 1 or equal to the numbers \
                        of centers")

    vertices = np.concatenate([func(i)[0] for i in func_args])
    return repeat_primitive(vertices=vertices, faces=faces, centers=centers,
                            directions=directions, colors=colors,
                            scales=scales, have_tiled_verts=True)


def repeat_primitive(vertices, faces, centers, directions=None,
                     colors=(1, 0, 0), scales=1, have_tiled_verts=False):
    """Repeat Vertices and triangles of a specific primitive shape.

    It could be seen as a glyph.

    Parameters
    ----------
    vertices: ndarray
        vertices coords to duplicate at the centers positions
    triangles: ndarray
        triangles that composed our shape to duplicate
    centers : ndarray, shape (N, 3)
        Superquadrics positions
    directions : ndarray, shape (N, 3) or tuple (3,), optional
        The orientation vector of the cone.
    colors : ndarray (N,3) or (N, 4) or tuple (3,) or tuple (4,)
        RGB or RGBA (for opacity) R, G, B and A should be at the range [0, 1]
    scales : ndarray, shape (N) or (N,3) or float or int, optional
        The height of the cone.
    have_tiled_verts : bool
        option to control if we need to duplicate vertices of a shape or not

    Returns
    -------
    big_vertices: ndarray
        Expanded vertices at the centers positions
    big_triangles: ndarray
        Expanded triangles that composed our shape to duplicate
    big_colors : ndarray
        Expanded colors applied to all vertices/faces
    big_centers : ndarray
        Expanded centers for all vertices/faces

    """
    # duplicated vertices if needed
    if not have_tiled_verts:
        vertices = np.tile(vertices, (centers.shape[0], 1))
    big_vertices = vertices
    # Get unit shape
    unit_verts_size = vertices.shape[0] // centers.shape[0]
    unit_triangles_size = faces.shape[0]

    # scale them
    if not isinstance(scales, np.ndarray):
        scales = np.array(scales)
    if scales.ndim == 1:
        if scales.size == centers.shape[0]:
            scales = np.repeat(scales, unit_verts_size, axis=0)
            scales = scales.reshape((big_vertices.shape[0], 1))
    elif scales.ndim == 2:
        scales = np.repeat(scales, unit_verts_size, axis=0)
    big_vertices *= scales

    # update triangles
    big_triangles = np.array(np.tile(faces,
                                     (centers.shape[0], 1)),
                             dtype=np.int32)
    big_triangles += np.repeat(np.arange(0,
                                         centers.shape[0] * unit_verts_size,
                                         step=unit_verts_size),
                               unit_triangles_size,
                               axis=0).reshape((big_triangles.shape[0],
                                                1))

    def normalize_input(arr, arr_name=''):
        if isinstance(arr, (tuple, list, np.ndarray)) and len(arr) in [3, 4] \
                and not all(isinstance(i, (list, tuple, np.ndarray))
                            for i in arr):
            return np.array([arr] * centers.shape[0])
        elif isinstance(arr, np.ndarray) and len(arr) == 1:
            return np.repeat(arr, centers.shape[0], axis=0)
        elif arr is None:
            return np.array([])
        elif len(arr) != len(centers):
            msg = "{} size should be 1 or ".format(arr_name)
            msg += "equal to the numbers of centers"
            raise IOError(msg)
        else:
            return np.array(arr)

    # update colors
    colors = normalize_input(colors, 'colors')
    big_colors = np.repeat(colors, unit_verts_size, axis=0)
    big_colors *= 255

    # update orientations
    directions = normalize_input(directions, 'directions')
    for pts, dirs in enumerate(directions):
        w = np.cos(0.5 * np.pi)
        denom = np.linalg.norm(dirs / 2.)
        f = (np.sin(0.5 * np.pi) / denom) if denom else 0
        dirs = np.append((dirs / 2.) * f, w)
        rot = transform.Rotation.from_quat(dirs)
        rotation_matrix = rot.as_matrix() if SCIPY_1_4_PLUS else rot.as_dcm()

        big_vertices[pts * unit_verts_size: (pts + 1) * unit_verts_size] = \
            np.dot(rotation_matrix[:3, :3],
                   big_vertices[pts * unit_verts_size:
                                (pts + 1) * unit_verts_size].T).T

    # apply centers position
    big_centers = np.repeat(centers, unit_verts_size, axis=0)
    big_vertices += big_centers

    return big_vertices, big_triangles, big_colors, big_centers


def prim_square():
    """Return vertices and triangles for a square geometry.

    Returns
    -------
    vertices: ndarray
        4 vertices coords that composed our square
    triangles: ndarray
        2 triangles that composed our square

    """
    vertices = np.array([[-.5, -.5, 0.0],
                         [-.5, 0.5, 0.0],
                         [0.5, 0.5, 0.0],
                         [0.5, -.5, 0.0]])
    triangles = np.array([[0, 1, 2],
                          [2, 3, 0]], dtype='i8')
    return vertices, triangles


def prim_box():
    """Return vertices and triangle for a box geometry.

    Returns
    -------
    vertices: ndarray
        8 vertices coords that composed our box
    triangles: ndarray
        12 triangles that composed our box

    """
    vertices = np.array([[-.5, -.5, -.5],
                         [-.5, -.5, 0.5],
                         [-.5, 0.5, -.5],
                         [-.5, 0.5, 0.5],
                         [0.5, -.5, -.5],
                         [0.5, -.5, 0.5],
                         [0.5, 0.5, -.5],
                         [0.5, 0.5, 0.5]])
    triangles = np.array([[0, 6, 4],
                          [0, 2, 6],
                          [0, 3, 2],
                          [0, 1, 3],
                          [2, 7, 6],
                          [2, 3, 7],
                          [4, 6, 7],
                          [4, 7, 5],
                          [0, 4, 5],
                          [0, 5, 1],
                          [1, 5, 7],
                          [1, 7, 3]], dtype='i8')
    return vertices, triangles


def prim_sphere(name='symmetric362', gen_faces=False):
    """Provide vertices and triangles of the spheres.

    Parameters
    ----------
    name : str
        which sphere - one of:
        * 'symmetric362'
        * 'symmetric642'
        * 'symmetric724'
        * 'repulsion724'
        * 'repulsion100'
        * 'repulsion200'
    gen_faces : bool, optional
        If True, triangulate a set of vertices on the sphere to get the faces.
        Otherwise, we load the saved faces from a file. Default: False

    Returns
    -------
    vertices: ndarray
        vertices coords that composed our sphere
    triangles: ndarray
        triangles that composed our sphere

    Examples
    --------
    >>> import numpy as np
    >>> from fury.primitive import prim_sphere
    >>> verts, faces = prim_sphere('symmetric362')
    >>> verts.shape == (362, 3)
    True
    >>> faces.shape == (720, 3)
    True

    """
    fname = SPHERE_FILES.get(name)
    if fname is None:
        raise ValueError('No sphere called "%s"' % name)
    res = np.load(fname)

    verts = res['vertices'].copy()
    faces = faces_from_sphere_vertices(verts) if gen_faces else res['faces']
    faces = fix_winding_order(res['vertices'], faces, clockwise=True)
    return res['vertices'], faces


def prim_superquadric(roundness=(1, 1), sphere_name='symmetric362'):
    """Provide vertices and triangles of a superquadrics.

    Parameters
    ----------
    roundness : tuple, optional
        parameters (Phi and Theta) that control the shape of the superquadric

    sphere_name : str, optional
        which sphere - one of:
        * 'symmetric362'
        * 'symmetric642'
        * 'symmetric724'
        * 'repulsion724'
        * 'repulsion100'
        * 'repulsion200'

    Returns
    -------
    vertices: ndarray
        vertices coords that composed our sphere
    triangles: ndarray
        triangles that composed our sphere

    Examples
    --------
    >>> import numpy as np
    >>> from fury.primitive import prim_superquadric
    >>> verts, faces = prim_superquadric(roundness=(1, 1))
    >>> verts.shape == (362, 3)
    True
    >>> faces.shape == (720, 3)
    True

    """

    def _fexp(x, p):
        """Return a different kind of exponentiation."""
        return np.sign(x) * (np.abs(x) ** p)

    sphere_verts, sphere_triangles = prim_sphere(sphere_name)
    _, sphere_phi, sphere_theta = cart2sphere(*sphere_verts.T)

    phi, theta = roundness
    x = _fexp(np.sin(sphere_phi), phi) * _fexp(np.cos(sphere_theta), theta)
    y = _fexp(np.sin(sphere_phi), phi) * _fexp(np.sin(sphere_theta), theta)
    z = _fexp(np.cos(sphere_phi), phi)
    xyz = np.vstack([x, y, z]).T

    vertices = np.ascontiguousarray(xyz)

    return vertices, sphere_triangles


def prim_tetrahedron():
    """Return vertices and triangles for a tetrahedron.

    This shape has a side length of two units.

    Returns
    -------
    pyramid_vert: numpy.ndarray
        4 vertices coordinates
    triangles: numpy.ndarray
        4 triangles representing the tetrahedron

    """
    pyramid_vert = np.array([[0.5, 0.5, 0.5],
                             [0.5, -0.5, -0.5],
                             [-0.5, 0.5, -0.5],
                             [-0.5, -0.5, 0.5]])

    pyramid_triag = np.array([[2, 0, 1],
                              [0, 3, 2],
                              [0, 3, 1],
                              [1, 2, 3]], dtype='i8')

    return pyramid_vert, pyramid_triag


def prim_icosahedron():
    """Return vertices and triangles for icosahedron.

    Returns
    -------
    icosahedron_vertices: numpy.ndarray
        12 vertices coordinates to the icosahedron
    icosahedron_mesh: numpy.ndarray
        20 triangles representing the tetrahedron

    """
    phi = (1 + math.sqrt(5)) / 2.0

    icosahedron_vertices = np.array([[-1.0, 0.0, phi],
                                     [0.0, phi, 1.0],
                                     [1.0, 0.0, phi],
                                     [-phi, 1.0, 0.0],
                                     [0.0, phi, -1.0],
                                     [phi, 1.0, 0.0],
                                     [-phi, -1.0, 0.0],
                                     [0.0, -phi, 1.0],
                                     [phi, -1.0, 0.0],
                                     [-1.0, 0.0, -phi],
                                     [0.0, -phi, -1.0],
                                     [1.0, 0.0, -phi]])

    icosahedron_mesh = np.array([[1, 0, 2],
                                 [2, 5, 1],
                                 [5, 4, 1],
                                 [3, 1, 4],
                                 [0, 1, 3],
                                 [0, 6, 3],
                                 [9, 3, 6],
                                 [8, 2, 7],
                                 [2, 0, 7],
                                 [0, 7, 6],
                                 [5, 2, 8],
                                 [11, 5, 8],
                                 [11, 4, 5],
                                 [9, 11, 4],
                                 [4, 3, 9],
                                 [11, 10, 8],
                                 [8, 10, 7],
                                 [6, 7, 10],
                                 [10, 9, 6],
                                 [9, 10, 11]], dtype='i8')

    return icosahedron_vertices, icosahedron_mesh


def prim_rhombicuboctahedron():
    """Return vertices and triangles for rhombicuboctahedron.

    Returns
    -------
    vertices: numpy.ndarray
        24 vertices coordinates to the rhombicuboctahedron
    triangles: numpy.ndarray
        44 triangles representing the rhombicuboctahedron

    """
    phi = (math.sqrt(2) - 1) / 2.0

    vertices = np.array([[0.5, phi, phi],
                         [0.5, phi, -phi],
                         [0.5, -phi, phi],
                         [0.5, -phi, -phi],
                         [phi, 0.5, phi],
                         [phi, 0.5, -phi],
                         [-phi, 0.5, phi],
                         [-phi, 0.5, -phi],
                         [phi, phi, 0.5],
                         [phi, -phi, 0.5],
                         [-phi, phi, 0.5],
                         [-phi, -phi, 0.5],
                         [-0.5, phi, phi],
                         [-0.5, phi, -phi],
                         [-0.5, -phi, phi],
                         [-0.5, -phi, -phi],
                         [phi, -0.5, phi],
                         [phi, -0.5, -phi],
                         [-phi, -0.5, phi],
                         [-phi, -0.5, -phi],
                         [phi, phi, -0.5],
                         [phi, -phi, -0.5],
                         [-phi, phi, -0.5],
                         [-phi, -phi, -0.5]])

    triangles = np.array([[0, 1, 2],
                          [1, 3, 2],
                          [0, 4, 5],
                          [0, 5, 1],
                          [6, 4, 7],
                          [4, 5, 7],
                          [0, 8, 4],
                          [0, 2, 8],
                          [2, 9, 8],
                          [8, 9, 10],
                          [9, 11, 10],
                          [6, 8, 10],
                          [6, 8, 4],
                          [6, 10, 12],
                          [6, 12, 7],
                          [7, 12, 13],
                          [10, 11, 14],
                          [10, 14, 12],
                          [12, 14, 15],
                          [12, 15, 13],
                          [2, 3, 16],
                          [3, 17, 16],
                          [2, 16, 9],
                          [9, 16, 11],
                          [11, 16, 18],
                          [18, 16, 19],
                          [16, 17, 19],
                          [11, 18, 14],
                          [14, 18, 19],
                          [14, 19, 15],
                          [1, 21, 3],
                          [1, 20, 21],
                          [3, 21, 17],
                          [17, 21, 23],
                          [17, 23, 19],
                          [21, 20, 23],
                          [23, 20, 22],
                          [19, 23, 15],
                          [15, 23, 13],
                          [13, 23, 22],
                          [13, 22, 7],
                          [22, 7, 5],
                          [22, 20, 5],
                          [20, 1, 5]], dtype='i8')

    triangles = fix_winding_order(vertices, triangles, clockwise=True)

    return vertices, triangles


def prim_star(dim=2):
    """Return vertices and triangle for star geometry.

    Parameters
    ----------
    dim: int
        Represents the dimension of the wanted star

    Returns
    -------
    vertices: ndarray
        vertices coords that composed our star
    triangles: ndarray
        Triangles that composed our star

    """
    if dim == 2:
        vert = np.array([[-2.0, -3.0, 0.0],
                         [0.0, -2.0, 0.0],
                         [3.0, -3.0, 0.0],
                         [2.0, -1.0, 0.0],
                         [3.0, 1.0, 0.0],
                         [1.0, 1.0, 0.0],
                         [0.0, 3.0, 0.0],
                         [-1.0, 1.0, 0.0],
                         [-3.0, 1.0, 0.0],
                         [-2.0, -1.0, 0.0]])

        triangles = np.array([[1, 9, 0],
                              [1, 2, 3],
                              [3, 4, 5],
                              [5, 6, 7],
                              [7, 8, 9],
                              [1, 9, 3],
                              [3, 7, 9],
                              [3, 5, 7]], dtype='i8')

    if dim == 3:
        vert = np.array([[-2.0, -3.0, 0.0],
                         [0.0, -2, 0.0],
                         [3.0, -3.0, 0.0],
                         [2.0, -1.0, 0.0],
                         [3.0, 0.5, 0.0],
                         [1.0, 0.5, 0.0],
                         [0, 3.0, 0.0],
                         [-1.0, 0.5, 0.0],
                         [-3.0, 0.5, 0.0],
                         [-2.0, -1.0, 0.0],
                         [0.0, 0.0, 0.5],
                         [0.0, 0.0, -0.5]])
        triangles = np.array([[1, 9, 0],
                              [1, 2, 3],
                              [3, 4, 5],
                              [5, 6, 7],
                              [7, 8, 9],
                              [1, 9, 3],
                              [3, 7, 9],
                              [3, 5, 7],
                              [1, 0, 10],
                              [0, 9, 10],
                              [10, 9, 8],
                              [7, 8, 10],
                              [6, 7, 10],
                              [5, 6, 10],
                              [5, 10, 4],
                              [10, 3, 4],
                              [3, 10, 2],
                              [10, 1, 2],
                              [1, 0, 11],
                              [0, 9, 11],
                              [11, 9, 8],
                              [7, 8, 10],
                              [6, 7, 11],
                              [5, 6, 11],
                              [5, 10, 4],
                              [11, 3, 4],
                              [3, 11, 2],
                              [11, 1, 2]], dtype='i8')
    return vert, triangles


def prim_triangularprism():
    """Return vertices and triangle for a regular triangular prism.

    Returns
    -------
    vertices: ndarray
        vertices coords that compose our prism
    triangles: ndarray
        triangles that compose our prism

    """
    # Local variable to represent the square root of three rounded
    # to 7 decimal places
    three = float('{:.7f}'.format(math.sqrt(3)))
    vertices = np.array([[0, -1/three, 1/2],
                        [-1/2, 1/2/three, 1/2],
                        [1/2, 1/2/three, 1/2],
                        [-1/2, 1/2/three, -1/2],
                        [1/2, 1/2/three, -1/2],
                        [0, -1/three, -1/2]])
    triangles = np.array([[0, 1, 2],
                         [2, 1, 3],
                         [2, 3, 4],
                         [1, 0, 5],
                         [1, 5, 3],
                         [0, 2, 4],
                         [0, 4, 5],
                         [5, 4, 3]])
    triangles = fix_winding_order(vertices, triangles, clockwise=True)
    return vertices, triangles


def prim_pentagonalprism():
    """Return vertices and triangles for a pentagonal prism.

    Returns
    -------
    vertices: ndarray
        vertices coords that compose our prism
    triangles: ndarray
        triangles that compose our prism

    """
    # Local variable to represent the square root of five
    five = math.sqrt(5)
    onec = (five - 1) / 4.0
    twoc = (five + 1) / 4.0
    sone = (math.sqrt(10 + (2 * five))) / 4.0
    stwo = (math.sqrt(10 - (2 * five))) / 4.0

    vertices = np.array([[stwo/2, twoc/2, -0.5],
                         [sone/2, -onec/2, -0.5],
                         [0, -1/2, -0.5],
                         [-sone/2, -onec/2, -0.5],
                         [-stwo/2, twoc/2, -0.5],
                         [stwo/2, twoc/2, 0.5],
                         [sone/2, -onec/2, 0.5],
                         [0, -1/2, 0.5],
                         [-sone/2, -onec/2, 0.5],
                         [-stwo/2, twoc/2, 0.5]])
    triangles = np.array([[9, 5, 4],
                          [4, 5, 0],
                          [5, 6, 0],
                          [0, 6, 1],
                          [6, 7, 1],
                          [1, 7, 2],
                          [7, 8, 2],
                          [2, 8, 3],
                          [8, 9, 3],
                          [3, 9, 4],
                          [0, 1, 4],
                          [1, 4, 3],
                          [1, 3, 2],
                          [5, 6, 9],
                          [6, 8, 9],
                          [6, 7, 8]])
    triangles = fix_winding_order(vertices, triangles, clockwise=True)
    return vertices, triangles


def prim_octagonalprism():
    """Return vertices and triangle for an octagonal prism.

    Returns
    -------
    vertices: ndarray
        vertices coords that compose our prism
    triangles: ndarray
        triangles that compose our prism

    """
    # Local variable to represent the square root of two rounded
    # to 7 decimal places
    two = float('{:.7f}'.format(math.sqrt(2)))

    vertices = np.array([[-1, -(1 + two), -1],
                         [1, -(1 + two), -1],
                         [1, (1 + two), -1],
                         [-1, (1 + two), -1],
                         [-(1 + two), -1, -1],
                         [(1 + two), -1, -1],
                         [(1 + two), 1, -1],
                         [-(1 + two), 1, -1],
                         [-1, -(1 + two), 1],
                         [1, -(1 + two), 1],
                         [1, (1 + two), 1],
                         [-1, (1 + two), 1],
                         [-(1 + two), -1, 1],
                         [(1 + two), -1, 1],
                         [(1 + two), 1, 1],
                         [-(1 + two), 1, 1]])
    triangles = np.array([[0, 8, 9],
                          [9, 1, 0],
                          [5, 13, 9],
                          [9, 1, 5],
                          [3, 11, 10],
                          [10, 2, 3],
                          [2, 10, 14],
                          [14, 6, 2],
                          [5, 13, 14],
                          [14, 6, 5],
                          [7, 15, 11],
                          [11, 3, 7],
                          [7, 15, 12],
                          [12, 4, 7],
                          [0, 8, 12],
                          [12, 4, 0],
                          [0, 3, 4],
                          [3, 4, 7],
                          [0, 3, 1],
                          [1, 2, 3],
                          [2, 5, 6],
                          [5, 2, 1],
                          [8, 11, 12],
                          [11, 12, 15],
                          [8, 11, 9],
                          [9, 10, 11],
                          [10, 13, 14],
                          [13, 10, 9]], dtype='u8')
    vertices /= 4
    triangles = fix_winding_order(vertices, triangles, clockwise=True)
    return vertices, triangles


def prim_frustum():
    """Return vertices and triangle for a square frustum prism.

    Returns
    -------
    vertices: ndarray
        vertices coords that compose our prism
    triangles: ndarray
        triangles that compose our prism

    """
    vertices = np.array([[-.5, -.5, .5],
                         [.5, -.5, .5],
                         [.5, .5, .5],
                         [-.5, .5, .5],
                         [-1, -1, -.5],
                         [1, -1, -.5],
                         [1, 1, -.5],
                         [-1, 1, -.5]])
    triangles = np.array([[4, 6, 5],
                          [6, 4, 7],
                          [0, 2, 1],
                          [2, 0, 3],
                          [4, 3, 0],
                          [3, 4, 7],
                          [7, 2, 3],
                          [2, 7, 6],
                          [6, 1, 2],
                          [1, 6, 5],
                          [5, 0, 1],
                          [0, 5, 4]], dtype='u8')
    vertices /= 2
    triangles = fix_winding_order(vertices, triangles, clockwise=True)
    return vertices, triangles


def prim_cylinder(radius=0.5, height=1, sectors=36, capped=True):
    """Return vertices and triangles for a cylinder.

    Parameters
    ----------
    radius: float
        Radius of the cylinder
    height: float
        Height of the cylinder
    sectors: int
        Sectors in the cylinder
    capped: bool
        Whether the cylinder is capped at both ends or open

    Returns
    -------
    vertices: ndarray
        vertices coords that compose our cylinder
    triangles: ndarray
        triangles that compose our cylinder
    """

    if not isinstance(sectors, int):
        raise TypeError("Only integers are allowed for sectors parameter")
    if not sectors > 7:
        raise ValueError("Sectors parameter should be greater than 7")
    sector_step = 2 * math.pi / sectors
    unit_circle_vertices = []

    # generate a unit circle on XY plane
    for i in range(sectors + 1):
        sector_angle = i * sector_step
        unit_circle_vertices.append(math.cos(sector_angle))
        unit_circle_vertices.append(0)
        unit_circle_vertices.append(math.sin(sector_angle))

    vertices = []
    # generate vertices for a cylinder
    for i in range(2):
        h = -height / 2 + i * height
        k = 0
        for j in range(sectors + 1):
            ux = unit_circle_vertices[k]
            uz = unit_circle_vertices[k + 2]
            # position vector
            vertices.append(ux * radius)
            vertices.append(h)
            vertices.append(uz * radius)
            k += 3

    # base and top circle vertices
    base_center_index = None
    top_center_index = None

    if capped:
        base_center_index = int(len(vertices) / 3)
        top_center_index = base_center_index + sectors + 1

        for i in range(2):
            h = -height / 2 + i * height
            vertices.append(0)
            vertices.append(h)
            vertices.append(0)
            k = 0
            for j in range(sectors):
                ux = unit_circle_vertices[k]
                uz = unit_circle_vertices[k + 2]
                # position vector
                vertices.append(ux * radius)
                vertices.append(h)
                vertices.append(uz * radius)
                k += 3

    if capped:
        vertices = (np.array(vertices).reshape(
            2 * (sectors + 1) + 2 * sectors + 2, 3))
    else:
        vertices = (np.array(vertices).reshape(2 * (sectors + 1), 3))

    triangles = []
    k1 = 0
    k2 = sectors + 1

    # triangles for the side surface
    for i in range(sectors):
        triangles.append(k1)
        triangles.append(k2)
        triangles.append(k1 + 1)

        triangles.append(k2)
        triangles.append(k2 + 1)
        triangles.append(k1 + 1)
        k1 += 1
        k2 += 1

    if capped:
        k = base_center_index + 1
        for i in range(sectors):
            if i < sectors - 1:
                triangles.append(base_center_index)
                triangles.append(k)
                triangles.append(k + 1)
            else:
                triangles.append(base_center_index)
                triangles.append(k)
                triangles.append(base_center_index + 1)
            k += 1

        k = top_center_index + 1
        for i in range(sectors):
            if i < sectors - 1:
                triangles.append(top_center_index)
                triangles.append(k + 1)
                triangles.append(k)
            else:
                triangles.append(top_center_index)
                triangles.append(top_center_index + 1)
                triangles.append(k)
            k += 1

    if capped:
        triangles = (np.array(triangles).reshape(4 * sectors, 3))
    else:
        triangles = (np.array(triangles).reshape(2 * sectors, 3))

    return vertices, triangles
