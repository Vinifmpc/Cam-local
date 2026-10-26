"""Windows entry point: private local CAM service in its own WebView2 window."""
import multiprocessing
if __name__=='__main__':multiprocessing.freeze_support()

import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import struct
import sys
import threading
import time
import traceback
import urllib.request
from http.server import ThreadingHTTPServer

ROOT=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/roughing'))
from server import App,handler_for

def data_folder():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'CAMLocal'

def check_project(folder,source,report_path):
    """Run an unchanged saved setup through the packaged process coordinator."""
    from dataclasses import asdict
    from cam_project import load_project
    from cam_tools import write_json
    from cam_operations import OperationSettings
    app=App(folder/'project-check/uploads',folder/'project-check/projetos')
    report={'status':'running','frozen':bool(getattr(sys,'frozen',False)),'source_project':str(source)}
    write_json(report_path,report);history=[]
    try:
        record,mesh,tool,settings,_=load_project(source)
        asset=app.upload((source.parent/record['source']['path']).read_bytes(),'STL do teste salvo')
        request={'asset':asset,'placement':{'units':record['source']['units'],
            'rotation':record['alignment']['rotation'],'translation_mm':record['alignment']['translation_mm'],
            'xy_origin':'keep','z_origin':'keep'},'tool':tool.as_dict(),'settings':asdict(settings),
            'operations':asdict(OperationSettings.from_dict(record.get('operations',{}))),'notes':record['notes']}
        started=time.monotonic();task=app.calculate(request);previous=-1;last_saved=0.
        while True:
            state=app.job_state(task['job'])
            if state['status']!='running':break
            fraction=state.get('progress',0)
            if fraction>previous:
                history.append({k:state[k] for k in ('phase','progress','elapsed_s')});previous=fraction
            if time.monotonic()-last_saved>2:
                report.update(job=task['job'],state=state,history=history)
                write_json(report_path,report);last_saved=time.monotonic()
            time.sleep(.2)
        if state['status']!='complete':raise RuntimeError(state.get('error') or state['status'])
        calculation_s=time.monotonic()-started
        started=time.monotonic();exported=app.export(task['job'])
        assert exported['report']['status']=='passed'
        report.update(status='passed',calculation_s=round(calculation_s,3),export_s=round(time.monotonic()-started,3),
            moves=len(state['motion']['moves']),validation=state['motion']['validation'],nc=exported,
            model=mesh.summary(),history=history,job=task['job'],state={'status':'complete','progress':1})
        write_json(report_path,report)
    except Exception as error:
        report.update(status='failed',error=str(error),history=history);write_json(report_path,report);raise
    finally:app.shutdown()


