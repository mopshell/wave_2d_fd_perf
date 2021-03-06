"""Propagate a 2D wavefield using different implementations of a
finite difference method so that runtimes can be compared.
"""
from ctypes import c_int, c_float
import numpy as np
import torch
import wave_2d_fd_perf
from wave_2d_fd_perf import libvf1_O2_gcc, libvf1_O3_gcc, libvf1_Ofast_gcc, libvf2_Ofast_gcc, libvf3_Ofast_gcc, libvf4_Ofast_gcc, libvf5_Ofast_gcc, libvf6_Ofast_gcc, libvf6_Ofast_autopar_gcc, vcython1, vcython2


def alloc_aligned(m, n, k, dtype, align):
    """
    Allocate m x n elements of type dtype so kth element has alignment align.
    """

    dtype = np.dtype(dtype)
    numbytes = m * n * dtype.itemsize
    a = np.zeros(numbytes + (align - 1), dtype=np.uint8)
    data_align = (a.ctypes.data + k * dtype.itemsize) % align
    offset = 0 if data_align == 0 else (align - data_align)
    return a[offset : offset + numbytes].view(dtype).reshape(m, n)


class Propagator(object):
    """A finite difference propagator for the 2D wave equation.

       If align is not specified, the default value "1" will be used,
       which means no alignment will be done.
    """
    def __init__(self, model, pad, dx, dt=None, align=None):

        if align is None:
            align = 1

        self.nx = model.shape[1]
        self.ny = model.shape[0]
        self.dx = np.float32(dx)

        max_vel = np.max(model)
        if dt:
            self.dt = dt
        else:
            self.dt = 0.6 * self.dx / max_vel

        # calculate trailing padding in x dimension so that row
        # length is a multiple of align, at least 8
        align32 = int(np.ceil(align / np.dtype(np.float32).itemsize)) # align in float size
        nx_padded = int(np.ceil((self.nx + 2 * pad)/align32)) * align32
        x_end_pad = nx_padded - (self.nx + pad)

        self.nx_padded = self.nx + pad + x_end_pad
        self.ny_padded = self.ny + 2 * pad

        self.model_padded = np.pad(model, ((pad, pad), (pad, x_end_pad)), 'edge')

        self.model_padded2_dt2 = alloc_aligned(self.ny_padded, self.nx_padded,
                                               pad, np.float32, align)
        self.model_padded2_dt2[:, :] = self.model_padded**2 * self.dt**2

        self.wavefield = [alloc_aligned(self.ny_padded, self.nx_padded, pad, np.float32, align),
                          alloc_aligned(self.ny_padded, self.nx_padded, pad, np.float32, align)
                         ]
        self.current_wavefield = self.wavefield[0]
        self.previous_wavefield = self.wavefield[1]


class VC(Propagator):
    """C implementations."""
    def __init__(self, libname, model, dx, dt=None, align=None):
        pad = 8
        super(VC, self).__init__(model, pad, dx, dt, align)
        #print(hex(self.current_wavefield.ctypes.data + 8 * np.dtype(np.float32).itemsize), flush=True)

        self._libvc = np.ctypeslib.load_library(libname,
                                                wave_2d_fd_perf.__path__[0])
        self._libvc.step.argtypes = \
                [np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS', 'WRITEABLE')),
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS', 'WRITEABLE')),
                 c_int, c_int, c_int,
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS')),
                 c_float,
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        flags=('C_CONTIGUOUS')),
                 np.ctypeslib.ndpointer(dtype=c_int, ndim=1,
                                        flags=('C_CONTIGUOUS')),
                 np.ctypeslib.ndpointer(dtype=c_int, ndim=1,
                                        flags=('C_CONTIGUOUS')),
                 c_int, c_int, c_int]

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        """Propagate wavefield."""

        num_sources = sources.shape[0]
        source_len = sources.shape[1]
        self._libvc.step(self.current_wavefield, self.previous_wavefield,
                         self.nx_padded, self.ny_padded, self.nx,
                         self.model_padded2_dt2, self.dx,
                         sources,
                         sources_x.astype(c_int), sources_y.astype(c_int),
                         num_sources, source_len, num_steps)

        if num_steps%2 != 0:
            tmp = self.current_wavefield
            self.current_wavefield = self.previous_wavefield
            self.previous_wavefield = tmp

        return self.current_wavefield[8 : 8 + self.ny, 8 : 8 + self.nx]


