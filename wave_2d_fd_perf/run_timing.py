"""Measure the runtime of the propagators."""
from timeit import repeat
import numpy as np
import pandas as pd
from wave_2d_fd_perf.propagators import (VC1_O2_gcc, VC1_O3_gcc, VC1_Ofast_gcc, VC2_O2_gcc, VC2_O3_gcc, VC2_Ofast_gcc, VC3_Ofast_gcc, VC3_Ofast_unroll_gcc, VC4_Ofast_gcc, VC4_Ofast_extra1_gcc, VC4_Ofast_extra2_gcc, VC4_Ofast_extra3_gcc, VC5_Ofast_gcc, VC6_Ofast_gcc, VC6_Ofast_256_gcc, VC7_Ofast_gcc, VC8_Ofast_gcc, VC9_Ofast_gcc, VC10_Ofast_gcc, VC11_Ofast_gcc, VC12_Ofast_gcc, VC13_Ofast_gcc, VC14_Ofast_gcc, VC15_Ofast_gcc, VF1_O2_gcc, VF1_O3_gcc, VF1_Ofast_gcc, VF2_Ofast_gcc, VF3_Ofast_gcc, VF4_Ofast_gcc, VF5_Ofast_gcc, VF6_Ofast_gcc, VF6_Ofast_autopar_gcc, VCython1, VCython2)
from wave_2d_fd_perf.vpytorch1 import VPytorch1
from wave_2d_fd_perf.vpytorch2 import VPytorch2
from wave_2d_fd_perf.vpytorch3 import VPytorch3
from wave_2d_fd_perf.test_wave_2d_fd_perf import ricker

def run_timing_num_steps(num_repeat=10, num_steps=range(0, 110, 10),
                         model_size=1000, versions=None, align=None):
    """Time implementations as num_steps varies."""

    if versions is None:
        versions = _versions()

    times = pd.DataFrame(columns=['version', 'num_steps', 'model_size', 'time'])

    for nsteps in num_steps:
        model = _make_model(model_size, nsteps)
        times = _time_versions(versions, model, num_repeat, times, align)

    return times


def run_timing_model_size(num_repeat=10, num_steps=10,
                          model_sizes=range(200, 2200, 200), versions=None,
                          align=None):
    """Time implementations as model size varies."""

    if versions is None:
        versions = _versions()

    times = pd.DataFrame(columns=['version', 'num_steps', 'model_size', 'time'])

    for N in model_sizes:
        model = _make_model(N, num_steps)
        times = _time_versions(versions, model, num_repeat, times, align)

    return times


