"""Loopback-only CAM application. No controller/machine or G-code endpoint."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import copy
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import logging
import os
import math
import mimetypes
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlparse,parse_qs
import uuid
import zipfile

ROOT=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/roughing'))
from cam_tools import Tool,ToolLibrary,write_json
from cam_project import RoughingSettings,create_project,load_project
from calculation_worker import run_calculation,CalculationCancelled
from cam_operations import OperationSettings,validate_operations
from grbl_post import export_grbl
from mesh_geometry import place_stl,MAX_BYTES
from command_control import CommandMailbox
from machining_presets import PresetStore

STATIC=ROOT/'work/cam-ui/static' if getattr(sys,'frozen',False) else Path(__file__).parent/'static'
THREE=ROOT/'work/ui-runtime/node_modules/three'
FLIP_X=[[1,0,0],[0,-1,0],[0,0,-1]]


class App:
    def __init__(self,data=None,outputs=None,*,calculation_timeout_s=None):
        self.data=Path(data or ROOT/'work/ui-data');self.data.mkdir(parents=True,exist_ok=True)
        self.outputs=Path(outputs or ROOT/'outputs/CAM-local/projetos');self.outputs.mkdir(parents=True,exist_ok=True)
        self.tools_path=self.outputs.parent/'ferramentas.json'
        self.presets=PresetStore(self.outputs.parent/'machining-presets.json')
        self.presets.migrate_latest(self.outputs)
        if not self.tools_path.exists():
            ToolLibrary([Tool(id='flat-3_175',name='Topo reto Ø3,175 mm',diameter_mm=3.175,
                cutting_length_mm=22,notes='Confira as dimensões reais da ferramenta e preencha avanços e RPM.')]).save(self.tools_path)
        self.assets={};self.jobs={};self.saved={};self.exports={};self.token=secrets.token_urlsafe(32)
        self.export_lock=threading.Lock()
        self.pool=ThreadPoolExecutor(max_workers=1);self.lock=threading.Lock();self.active=None
        self.job_started={}
        self.cancel_signals={};self.stopping=False
        self.commands=CommandMailbox();self.on_close=None;self.on_show=None
        self.calculation_timeout_s=float(calculation_timeout_s if calculation_timeout_s is not None else os.environ.get('CAM_CALC_TIMEOUT_S','900'))
        if not math.isfinite(self.calculation_timeout_s) or self.calculation_timeout_s<=0:raise ValueError('Prazo de cálculo inválido')

    def upload(self,data,name='modelo.stl'):
        if not data or len(data)>MAX_BYTES:raise ValueError('STL vazio ou maior que 128 MiB')
        asset=uuid.uuid4().hex
        path=self.data/(asset+'.stl');path.write_bytes(data)
        self.assets[asset]={'path':path,'name':Path(name.replace('\\','/')).name[:150]}
        return asset

    def asset(self,identifier):
        if identifier not in self.assets:raise ValueError('Importe o STL novamente nesta sessão')
        return self.assets[identifier]

    def placement(self,record):
        allowed={'units','rotation','translation_mm','xy_origin','z_origin'}
        if not isinstance(record,dict) or set(record)-allowed:raise ValueError('Posicionamento inválido')
        return record

    def inspect(self,asset,placement):
        item=self.asset(asset);p=self.placement(placement)
        mesh=place_stl(item['path'],**p)
        return {'asset':asset,'name':item['name'],'placement':p,
                'mesh':mesh.summary(),'triangles':mesh.triangles.reshape(-1).tolist()}

    def inspect_drill(self,request):
        """Read-only hole/tool compatibility; no project or calculation created."""
        from drill import inspect_drill_compatibility
        item=self.asset(request['asset'])
        tool=Tool.from_dict(request['tool'])
        options_record=dict(request.get('operations',{}))
        # Inspection is available while all operation checkboxes are off.
        if not any(options_record.get(k, k=='roughing_enabled') for k in ('roughing_enabled','cutout_enabled','drill_enabled')):
            options_record['drill_enabled']=True
        options=OperationSettings.from_dict(options_record)
        settings=RoughingSettings.from_dict(request['settings'])
        mesh=place_stl(item['path'],**self.placement(request['placement']))
        return inspect_drill_compatibility(mesh.triangles,diameter=tool.diameter_mm,
            tool_length=tool.cutting_length_mm,stock_top=settings.stock_top_mm,
            bottom=options.drill_bottom_mm if options.drill_bottom_mm is not None else settings.bottom_mm,
            tolerance=options.drill_tolerance_mm,allow_helix=options.drill_allow_helix,
            center_cutting=options.drill_center_cutting,compensate_facets=options.drill_compensate_facets)

    def smart_plan(self,request):
        """Preview the same deterministic setup used by calculation/export.

        No project, worker or toolpath is created by this read-only request.
        """
        from smart_planner import resolve_smart_plan
        item,tool,settings,options,placement,_=self.validate_request(request)
        if options.machining_mode!='smart':return {'enabled':False}
        mesh=place_stl(item['path'],**placement)
        effective,resolved,report=resolve_smart_plan(mesh,tool,settings,options)
        from cam_project import validate_setup
        validate_setup(mesh,tool,effective,roughing_enabled=True,operations=resolved)
        return report

    def validate_request(self,request):
        if not isinstance(request,dict):raise ValueError('Configuração de projeto inválida')
        item=self.asset(request['asset'])
        tool=Tool.from_dict(request['tool'])
        settings=RoughingSettings.from_dict(request['settings'])
        options=OperationSettings.from_dict(request.get('operations',{}))
        # Smart depths come from the placed mesh/physical stock, not the
        # disabled manual depth inputs. Resolve those before reach checks.
        if options.machining_mode!='smart':validate_operations(options,settings,tool)
        placement=self.placement(request['placement'])
        ui=self.ui_metadata(request.get('ui',{}))
        return item,tool,settings,options,placement,ui

    def prepare(self,request,identifier=None):
        item,tool,settings,options,placement,ui=self.validate_request(request)
        identifier=identifier or uuid.uuid4().hex;folder=self.outputs/identifier;folder.mkdir()
        # Snapshot the source into the saved project; uploads remain immutable.
        source=folder/'model.stl';source.write_bytes(item['path'].read_bytes())
        project=folder/'project.json'
        create_project(source,project,tool=tool,settings=settings,
            **placement,notes=request.get('notes',''),operations=options)
        write_json(folder/'ui.json',ui)
        self.saved[identifier]=project
        return identifier,project

    @staticmethod
    def ui_metadata(record):
        if not isinstance(record,dict):raise ValueError('Metadados da interface inválidos')
        windows=record.get('windows')
        if windows is not None:
            if not isinstance(windows,list) or len(windows)>100:raise ValueError('Janelas inválidas')
            for b in windows:
                if (not isinstance(b,list) or len(b)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in b)
                    or b[2]<=b[0] or b[3]<=b[1]):raise ValueError('Janela inválida')
        result={'windows':windows,'approximate_regions':bool(record.get('approximate_regions',False))}
        stock=record.get('stock')
        if stock is not None:
            if (not isinstance(stock,dict) or set(stock)!={'x0','y0','x1','y1','step'}
                or not all(type(v) in (int,float) and math.isfinite(v) for v in stock.values())
                or stock['x1']<=stock['x0'] or stock['y1']<=stock['y0'] or stock['step'] not in (.25,.5,1)):
                raise ValueError('Limites ou resolução do bruto inválidos')
            result['stock']=stock.copy()
        return result

    @staticmethod
    def motion_view(result):
        if not result or not result.get('motion'):return None
        motion=result['motion']
        return {'moves':[[m['kind'],*m['start'],*m['end'],m.get('layer',-1),m.get('operation','roughing')] for m in motion['moves']],
            'timing':motion.get('timing'), 'durations_s':[m.get('duration_s') for m in motion['moves']],
            'feeds_mm_min':[m.get('feed_mm_min') for m in motion['moves']],
            'safe_z':motion['safe_z'],'initial':motion['initial_position'],
            'smart_plan':result.get('smart_plan'),
            'validation':motion['validation'],'counts':motion['move_counts'],
            'entries':len(motion['entries']),'cutting_edges':sum((result.get(name) or {}).get('cutting_edges',0) for name in ('roughing','cutout','drill')),
            'operations':{name:{'contours':len(result[name].get('contours',[])),
                'contours_selection':result[name].get('contours_selection'),
                'selected_internal_indices':result[name].get('selected_internal_indices',[]),
                'internal_contours_total':result[name].get('internal_contours_total',0),
                'skipped_internal_contours':result[name].get('skipped_internal_contours',0),
                'rest_material':result[name].get('rest_material'),
                'preparation_polyline_count':result[name].get('preparation_polyline_count',0),
                'preparation_cutting_edges':result[name].get('preparation_cutting_edges',0),
                'automatic_area_mm2':(result[name].get('automatic_regions') or {}).get('area_mm2'),
                'prior_roughing':result['operations'][name].get('prior_roughing'),
                'depth_passes':len(result[name].get('depth_levels',result[name].get('layers',[]))),
                'path_order':result['operations'][name].get('path_order','layer'),
                'regions':result['operations'][name].get('region_schedule',{}).get('region_count',0),
                'stay_down_entries':result['operations'][name].get('stay_down_entries',0),
                'center_plunge_entries':result['operations'][name].get('center_plunge_entries',0),
                'holes_count':len(result[name].get('holes',[])),
                'helix_count':sum(h.get('strategy')=='helix' for h in result[name].get('holes',[])),
                'skipped_holes_count':len(result[name].get('skipped_holes',[]))}
                for name in result.get('operations',{'roughing':{}})}}

    def demo(self):
        from sample_model import pocket_plate_stl
        asset=self.upload(pocket_plate_stl(),'Placa com bolsão · exemplo')
        p={'units':'mm','rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0],
           'xy_origin':'minimum','z_origin':'top'}
        scene=self.inspect(asset,p)
        tool=Tool(id='demo-flat-3_175',name='Topo reto Ø3,175 mm · demonstração',diameter_mm=3.175,
                  cutting_length_mm=22,feed_mm_min=700,plunge_mm_min=150,spindle_rpm=8000,
                  notes='Valores de demonstração para simular; ajuste à ferramenta e ao material reais.')
        settings=RoughingSettings(stock_top_mm=0,bottom_mm=-5,stepdown_mm=1,
            stepover_mm=1.27,sampling_mm=.25,boundaries_mm=[[[-5,-5],[25,-5],[25,25],[-5,25]]],
            cleanup_contours=True,compress_collinear=True,region_mode='layer',domain_mode='expanded')
        scene.update({'tool':tool.as_dict(),'settings':asdict(settings),'isDemo':True,
            'notes':'Peça geométrica original gerada pelo CAM Local. Valores de demonstração para simulação.',
            'operations':asdict(OperationSettings(machining_mode='smart',cutout_stepdown_mm=1)),
            'motion':None,'approximate_regions':False})
        return scene

    def export(self,identifier):
        if identifier not in self.saved:raise ValueError('Projeto calculado não encontrado; recalcule')
        if identifier in self.jobs and self.jobs[identifier]['status']!='complete':
            raise ValueError('Aguarde um cálculo concluído antes de exportar')
        project=self.saved[identifier];result_path=project.with_name('result.json')
        if not result_path.exists():raise ValueError('Calcule os percursos antes de exportar')
        if not self.export_lock.acquire(blocking=False):raise RuntimeError('Já há uma exportação em andamento')
        try:
            result=json.loads(result_path.read_text(encoding='utf8'))
            export_id=uuid.uuid4().hex
            options=OperationSettings.from_dict(json.loads(project.read_text(encoding='utf8')).get('operations',{}))
            priority=('-regioes' if options.roughing_order=='region_first' else '-camadas') if options.roughing_enabled else ''
            filename='cam-'+options.order+priority+'-'+export_id[:8]+'.nc'
            destination=self.outputs.parent/'exportacoes'/export_id/filename
            report=export_grbl(result,project,destination)
            self.exports[export_id]=destination
            return {'export_id':export_id,'filename':filename,'report':report}
        finally:self.export_lock.release()

    def calculate(self,request):
        # Validate cheap inputs now; STL inspection and preparation belong to
        # the worker so the HTTP/UI thread can report progress immediately.
        request=copy.deepcopy(request)
        self.validate_request(request)
        with self.lock:
            if self.stopping:raise RuntimeError('O aplicativo está encerrando')
            if self.active:raise RuntimeError('Já há um cálculo em andamento. Aguarde a conclusão.')
            identifier=uuid.uuid4().hex
            self.job_started[identifier]=time.monotonic()
            self.jobs[identifier]={'status':'running','project_id':identifier,'phase':'Preparando STL e configuração','progress':0.0}
            self.active=identifier
            cancel=threading.Event();self.cancel_signals[identifier]=cancel
        last_saved=0.
        folder=self.outputs/identifier
        def progress(update):
            nonlocal last_saved
            with self.lock:
                self.jobs[identifier].update(update)
                state=self.jobs[identifier].copy()
            now=time.monotonic()
            if now-last_saved>=2 and folder.exists():
                state['elapsed_s']=round(now-self.job_started[identifier],3)
                write_json(folder/'job.json',state);last_saved=now
        def run():
            try:
                _,project=self.prepare(request,identifier)
                result=run_calculation(project,progress,cancel,timeout_s=self.calculation_timeout_s)
                payload={'status':'complete','project_id':identifier,'motion':self.motion_view(result),
                         'inspection':result['roughing']['setup_inspection'],'phase':'Percursos calculados e salvos','progress':1.0}
            except CalculationCancelled:
                payload={'status':'cancelled','project_id':identifier,'phase':'Cálculo cancelado'}
            except Exception as error:
                logging.exception('CAM calculation failed: %s',identifier)
                payload={'status':'failed','project_id':identifier,'error':str(error),'phase':'Cálculo interrompido'}
            payload['elapsed_s']=round(time.monotonic()-self.job_started[identifier],3)
            logging.info('CAM calculation %s: %s in %.3fs',identifier,payload['status'],payload['elapsed_s'])
            # Persist compact diagnostics, keeping the large motion in result.json.
            if folder.exists():
                diagnostic={k:v for k,v in payload.items() if k not in ('motion','inspection')}
                try:write_json(folder/'job.json',diagnostic)
                except OSError:logging.exception('Could not persist CAM job diagnostics: %s',identifier)
            with self.lock:
                self.jobs[identifier]=payload;self.active=None;self.cancel_signals.pop(identifier,None)
        try:self.pool.submit(run)
        except RuntimeError:
            with self.lock:
                self.active=None
                self.jobs.pop(identifier,None);self.job_started.pop(identifier,None);self.cancel_signals.pop(identifier,None)
            raise
        return {'job':identifier,'status':'running'}

    def cancel(self,identifier):
        with self.lock:
            if identifier not in self.jobs:raise ValueError('Cálculo não encontrado')
            if identifier in self.cancel_signals:
                self.cancel_signals[identifier].set()
                return {'status':'cancelling','job':identifier}
            return {'status':self.jobs[identifier]['status'],'job':identifier}

    def shutdown(self):
        self.commands.close()
        with self.lock:
            self.stopping=True
            for signal in self.cancel_signals.values():signal.set()
        self.pool.shutdown(wait=True,cancel_futures=True)

    def job_state(self,identifier):
        with self.lock:
            if identifier not in self.jobs:raise ValueError('Cálculo não encontrado')
            state=self.jobs[identifier].copy()
            if state['status']=='running':
                state['elapsed_s']=round(time.monotonic()-self.job_started[identifier],3)
            return state

    def bundle(self,identifier):
        if identifier not in self.saved:raise ValueError('Projeto não encontrado nesta sessão')
        project=self.saved[identifier];folder=project.parent;buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('project.json','model.stl','result.json','ui.json'):
                if (folder/name).exists():archive.write(folder/name,name)
        return buf.getvalue()

    def restore(self,data):
        if len(data)>MAX_BYTES:raise ValueError('Projeto maior que 128 MiB')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members={p.filename:p for p in archive.infolist()}
            if not {'project.json','model.stl'}<=members.keys():raise ValueError('ZIP precisa conter project.json e model.stl')
            if sum(p.file_size for p in members.values())>MAX_BYTES:raise ValueError('Projeto descompactado excede 128 MiB')
            record=json.loads(archive.read('project.json'))
            asset=self.upload(archive.read('model.stl'),'STL do projeto')
            identifier=uuid.uuid4().hex;folder=self.outputs/identifier;folder.mkdir()
            (folder/'model.stl').write_bytes(self.asset(asset)['path'].read_bytes())
            # The only accepted input file is the model inside this ZIP.
            record['source']['path']='model.stl';write_json(folder/'project.json',record)
            _,mesh,tool,settings,inspection=load_project(folder/'project.json')
            p={'units':record['source']['units'],'rotation':mesh.rotation,
               'translation_mm':mesh.translation,'xy_origin':'keep','z_origin':'keep'}
            scene=self.inspect(asset,p)
            # Recalculation is required after importing. Do not trust a supplied
            # result.json as a validated motion plan.
            scene.update({'tool':tool.as_dict(),'settings':asdict(settings),'inspection':inspection,
                          'notes':record['notes'],'operations':record.get('operations',{}),'motion':None})
            if 'ui.json' in members:
                ui=self.ui_metadata(json.loads(archive.read('ui.json')))
                scene.update(ui);write_json(folder/'ui.json',ui)
            self.saved[identifier]=folder/'project.json'
            return scene


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,mime='application/json'):
            if mime=='application/json':data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf8')
            self.send_response(status);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY')
            self.end_headers();self.wfile.write(data)
        def local_request(self):
            host=self.headers.get('Host','')
            valid={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if host not in valid:raise PermissionError('Servidor disponível somente pelo endereço local')
            origin=self.headers.get('Origin')
            if origin and origin not in {'http://'+h for h in valid}:raise PermissionError('Origem recusada')
        def body(self):
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>MAX_BYTES:raise ValueError('Tamanho da requisição inválido')
            data=self.rfile.read(size)
            if len(data)!=size:raise ValueError('Requisição incompleta')
            return data
        def do_GET(self):
            try:
                self.local_request();url=urlparse(self.path);path=url.path
                if path=='/api/bootstrap':
                    try:presets=app.presets.read()
                    except (ValueError,OSError) as error:presets={'presets':[],'last_used':None,'selected_id':None,'error':str(error)}
                    return self.send(200,{'application':'cam-local-v1','command_api':1,'token':app.token,'tools':ToolLibrary.load(app.tools_path).as_dict()['tools'],'presets':presets})
                if path=='/api/demo':return self.send(200,app.demo())
                if path.startswith('/api/jobs/'):
                    identifier=path.rsplit('/',1)[-1]
                    state=app.job_state(identifier)
                    if parse_qs(url.query).get('summary')==['1']:
                        motion=state.pop('motion',None);state.pop('inspection',None)
                        if motion:state['motion_summary']={
                            'moves':len(motion['moves']),'timing':motion['timing'],
                            'counts':motion['counts'],'validation':motion['validation'],
                            'operations':motion['operations']}
                    return self.send(200,state)
                if path.startswith('/api/download/'):
                    return self.send(200,app.bundle(path.rsplit('/',1)[-1]),'application/zip')
                if path.startswith('/api/nc/'):
                    identifier=path.rsplit('/',1)[-1]
                    if identifier not in app.exports:raise ValueError('Exportação não encontrada')
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                    payload=app.exports[identifier].read_bytes()
                    self.send_header('Content-Length',str(len(payload)))
                    self.send_header('Content-Disposition','attachment; filename="'+app.exports[identifier].name+'"')
                    self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(payload);return
                vendor={'/vendor/three.module.js':THREE/'build/three.module.js',
                        '/vendor/three.core.js':THREE/'build/three.core.js',
                        '/vendor/manifold.js':ROOT/'work/ui-runtime/node_modules/manifold-3d/manifold.js',
                        '/vendor/manifold.wasm':ROOT/'work/ui-runtime/node_modules/manifold-3d/manifold.wasm',
                        '/vendor/OrbitControls.js':THREE/'examples/jsm/controls/OrbitControls.js'}
                target=vendor.get(path)
                if target is None:
                    target=(STATIC/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                    if not target.is_relative_to(STATIC.resolve()):raise PermissionError('Caminho inválido')
                if not target.is_file():return self.send(404,{'error':'Arquivo não encontrado'})
                mime='text/javascript' if target.suffix in ('.js','.mjs') else 'application/wasm' if target.suffix=='.wasm' else mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                return self.send(200,target.read_bytes(),mime)
            except PermissionError as error:self.send(403,{'error':str(error)})
            except (ValueError,OSError,KeyError,zipfile.BadZipFile) as error:self.send(400,{'error':str(error)})
        def do_POST(self):
            try:
                self.local_request()
                if not secrets.compare_digest(self.headers.get('X-Cam-Token',''),app.token):raise PermissionError('Sessão local inválida; recarregue a página')
                url=urlparse(self.path)
                data=self.body()
                if url.path=='/api/upload':
                    asset=app.upload(data,parse_qs(url.query).get('name',['modelo.stl'])[0])
                    return self.send(200,{'asset':asset})
                if url.path=='/api/import-project':return self.send(200,app.restore(data))
                record=json.loads(data)
                if url.path=='/api/presets':return self.send(200,app.presets.update(record))
                if url.path=='/api/commands/submit':return self.send(202,app.commands.submit(record['command'],record.get('timeout_s',30)))
                if url.path=='/api/commands/next':return self.send(200,app.commands.next(record['client'],record.get('wait_s',20)))
                if url.path=='/api/commands/result':return self.send(200,app.commands.result(record['command_id']))
                if url.path=='/api/commands/complete':return self.send(200,app.commands.complete(record['command_id'],record['client'],record.get('result'),record.get('error')))
                if url.path=='/api/validate-config':
                    _,tool,settings,options,placement,ui=app.validate_request(record)
                    if options.roughing_enabled and settings.stepover_mm>tool.diameter_mm:raise ValueError('Stepover maior que o diâmetro da ferramenta')
                    if options.machining_mode=='smart':app.smart_plan(record)
                    elif options.roughing_enabled and settings.stock_top_mm-settings.bottom_mm>tool.cutting_length_mm:raise ValueError('Profundidade maior que o comprimento de corte da ferramenta')
                    return self.send(200,{'tool':tool.as_dict(),'settings':asdict(settings),'operations':asdict(options),'placement':placement,'ui':ui})
                if url.path=='/api/window/show':
                    if app.on_show:threading.Thread(target=app.on_show,daemon=True).start()
                    return self.send(200,{'shown':bool(app.on_show)})
                if url.path=='/api/shutdown':
                    self.send(200,{'stopping':True})
                    if app.on_close:threading.Thread(target=app.on_close,daemon=True).start()
                    threading.Thread(target=self.server.shutdown,daemon=True).start();return
                if url.path=='/api/inspect':return self.send(200,app.inspect(record['asset'],record['placement']))
                if url.path=='/api/drill-inspect':return self.send(200,app.inspect_drill(record))
                if url.path=='/api/smart-plan':return self.send(200,app.smart_plan(record))
                if url.path=='/api/calculate':return self.send(202,app.calculate(record))
                if url.path=='/api/cancel':return self.send(202,app.cancel(record['job']))
                if url.path=='/api/export':return self.send(200,app.export(record['project_id']))
                if url.path=='/api/save':
                    identifier,project=app.prepare(record)
                    return self.send(200,{'project_id':identifier,'path':str(project)})
                if url.path=='/api/tools':
                    tool=Tool.from_dict(record['tool']);library=ToolLibrary.load(app.tools_path)
                    library.add(tool,replace=bool(record.get('replace',False)));library.save(app.tools_path)
                    return self.send(200,{'tools':library.as_dict()['tools']})
                self.send(404,{'error':'Operação não encontrada'})
            except PermissionError as error:self.send(403,{'error':str(error)})
            except RuntimeError as error:self.send(409,{'error':str(error)})
            except (ValueError,OSError,TypeError,KeyError,zipfile.BadZipFile) as error:self.send(400,{'error':str(error)})
    return Handler


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();app=App()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(app))
    print(f'CAM local pronto: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.shutdown()


if __name__=='__main__':main()