class VC_blocksize(VC):
    """C implementations with variable blocksize."""
    def __init__(self, libname, model, blocksize_y, blocksize_x, dx, dt=None, align=None):
        super(VC_blocksize, self).__init__(libname, model, dx, dt, align)
        self.blocksize_y = blocksize_y
        self.blocksize_x = blocksize_x

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        """Propagate wavefield."""

        num_sources = sources.shape[0]
        source_len = sources.shape[1]
        # V9a doesn't use blocksize_y, so only pass it if not None
        if self.blocksize_y:
            self._libvc.step(self.current_wavefield, self.previous_wavefield,
                             self.nx_padded, self.ny_padded, self.nx,
                             self.model_padded2_dt2, self.dx,
                             sources,
                             sources_x.astype(c_int), sources_y.astype(c_int),
                             num_sources, source_len,
                             num_steps, self.blocksize_y, self.blocksize_x)
        else:
            self._libvc.step(self.current_wavefield, self.previous_wavefield,
                             self.nx_padded, self.ny_padded, self.nx,
                             self.model_padded2_dt2, self.dx,
                             sources,
                             sources_x.astype(c_int), sources_y.astype(c_int),
                             num_sources, source_len,
                             num_steps, self.blocksize_x)


        if num_steps%2 != 0:
            tmp = self.current_wavefield
            self.current_wavefield = self.previous_wavefield
            self.previous_wavefield = tmp

        return self.current_wavefield[8 : 8 + self.ny, 8 : 8 + self.nx]


class VC_fxx(VC):
    """C implementations with allocated f_xx."""
    def __init__(self, libname, model, dx, dt=None, align=None):
        super(VC_fxx, self).__init__(libname, model, dx, dt, align)
        if align is None:
            align = 1
        self.f_xx = alloc_aligned(self.ny_padded, self.nx_padded, 8, np.float32, align)
        self._libvc.step.argtypes = \
                [np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS', 'WRITEABLE')),
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS', 'WRITEABLE')),
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS', 'WRITEABLE')),
                 c_int, c_int, c_int,
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        shape=(self.ny_padded, self.nx_padded),
                                        flags=('C_CONTIGUOUS')),
                 c_float,
                 np.ctypeslib.ndpointer(dtype=c_float, ndim=2,
                                        flags=('C_CONTIGUOUS')),
                 np.ctypeslib.ndpointer(dtype=c_int, ndim=1,
                                        flags=('C_CONTIGUOUS')),
                 np.ctypeslib.ndpointer(dtype=c_int, ndim=1,
                                        flags=('C_CONTIGUOUS')),
                 c_int, c_int, c_int]

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        """Propagate wavefield."""

        num_sources = sources.shape[0]
        source_len = sources.shape[1]
        self._libvc.step(self.current_wavefield, self.previous_wavefield,
                         self.f_xx,
                         self.nx_padded, self.ny_padded, self.nx,
                         self.model_padded2_dt2, self.dx,
                         sources,
                         sources_x.astype(c_int), sources_y.astype(c_int),
                         num_sources, source_len, num_steps)

        if num_steps%2 != 0:
            tmp = self.current_wavefield
            self.current_wavefield = self.previous_wavefield
            self.previous_wavefield = tmp

        return self.current_wavefield[8 : 8 + self.ny, 8 : 8 + self.nx]


class VF(Propagator):
    """Fortran implementations."""

    def __init__(self, model, dx, dt=None, align=None):
        pad = 8
        super(VF, self).__init__(model, pad, dx, dt, align)

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        """Propagate wavefield."""

        self.fstep(self.current_wavefield.T, self.previous_wavefield.T,
                   self.model_padded2_dt2.T, self.nx,
                   self.dx,
                   sources.T, sources_x, sources_y, num_steps)

        if num_steps%2 != 0:
            tmp = self.current_wavefield
            self.current_wavefield = self.previous_wavefield
            self.previous_wavefield = tmp

        return self.current_wavefield[8 : 8 + self.ny, 8 : 8 + self.nx]


class VCython(Propagator):
    """Cython implementations."""
    def __init__(self, module, model, dx, dt=None, align=None):
        pad = 8
        super(VCython, self).__init__(model, pad, dx, dt, align)

        self.fd_coeff = np.array([2*-924708642,
                                  538137600,
                                  -94174080,
                                  22830080,
                                  -5350800,
                                  1053696,
                                  -156800,
                                  15360,
                                  -735]) / 302702400 / dx**2
        self.fd_coeff = self.fd_coeff.astype(np.float32)
        self.stepfunc = module.step

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        """Propagate wavefield."""

        num_sources = sources.shape[0]
        source_len = sources.shape[1]
        self.stepfunc(self.current_wavefield, self.previous_wavefield,
                      self.nx_padded, self.ny_padded, self.nx,
                      self.model_padded2_dt2,
                      sources,
                      sources_x.astype(c_int), sources_y.astype(c_int),
                      num_sources, source_len, num_steps, self.fd_coeff)

        if num_steps%2 != 0:
            self.current_wavefield, self.previous_wavefield = \
                self.previous_wavefield, self.current_wavefield

        return self.current_wavefield[8 : 8 + self.ny, 8 : 8 + self.nx]


