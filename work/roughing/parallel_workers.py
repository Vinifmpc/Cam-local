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
        except ValueError as error:raise ValueError('CAM_WORKERS deve ser um inteiro entre 1 e 32.') from error
        if not 1<=requested<=32:raise ValueError('CAM_WORKERS deve ser um inteiro entre 1 e 32.')
        return min(requested,os.cpu_count() or 1)
    return min(8,max(1,(os.cpu_count() or 1)-1))


def geometry_workers(task_count,work,*,minimum_work=60_000,minimum_tasks=8):
    """Return a bounded count; work is triangle-layer pairs or contact probes."""
    if task_count<minimum_tasks or work<minimum_work:return 1
    # Avoid spawning eight interpreters for one barely parallel-sized job.
    # Large requests can use the full CPU budget; each chunk retains enough
    # work to amortize Windows process startup and native STL construction.
    return min(task_count,worker_limit(),max(2,(work+minimum_work-1)//minimum_work))