def _versions():
    """Return a list of versions to be timed."""
    return [{'class': VC1_O2_gcc, 'name': 'C v1 (gcc, -O2)'},
            {'class': VC1_O3_gcc, 'name': 'C v1 (gcc, -O3)'},
            {'class': VC1_Ofast_gcc, 'name': 'C v1 (gcc, -Ofast)'},
            {'class': VC2_O2_gcc, 'name': 'C v2 (gcc, -O2)'},
            {'class': VC2_O3_gcc, 'name': 'C v2 (gcc, -O3)'},
            {'class': VC2_Ofast_gcc, 'name': 'C v2 (gcc, -Ofast)'},
            {'class': VC3_Ofast_gcc, 'name': 'C v3 (gcc, -Ofast)'},
            {'class': VC3_Ofast_unroll_gcc, 'name': 'C v3 (gcc, -Ofast -funroll-loops)'},
            {'class': VC4_Ofast_gcc, 'name': 'C v4 (gcc, -Ofast)'},
            {'class': VC4_Ofast_extra1_gcc, 'name': 'C v4 (gcc, -Ofast opt1)'},
            {'class': VC4_Ofast_extra2_gcc, 'name': 'C v4 (gcc, -Ofast opt2)'},
            {'class': VC4_Ofast_extra3_gcc, 'name': 'C v4 (gcc, -Ofast opt3)'},
            {'class': VC5_Ofast_gcc, 'name': 'C v5 (gcc, -Ofast)'},
            {'class': VC6_Ofast_gcc, 'name': 'C v6 (gcc, -Ofast)'},
            {'class': VC6_Ofast_256_gcc, 'name': 'C v6 256 (gcc, -Ofast)', 'align': 256},
            {'class': VC7_Ofast_gcc, 'name': 'C v7 (gcc, -Ofast)'},
            {'class': VC8_Ofast_gcc, 'name': 'C v8 (gcc, -Ofast)'},
            {'class': VC9_Ofast_gcc, 'name': 'C v9 (gcc, -Ofast)'},
            {'class': VC10_Ofast_gcc, 'name': 'C v10 (gcc, -Ofast)'},
            {'class': VC11_Ofast_gcc, 'name': 'C v11 (gcc, -Ofast)'},
            {'class': VC12_Ofast_gcc, 'name': 'C v12 (gcc, -Ofast)'},
            {'class': VC13_Ofast_gcc, 'name': 'C v13 (gcc, -Ofast)'},
            {'class': VC14_Ofast_gcc, 'name': 'C v14 (gcc, -Ofast)'},
            {'class': VC15_Ofast_gcc, 'name': 'C v15 (gcc, -Ofast)'},
            {'class': VF1_O2_gcc, 'name': 'F v1 (gcc, -O2)'},
            {'class': VF1_O3_gcc, 'name': 'F v1 (gcc, -O3)'},
            {'class': VF1_Ofast_gcc, 'name': 'F v1 (gcc, -Ofast)'},
            {'class': VF2_Ofast_gcc, 'name': 'F v2 (gcc, -Ofast)'},
            {'class': VF3_Ofast_gcc, 'name': 'F v3 (gcc, -Ofast)'},
            {'class': VF4_Ofast_gcc, 'name': 'F v4 (gcc, -Ofast)'},
            {'class': VF5_Ofast_gcc, 'name': 'F v5 (gcc, -Ofast)'},
            {'class': VF6_Ofast_gcc, 'name': 'F v6 (gcc, -Ofast)'},
            {'class': VF6_Ofast_autopar_gcc, 'name': 'F v6 (gcc, -Ofast autopar)'},
            {'class': VCython1, 'name': 'Cython v1)'},
            {'class': VCython2, 'name': 'Cython v2)'},
            {'class': VPytorch1, 'name': 'PyTorch v1)'},
            {'class': VPytorch2, 'name': 'PyTorch v2)'},
            {'class': VPytorch3, 'name': 'PyTorch v3)'}]


def _make_model(N, nsteps):
    """Create a model with a given number of elements and time steps."""
    model = np.random.random([N, N]).astype(np.float32) * 3000 + 1500
    dx = 5
    dt = 0.001
    source = ricker(25, nsteps, dt, 0.05)
    sx = int(N/2)
    sy = sx
    return {'model': model, 'dx': dx, 'dt': dt, 'nsteps': nsteps,
            'sources': np.array([source]), 'sx': np.array([sx]),
            'sy': np.array([sy])}


def _time_versions(versions, model, num_repeat, dataframe, align=None):
    """Loop over versions and append the timing results to the dataframe."""
    num_steps = model['nsteps']
    model_size = len(model['model'])
    for v in versions:

        if 'align' in v.keys():
            if (align) and (align % v['align']) == 0:
                ok_to_run = True
            else:
                ok_to_run = False
        else:
            ok_to_run = True

        if ok_to_run:
            time = _time_version(v['class'], model, num_repeat, align)
            dataframe = dataframe.append({'version': v['name'],
                                          'num_steps': num_steps,
                                          'model_size': model_size,
                                          'time': time}, ignore_index=True)
    return dataframe


def _time_version(version, model, num_repeat, align=None):
    """Time a particular version."""
    v = version(model['model'], model['dx'], model['dt'], align)

    def closure():
        """Closure over variables so they can be used in repeat below."""
        v.step(model['nsteps'], model['sources'], model['sx'], model['sy'])

    return np.min(repeat(closure, number=1, repeat=num_repeat))

if __name__ == '__main__':
    print(run_timing_num_steps())