class VPytorch(Propagator):
    """PyTorch implementations."""
    def __init__(self, model, pad, dx, dt=None, align=None):
        super(VPytorch, self).__init__(model, pad, dx, dt, align)

        self.model = torch.from_numpy(self.model_padded2_dt2[np.newaxis,
                                                             np.newaxis])
        self.wfc = torch.from_numpy(self.current_wavefield[np.newaxis,
                                                           np.newaxis])
        self.wfp = torch.from_numpy(self.previous_wavefield[np.newaxis,
                                                            np.newaxis])
        self.fd_coeff = np.array([2*-924708642,
                                  538137600,
                                  -94174080,
                                  22830080,
                                  -5350800,
                                  1053696,
                                  -156800,
                                  15360,
                                  -735]) / 302702400 / dx**2
        self.fd_coeff = self.fd_coeff.astype(np.float32)
        self.kernel1d = torch.tensor(np.hstack([self.fd_coeff[::-1],
                                                self.fd_coeff[1:]]))
        self.kernel2d = torch.zeros(17, 17)
        self.kernel2d[8, :] = self.kernel1d
        self.kernel2d[:, 8] = self.kernel1d
        self.kernel1d[8] /= 2
        self.kernel1d = self.kernel1d.reshape(1, 1, 17)
        self.kernel2d = self.kernel2d.reshape(1, 1, 17, 17)
        self.fd_coeff = torch.tensor(self.fd_coeff)

        torch.backends.cudnn.benchmark = True


class VC1_O2_gcc(VC):
    """A C implementation with loop in Laplacian."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC1_O2_gcc, self).__init__('libvc1_O2_gcc', model, dx, dt, align)


class VC1_O3_gcc(VC):
    """VC1 with -O3."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC1_O3_gcc, self).__init__('libvc1_O3_gcc', model, dx, dt, align)


class VC1_Ofast_gcc(VC):
    """VC1 with -Ofast."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC1_Ofast_gcc, self).__init__('libvc1_Ofast_gcc', model, dx, dt, align)


class VC2_O2_gcc(VC):
    """Like VC1 but with Laplacian loop manually unrolled."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC2_O2_gcc, self).__init__('libvc2_O2_gcc', model, dx, dt, align)


class VC2_O3_gcc(VC):
    """VC2 with -O3."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC2_O3_gcc, self).__init__('libvc2_O3_gcc', model, dx, dt, align)


class VC2_Ofast_gcc(VC):
    """VC2 with -Ofast."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC2_Ofast_gcc, self).__init__('libvc2_Ofast_gcc', model, dx, dt, align)


class VC3_Ofast_gcc(VC):
    """A vectorized version of VC1."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC3_Ofast_gcc, self).__init__('libvc3_Ofast_gcc', model, dx, dt, align)


class VC3_Ofast_unroll_gcc(VC):
    """VC3 with -funroll-loops."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC3_Ofast_unroll_gcc, self).__init__('libvc3_Ofast_unroll_gcc', model, dx, dt, align)


class VC4_Ofast_gcc(VC):
    """A vectorized version of VC2."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC4_Ofast_gcc, self).__init__('libvc4_Ofast_gcc', model, dx, dt, align)


class VC4_Ofast_extra1_gcc(VC):
    """VC4 with -funsafe-loop-optimizations."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC4_Ofast_extra1_gcc, self).__init__('libvc4_Ofast_extra1_gcc', model, dx, dt, align)


class VC4_Ofast_extra2_gcc(VC):
    """VC4 with -funsafe-loop-optimizations and -floop-block."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC4_Ofast_extra2_gcc, self).__init__('libvc4_Ofast_extra2_gcc', model, dx, dt, align)


class VC4_Ofast_extra3_gcc(VC):
    """VC4 with -funsafe-loop-optimizations and -floop-block and auto parallelization."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC4_Ofast_extra3_gcc, self).__init__('libvc4_Ofast_extra3_gcc', model, dx, dt, align)


class VC5_Ofast_gcc(VC):
    """VC4 with x (inner) loop parallelized."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC5_Ofast_gcc, self).__init__('libvc5_Ofast_gcc', model, dx, dt, align)


class VC6_Ofast_gcc(VC):
    """VC4 with y (outer) loop parallelized."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC6_Ofast_gcc, self).__init__('libvc6_Ofast_gcc', model, dx, dt, align)


class VC6_Ofast_256_gcc(VC):
    """VC6 with 256-bit align specified in code."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC6_Ofast_256_gcc, self).__init__('libvc6_Ofast_256_gcc', model, dx, dt, align)


class VC7_Ofast_gcc(VC):
    """VC4 with collapsed x and y loops parallelized."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC7_Ofast_gcc, self).__init__('libvc7_Ofast_gcc', model, dx, dt, align)