def self_test(folder,report_path,stl_path=None):
    from cam_project import calculate_project
    from cam_tools import write_json
    write_json(report_path,{'status':'running','frozen':bool(getattr(sys,'frozen',False))})
    app=App(folder/'self-test/uploads',folder/'self-test/projetos')
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        triangles=[[-5,-5,-2,5,-5,-2,5,5,-2],[-5,-5,-2,5,5,-2,-5,5,-2]]
        model=bytes(80)+struct.pack('<I',2)+b''.join(struct.pack('<12fH',0,0,1,*p,0) for p in triangles)
        asset=app.upload(stl_path.read_bytes() if stl_path else model,stl_path.name if stl_path else 'ensaio.stl')
        request={'asset':asset,'placement':{'units':'mm','xy_origin':'keep','z_origin':'keep'},
            'tool':{'id':'ensaio','name':'Topo 1 mm','diameter_mm':1,'cutting_length_mm':5},
            'settings':{'stepdown_mm':1,'stepover_mm':.8,'stock_top_mm':0,'bottom_mm':-2,
                        'boundaries_mm':[[[-2,-1],[2,-1],[2,1],[-2,1]]]},
            'operations':{'roughing_enabled':True,'cutout_enabled':True,'cutout_bottom_mm':-2.1,
                          'roughing_feed_mm_min':700,'cutout_feed_mm_min':900,'plunge_mm_min':150,'spindle_rpm':8000}}
        if stl_path:
            request['placement']={'units':'mm','xy_origin':'minimum','z_origin':'top'}
            mesh=app.inspect(asset,request['placement'])['mesh']
            lo,hi=mesh['bounds_mm']['minimum'],mesh['bounds_mm']['maximum']
            request['tool']={'id':'ensaio-cubo','name':'Topo 3,175 mm','diameter_mm':3.175,'cutting_length_mm':22}
            request['settings'].update(stepdown_mm=.7,stepover_mm=1.27,sampling_mm=.2,
                stock_top_mm=hi[2],bottom_mm=lo[2],region_mode='layer',cleanup_contours=True,compress_collinear=True,
                boundaries_mm=[[[lo[0]-5,lo[1]-5],[hi[0]+5,lo[1]-5],[hi[0]+5,hi[1]+5],[lo[0]-5,hi[1]+5]]])
            request['operations'].update(cutout_bottom_mm=lo[2]-.1,cutout_stepdown_mm=.7)
        started=time.monotonic()
        identifier,project=app.prepare(request)
        result=calculate_project(project,include_motion=True);write_json(project.with_name('result.json'),result)
        nc=app.export(identifier)
        restored=app.restore(app.bundle(identifier));assert restored['motion'] is None
        assets={}
        for path in ('/','/app.js','/vendor/three.module.js','/vendor/manifold.js','/vendor/manifold.wasm'):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}'+path) as response:
                content=response.read();assets[path]={'bytes':len(content),'mime':response.headers['Content-Type']}
        demo=app.demo();assert demo['motion']['moves']
        assert nc['report']['status']=='passed'
        report={'status':'passed','frozen':bool(getattr(sys,'frozen',False)),
                'native_dependencies':'numpy + Clipper2 + bundled Node/OpenCAMLib passed',
                'calculated_moves':len(result['motion']['moves']),'nc':nc,'assets':assets,
                'project_roundtrip':'passed','prepared_ring_moves':len(demo['motion']['moves']),
                'data_directory':str(folder)}
        report['calculation_and_export_s']=round(time.monotonic()-started,3)
        if stl_path:
            report['fixture']={'path':str(stl_path),'mesh':mesh}
            report['cases']=[]
            for label,rough,cutout,order in [('rough',True,False,'roughing_then_cutout'),
                    ('cutout',False,True,'roughing_then_cutout'),
                    ('rough_then_cutout',True,True,'roughing_then_cutout'),
                    ('cutout_then_rough',True,True,'cutout_then_roughing')]:
                request['operations'].update(roughing_enabled=rough,cutout_enabled=cutout,order=order)
                started=time.monotonic();task=app.calculate(request);identifier=task['job']
                deadline=time.monotonic()+180
                while app.job_state(identifier)['status']=='running':
                    if time.monotonic()>deadline:raise TimeoutError('Ensaio excedeu 180 s: '+str(app.job_state(identifier)))
                    time.sleep(.05)
                state=app.job_state(identifier)
                assert state['status']=='complete',state
                calculated=state['motion'];assert calculated['moves']
                if rough:assert any(m[0]=='cut' and m[8]=='roughing' for m in calculated['moves'])
                if cutout:assert any(m[0]=='cut' and m[8]=='cutout' for m in calculated['moves'])
                exported=app.export(identifier);assert exported['report']['status']=='passed'
                restored=app.restore(app.bundle(identifier))
                assert restored['operations']==request['operations'] or all(
                    restored['operations'][k]==v for k,v in request['operations'].items())
                report['cases'].append({'case':label,'status':'passed','moves':len(calculated['moves']),
                    'elapsed_s':round(time.monotonic()-started,3),'nc':exported['report']})
            restored_request={k:restored[k] for k in ('asset','placement','tool','settings','operations','notes')}
            identifier,project=app.prepare(restored_request)
            result=calculate_project(project,include_motion=True);write_json(project.with_name('result.json'),result)
            assert app.export(identifier)['report']['status']=='passed'
            report['restored_cube_recalculation']='passed'
        report_path.parent.mkdir(parents=True,exist_ok=True);write_json(report_path,report)
    except Exception as error:
        write_json(report_path,{'status':'failed','frozen':bool(getattr(sys,'frozen',False)),'error':str(error)})
        raise
    finally:
        server.shutdown();server.server_close();thread.join();app.shutdown()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path)
    parser.add_argument('--stl',type=Path,help='STL externo para ensaio completo do executável')
    parser.add_argument('--check-project',type=Path,help='Conferir projeto salvo sem alterar o original')
    command=parser.add_mutually_exclusive_group()
    command.add_argument('--command',type=Path,help='Executar arquivo JSON de comandos no aplicativo aberto')
    command.add_argument('--command-json',help='Executar um comando/lote JSON no aplicativo aberto')
    parser.add_argument('--port',type=int,help='Porta explícita para comandos (normalmente descoberta automaticamente)')
    parser.add_argument('--start',action='store_true',help='Abrir o aplicativo se necessário antes dos comandos')
    parser.add_argument('--data-dir',type=Path,help='Pasta de dados/perfil separada para automação e ensaios')
    parser.add_argument('--hidden',action='store_true',help='Janela oculta para ensaios por comandos em perfil isolado')
    args=parser.parse_args();folder=(args.data_dir or data_folder()).resolve();folder.mkdir(parents=True,exist_ok=True)
    if args.hidden and (args.data_dir is None or folder==data_folder().resolve()):
        parser.error('--hidden exige --data-dir com um perfil isolado')
    logfile=folder/'desktop.log'
    logging.basicConfig(filename=logfile,encoding='utf8',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    # GUI builds have no console. Preserve useful diagnostics for libraries.
    if sys.stdout is None:sys.stdout=logfile.open('a',encoding='utf8')
    if sys.stderr is None:sys.stderr=sys.stdout
    if args.command is not None or args.command_json is not None:
        from command_client import run_commands
        report=args.report or folder/'command-result.json'
        try:document=json.loads(args.command.read_text(encoding='utf-8-sig') if args.command is not None else args.command_json)
        except (OSError,ValueError) as error:
            from cam_tools import write_json
            write_json(report,{'protocol':1,'status':'failed','error':str(error)});return 1
        result=run_commands(document,report,folder,port=args.port,start=args.start)
        return 0 if result['status']=='complete' else 1
    if args.self_test:
        self_test(folder,args.report or folder/'self-test.json',args.stl);return
    if args.check_project:
        check_project(folder,args.check_project,args.report or folder/'project-check.json');return
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    app=App(folder/'uploads',folder/'projetos')
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    (folder/'desktop-runtime.json').write_text(json.dumps({'pid':os.getpid(),'port':server.server_port}),encoding='utf8')
    logging.info('Desktop ready on private loopback port %s',server.server_port)
    try:
        window=webview.create_window('CAM Local',url,width=1280,height=860,min_size=(900,620),background_color='#152a42',
            hidden=args.hidden,focus=not args.hidden)
        app.on_close=window.destroy
        def show_window():
            window.show();window.restore()
        app.on_show=show_window
        webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(folder/'webview'),
                      localization={'global.saveFile':'Salvar arquivo','global.openFile':'Abrir arquivo','global.cancel':'Cancelar'})
    finally:
        app.shutdown();server.shutdown();server.server_close();thread.join()
        runtime=folder/'desktop-runtime.json'
        try:
            if json.loads(runtime.read_text(encoding='utf8')).get('pid')==os.getpid():runtime.unlink()
        except (OSError,ValueError):pass
        logging.info('Desktop stopped')

if __name__=='__main__':
    try:sys.exit(main() or 0)
    except Exception:
        folder=data_folder();folder.mkdir(parents=True,exist_ok=True)
        error=traceback.format_exc();(folder/'erro-desktop.txt').write_text(error,encoding='utf8')
        if not any(flag in sys.argv for flag in ('--self-test','--check-project','--command','--command-json')):
            ctypes.windll.user32.MessageBoxW(None,'Não foi possível iniciar o CAM Local.\n\nDetalhes em '+str(folder/'erro-desktop.txt'),'CAM Local',16)
        sys.exit(1)
