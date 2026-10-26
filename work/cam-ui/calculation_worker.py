"""Own the CPU job in a cancellable process, outside the HTTP/UI interpreter."""
import faulthandler
import json
import multiprocessing
import os
from pathlib import Path
import queue
import subprocess
import time
import traceback


class CalculationCancelled(RuntimeError):pass


def _calculate(project,messages):
    from cam_project import calculate_project
    from cam_tools import write_json
    project=Path(project)
    phase='Iniciando motor de cálculo';fraction=0.;last_sent=0.
    def report(name,value):
        nonlocal phase,fraction,last_sent
        phase=name;fraction=value;now=time.monotonic()
        if now-last_sent>=.1 or value in (0,1):
            messages.put({'phase':phase,'progress':fraction});last_sent=now
    with project.with_name('calculation-stack.log').open('w',encoding='utf8') as stack:
        faulthandler.enable(file=stack,all_threads=True)
        faulthandler.dump_traceback_later(60,repeat=True,file=stack)
        try:
            result=calculate_project(project,include_motion=True,progress=report)
            report('Gravando o resultado calculado',.97)
            write_json(project.with_name('calculation-result.json'),result)
            messages.put({'status':'complete'})
        except BaseException as error:
            failure={'status':'failed','error':str(error),'error_type':type(error).__name__,
                     'phase':phase,'progress':fraction,'traceback':traceback.format_exc()}
            write_json(project.with_name('calculation-error.json'),failure)
            messages.put(failure)
        finally:faulthandler.cancel_dump_traceback_later()


def _own_windows_tree(process):
    """Close this handle to stop descendants even after their parent crashes."""
    if os.name!='nt':return None
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
            ('flags',wintypes.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),
            ('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',ctypes.c_ulonglong*6),('process_memory',ctypes.c_size_t),
            ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job:return None
    info=Extended();info.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    handle=kernel.OpenProcess(0x0101,False,process.pid)  # SET_QUOTA | TERMINATE
    valid=handle and kernel.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)) and kernel.AssignProcessToJobObject(job,handle)
    if handle:kernel.CloseHandle(handle)
    if not valid:kernel.CloseHandle(job);return None
    return lambda:kernel.CloseHandle(job)


def _stop_tree(process,close_job=None):
    if close_job:
        close_job();process.join(timeout=5)
    if not process.is_alive():return
    if os.name=='nt':
        # The PID was created by this module; /T also stops its geometry pool.
        try:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
        except (OSError,subprocess.TimeoutExpired):pass
    if process.is_alive():process.terminate()
    process.join(timeout=5)


def run_calculation(project,on_update,cancel,*,timeout_s=900):
    context=multiprocessing.get_context('spawn');messages=context.Queue()
    process=context.Process(target=_calculate,args=(str(project),messages),name='CAM-calculo',daemon=False)
    started=time.monotonic();last_progress=started;last_heartbeat=0.
    phase='Iniciando motor em processo separado';fraction=0.;close_job=None
    def complete():
        if cancel.is_set():raise CalculationCancelled('Cálculo cancelado')
        if time.monotonic()-started>timeout_s:raise TimeoutError('Cálculo excedeu o prazo configurado')
        stage=Path(project).with_name('calculation-result.json')
        result=json.loads(stage.read_text(encoding='utf8'))
        os.replace(stage,Path(project).with_name('result.json'))
        return result
    try:
        if cancel.is_set():raise CalculationCancelled('Cálculo cancelado')
        process.start()
        close_job=_own_windows_tree(process)
        on_update({'phase':phase,'progress':fraction,'worker_pid':process.pid,'worker_alive':True,'heartbeat_s':0})
        while True:
            now=time.monotonic()
            if cancel.is_set():raise CalculationCancelled('Cálculo cancelado')
            if now-started>timeout_s:
                raise TimeoutError(f'Cálculo excedeu {timeout_s/60:g} minutos. A tarefa foi encerrada; consulte os diagnósticos do projeto.')
            try:message=messages.get(timeout=.25)
            except queue.Empty:message=None
            if message:
                if message.get('status')=='failed':
                    raise RuntimeError(message.get('error') or 'O processo de cálculo informou uma falha')
                if message.get('status')=='complete':
                    process.join(timeout=5)
                    if process.exitcode not in (None,0):raise RuntimeError(f'O motor terminou com código {process.exitcode}')
                    return complete()
                phase=message.get('phase',phase);fraction=max(fraction,message.get('progress',fraction))
                last_progress=time.monotonic()
                on_update({'phase':phase,'progress':fraction,'worker_pid':process.pid,'worker_alive':True,'heartbeat_s':0})
            if not process.is_alive():
                # Normal completion enqueues its final status before exiting.
                # Give the queue feeder one final bounded drain on next loop.
                try:message=messages.get(timeout=.5)
                except queue.Empty:raise RuntimeError(f'O processo de cálculo encerrou inesperadamente (código {process.exitcode}). Consulte calculation-stack.log.')
                if message.get('status')=='complete':
                    if process.exitcode not in (None,0):raise RuntimeError(f'O motor terminou com código {process.exitcode}')
                    return complete()
                if message.get('status')=='failed':raise RuntimeError(message.get('error') or 'Falha no motor')
                on_update(message)
            if now-last_heartbeat>=2:
                on_update({'phase':phase,'progress':fraction,'worker_pid':process.pid,
                           'worker_alive':process.is_alive(),'heartbeat_s':round(max(0,time.monotonic()-last_progress),1)})
                last_heartbeat=now
    finally:
        if process.pid is not None:_stop_tree(process,close_job)
        messages.close();messages.cancel_join_thread()