class VC8_Ofast_gcc(VC):
    """VC6 with blocking, parallelized over y blocks."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC8_Ofast_gcc, self).__init__('libvc8_Ofast_gcc', model, dx, dt, align)


class VC9_Ofast_gcc(VC):
    """VC6 with blocking, parallelized over x blocks."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC9_Ofast_gcc, self).__init__('libvc9_Ofast_gcc', model, dx, dt, align)


class VC10_Ofast_gcc(VC):
    """VC6 with blocking, parallelized over all blocks."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC10_Ofast_gcc, self).__init__('libvc10_Ofast_gcc', model, dx, dt, align)


class VC8a_Ofast_gcc(VC_blocksize):
    """VC8, variable blocksize."""
    def __init__(self, model, blocksize_y, blocksize_x, dx, dt=None, align=None):
        super(VC8a_Ofast_gcc, self).__init__('libvc8a_Ofast_gcc', model, blocksize_y, blocksize_x, dx, dt, align)


class VC9a_Ofast_gcc(VC_blocksize):
    """VC9, variable blocksize."""
    def __init__(self, model, blocksize_y, blocksize_x, dx, dt=None, align=None):
        super(VC9a_Ofast_gcc, self).__init__('libvc9a_Ofast_gcc', model, None, blocksize_x, dx, dt, align)


class VC10a_Ofast_gcc(VC_blocksize):
    """VC10, variable blocksize."""
    def __init__(self, model, blocksize_y, blocksize_x, dx, dt=None, align=None):
        super(VC10a_Ofast_gcc, self).__init__('libvc10a_Ofast_gcc', model, None, blocksize_x, dx, dt, align)


class VC11_Ofast_gcc(VC):
    """VC6 with timestep loop inside parallel region."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC11_Ofast_gcc, self).__init__('libvc11_Ofast_gcc', model, dx, dt, align)

    def step(self, num_steps, sources=None, sources_x=None, sources_y=None):
        srcsort = np.argsort(sources_y)
        sources_sort = sources[srcsort, :]
        sources_x_sort = sources_x[srcsort]
        sources_y_sort = sources_y[srcsort]
        return super(VC11_Ofast_gcc, self).step(num_steps, sources_sort, sources_x_sort, sources_y_sort)


class VC12_Ofast_gcc(VC_fxx):
    """V3 with separate loop for f_xx."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC12_Ofast_gcc, self).__init__('libvc12_Ofast_gcc', model, dx, dt, align)


class VC13_Ofast_gcc(VC_fxx):
    """V12 with f_xx loop over single index."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC13_Ofast_gcc, self).__init__('libvc13_Ofast_gcc', model, dx, dt, align)


class VC14_Ofast_gcc(VC_fxx):
    """V13 with BLAS."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC14_Ofast_gcc, self).__init__('libvc14_Ofast_gcc', model, dx, dt, align)


class VC15_Ofast_gcc(VC):
    """V2 with ivdep pragma."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VC15_Ofast_gcc, self).__init__('libvc15_Ofast_gcc', model, dx, dt, align)


class VF1_O2_gcc(VF):
    """A simple Fortran implementation."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF1_O2_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf1_O2_gcc.vf1.step


class VF1_O3_gcc(VF):
    """VF1, with -O3."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF1_O3_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf1_O3_gcc.vf1.step


class VF1_Ofast_gcc(VF):
    """VF1, with -Ofast."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF1_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf1_Ofast_gcc.vf1.step


class VF2_Ofast_gcc(VF):
    def __init__(self, model, dx, dt=None, align=None):
        super(VF2_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf2_Ofast_gcc.vf2.step


class VF3_Ofast_gcc(VF):
    """Like VF1, but uses forall."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF3_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf3_Ofast_gcc.vf3.step


class VF4_Ofast_gcc(VF):
    """Like VF3, but does not use pure function."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF4_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf4_Ofast_gcc.vf4.step


class VF5_Ofast_gcc(VF):
    """Like VF1, but uses do concurrent."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF5_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf5_Ofast_gcc.vf5.step


class VF6_Ofast_gcc(VF):
    """Like VF5, but does not use pure function."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF6_Ofast_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf6_Ofast_gcc.vf6.step


class VF6_Ofast_autopar_gcc(VF):
    """VF6 with auto parallelization."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VF6_Ofast_autopar_gcc, self).__init__(model, dx, dt, align)
        self.fstep = libvf6_Ofast_autopar_gcc.vf6.step


class VCython1(VCython):
    """VC1 implemented using Cython."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VCython1, self).__init__(vcython1, model, dx, dt, align)


class VCython2(VCython):
    """VC6 implemented using Cython."""
    def __init__(self, model, dx, dt=None, align=None):
        super(VCython2, self).__init__(vcython2, model, dx, dt, align)
