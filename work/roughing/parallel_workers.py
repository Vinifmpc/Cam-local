"""Bounded CPU parallelism for independent CAM geometry.

CAM_WORKERS=1 is the reproducible serial diagnostic path. Automatic mode
keeps small jobs serial: importing NumPy/Clipper in Windows spawn workers is
more expensive than calculating a few simple layers in the current process.
"""
import os


def worker_limit():
    value=os.environ.get('CAM_WORKERS','').strip()
    if value:
        try:requested=int(value)
        except ValueError as error:raise ValueError('CAM_WORKERS deve ser um inteiro entre 1 e 8.') from error
        if not 1<=requested<=8:raise ValueError('CAM_WORKERS deve ser um inteiro entre 1 e 8.')
        return min(requested,os.cpu_count() or 1)
    return min(4,max(1,(os.cpu_count() or 1)-1))


def geometry_workers(task_count,work,*,minimum_work=60_000,minimum_tasks=8):
    """Return a bounded count; work is triangle-layer pairs or contact probes."""
    if task_count<minimum_tasks or work<minimum_work:return 1
    return min(task_count,worker_limit())
