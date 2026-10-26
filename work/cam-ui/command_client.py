"""JSON command client. Filesystem access stays in this local CLI process."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cam_tools import write_json


def command_schema():
    from dataclasses import fields
    from cam_project import RoughingSettings
    from cam_operations import OperationSettings
    from cam_tools import Tool
    return {'protocol': 1, 'format': 'Um objeto com action, uma lista, ou {commands:[...]}. Execução sequencial; para no primeiro erro.',
        'units': 'mm, mm/min, segundos; coordenadas no modelo já posicionado',
        'actions': {
            'schema': {}, 'ping': {}, 'state': {'detail': 'true inclui vértices das regiões'},
            'stl.open': {'path':'arquivo.stl', 'placement':'opcional: units, rotation, translation_mm, xy_origin, z_origin'},
            'project.open': {'path':'projeto.zip'}, 'project.save': {'path':'destino.zip','overwrite':False},
            'demo.open': {}, 'config.patch': {'settings':'campos parciais','operations':'campos parciais','stock':'x0,y0,x1,y1,step (.25/.5/1)','notes':'texto'},
            'placement.set': {'placement':'units mm/inch, rotation matriz 3x3, translation_mm vetor 3, xy_origin minimum/keep/center, z_origin top/keep/bottom'},
            'tools.list': {}, 'tool.set': {'id':'ID cadastrado, ou tool com campos'},
            'tool.save': {'tool':'registro completo/parcial da ferramenta selecionada','replace':False},
            'regions.add': {'kind':'keepin/keepout','shape':'rectangle: min/max [x,y]; circle: center/radius; ellipse: center/radius_x/radius_y; polygon/freehand: points [[x,y],...]'},
            'regions.remove': {'kind':'keepin/keepout','index':'índice a partir de zero'},
            'regions.picker': {'kind':'keepin/keepout; mostra os cinco ícones de formas'},
            'regions.draw': {'kind':'keepin/keepout','shape':'rectangle/circle/ellipse/polygon/freehand; inicia o desenho após escolher o ícone'},
            'regions.cancel': {'description':'Fecha as formas e cancela o desenho sem criar região'},
            'cutout.recovery.apply': {'description':'Aplica a sugestão ativa de soltar a peça, somente externo, após erro de fresa nos internos; requer novo cálculo'},
            'regions.clear': {'kind':'keepin/keepout/all'}, 'operation.tab': {'tab':'rough/cutout/drill'},
            'operations.set': {'order':'permutação de [roughing,cutout,drill]; duas IDs legadas também aceitas','enabled':'objeto parcial: roughing/cutout/drill booleanos'},
            'drill.inspect': {'description':'Detecta furos circulares e compara diâmetro/comprimento da fresa e opções do Drill, sem calcular nem alterar o projeto'},
            'machining.plan': {'description':'Confere o plano inteligente Rough + Cutout sem iniciar cálculo; config.patch operations.machining_mode=smart ativa o modo. Fundo do bruto e pele vazios usam os valores automáticos apresentados no plano.'},
            'calculate.start': {}, 'calculate.status': {'job':'opcional; cálculo atual/último por padrão'},
            'calculate.wait': {'job':'opcional','timeout_s':900}, 'calculate.cancel': {'job':'opcional'},
            'nc.export': {'path':'destino.nc','overwrite':False},
            'view.set': {'preset':'iso/top/front','fit':'booleano','zoom':'.05 a 100','position':'vetor 3 opcional','target':'vetor 3 opcional','depth_coloring':'booleano; cores por profundidade e bordas dos degraus'},
            'view.capture': {'path':'destino.png','overwrite':False},
            'simulation.set': {'mode':'paths/stock','speed':'.1 a 100; 1 = feedrate real','layers':'model/paths/rapids/regions: booleanos'},
            'simulation.play': {}, 'simulation.pause': {},
            'simulation.seek': {'time_s':'segundos, ou fraction entre 0 e 1'},
            'simulation.reset': {}, 'simulation.wait': {'surface':'grid/solid','timeout_s':120},
            'simulation.sample': {'points':'1 a 64 posições XY [[x,y],...]; lê a altura das células da grade atual após simulation.wait, sem alterar a reprodução'},
            'diagnostics': {'lines':'últimas linhas do log, 1 a 200'},
            'command.result': {'command_id':'identificador de comando que excedeu o prazo'}, 'app.close': {}},
        'fields': {name:[field.name for field in fields(cls)] for name,cls in (
            ('settings',RoughingSettings),('operations',OperationSettings),('tool',Tool))},
        'notes': ['Configurações são validadas antes de alterar a interface.',
            'Abrir STL/alterar posicionamento redefine profundidades e regiões para o modelo novo.',
            'Alterações de usinagem invalidam percursos. Espere/cancele o cálculo antes de editar.',
            'Timeout de comando já iniciado retorna command_id; consulte o resultado, sem repetir a ação.',
            'A interface usa region_mode=layer e compress_collinear=true.',
            'A reprodução precisa da janela visível: ao ocultar/minimizar, ela pausa como no uso manual.']}


class CommandError(RuntimeError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details=details


class CommandClient:
    def __init__(self, folder, port=None):
        self.folder=Path(folder)
        if port is None:
            try:port=json.loads((self.folder/'desktop-runtime.json').read_text(encoding='utf8'))['port']
            except (OSError,KeyError,ValueError) as error:raise CommandError('Abra o CAM Local ou utilize --start.') from error
        if type(port) is not int or not 1 <= port <= 65535:raise CommandError('Porta local inválida')
        self.base=f'http://127.0.0.1:{port}'
        self.token=None
        boot=self.http('/api/bootstrap',timeout=3)
        if boot.get('application')!='cam-local-v1' or boot.get('command_api')!=1:
            raise CommandError('Esta instância precisa da versão com controle por comandos.')
        self.token=boot['token']
        self.last_job=None

    def http(self, path, payload=None, *, raw=None, binary=False, timeout=300):
        headers={}
        if self.token:headers['X-Cam-Token']=self.token
        data=raw
        if payload is not None:
            data=json.dumps(payload,allow_nan=False).encode('utf8');headers['Content-Type']='application/json'
        req=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:
                result=response.read()
            return result if binary else json.loads(result)
        except urllib.error.HTTPError as error:
            try:message=json.loads(error.read()).get('error',str(error))
            except ValueError:message=str(error)
            raise CommandError(message) from error
        except (urllib.error.URLError,TimeoutError,OSError) as error:
            raise CommandError('Não foi possível comunicar com o aplicativo: '+str(error)) from error

    def ui(self, command):
        timeout=command.get('timeout_s',30)
        submitted=self.http('/api/commands/submit',{'command':command,'timeout_s':min(timeout,300)})
        identifier=submitted['command_id'];deadline=time.monotonic()+timeout+1
        while True:
            result=self.http('/api/commands/result',{'command_id':identifier},timeout=5)
            if result['status']=='complete':return result.get('result')
            if result['status'] in ('failed','expired'):raise CommandError(result['error'],command_id=identifier,status=result['status'])
            if time.monotonic()>deadline:
                raise CommandError('O comando excedeu o prazo. Consulte command.result antes de repetir.',command_id=identifier,status=result['status'])
            time.sleep(.1)

    def job_id(self, command):
        if command.get('job'):return command['job']
        if self.last_job:return self.last_job
        state=self.ui({'action':'state'})['calculation']
        job=state['active_job'] or state['last_job']
        if not job:raise CommandError('Nenhum cálculo iniciado nesta sessão')
        return job

    @staticmethod
    def destination(command):
        path=Path(command['path']).expanduser().resolve()
        if path.exists() and not command.get('overwrite',False):raise CommandError('Destino já existe; utilize overwrite:true: '+str(path))
        if not path.parent.is_dir():raise CommandError('Pasta de destino inexistente: '+str(path.parent))
        return path

    def execute(self, command):
        action=command['action']
        if action=='schema':return command_schema()
        if action=='ping':return {'application':'cam-local-v1','command_api':1,'port':int(self.base.rsplit(':',1)[1])}
        if action=='command.result':return self.http('/api/commands/result',{'command_id':command['command_id']})
        if action=='diagnostics':
            count=command.get('lines',40)
            if type(count) is not int or not 1<=count<=200:raise CommandError('lines deve ficar entre 1 e 200')
            path=self.folder/'desktop.log'
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-65536));tail=stream.read().decode('utf8',errors='replace')
            return {'path':str(path),'lines':tail.splitlines()[-count:]}
        if action=='stl.open':
            source=Path(command['path']).expanduser().resolve()
            if source.stat().st_size>128*1024*1024:raise CommandError('STL maior que 128 MiB')
            asset=self.http('/api/upload?name='+urllib.parse.quote(source.name),raw=source.read_bytes())
            return self.ui({k:v for k,v in {**command,'asset':asset['asset']}.items() if k!='path'})
        if action=='project.open':
            source=Path(command['path']).expanduser().resolve()
            if source.stat().st_size>128*1024*1024:raise CommandError('Projeto maior que 128 MiB')
            scene=self.http('/api/import-project',raw=source.read_bytes())
            return self.ui({'action':'project.adopt','scene':scene,'timeout_s':command.get('timeout_s',60)})
        if action in ('project.save','nc.export','view.capture'):
            destination=self.destination(command)
            result=self.ui({k:v for k,v in command.items() if k not in ('path','overwrite')})
            if action=='view.capture':payload=base64.b64decode(result['data_url'].split(',',1)[1],validate=True);result={'mime':result['mime']}
            else:
                route='/api/download/'+result['project_id'] if action=='project.save' else '/api/nc/'+result['export_id']
                payload=self.http(route,binary=True)
            # Exclusive creation unless overwrite was explicitly requested.
            with destination.open('wb' if command.get('overwrite',False) else 'xb') as stream:stream.write(payload)
            result.update(path=str(destination),bytes=len(payload));return result
        if action in ('calculate.status','calculate.wait'):
            job=self.job_id(command);deadline=time.monotonic()+command.get('timeout_s',900)
            while True:
                state=self.http('/api/jobs/'+urllib.parse.quote(job,safe='')+'?summary=1')
                if action=='calculate.status':return {'job':job,**state}
                if state['status'] in ('failed','cancelled'):raise CommandError(state.get('error') or 'Cálculo cancelado',job=job,state=state)
                if state['status']=='complete':
                    # The normal UI poll must have adopted this exact result before
                    # the next export/simulation command in a batch can proceed.
                    ui=self.ui({'action':'state'})['calculation']
                    if ui['computed_project']==job:return {'job':job,**state}
                    if not ui['busy']:raise CommandError('Cálculo concluído para uma configuração anterior; recalcule.',job=job)
                if time.monotonic()>deadline:raise CommandError('Prazo de espera do cálculo excedido; o trabalho continua.',job=job,state=state)
                time.sleep(.5)
        if action=='calculate.cancel' and command.get('job'):return self.http('/api/cancel',{'job':command['job']})
        if action=='simulation.wait':
            surface=command.get('surface','grid')
            if surface not in ('grid','solid'):raise CommandError('surface deve ser grid ou solid')
            deadline=time.monotonic()+command.get('timeout_s',120)
            while True:
                state=self.ui({'action':'state'})['simulation']
                ready=state['stock_ready'] and not state['stock_busy'] and state['stock_applied']==state['stock_target']
                if ready and (surface=='grid' or state['solid_ready']):return state
                if time.monotonic()>deadline:raise CommandError('A simulação não ficou pronta dentro do prazo.',state=state)
                time.sleep(.3)
        if action=='app.close':return self.http('/api/shutdown',{})
        result=self.ui(command)
        if action=='calculate.start':self.last_job=result['job']
        return result


def connect(folder, port=None, start=False):
    try:return CommandClient(folder,port)
    except CommandError:
        if not start or port is not None:raise
    args=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('desktop_app.py'))]
    args.extend(['--data-dir',str(folder)])
    environment=os.environ.copy()
    if getattr(sys,'frozen',False):environment['PYINSTALLER_RESET_ENVIRONMENT']='1'
    subprocess.Popen(args,env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:return CommandClient(folder,port)
        except CommandError:time.sleep(.5)
    raise CommandError('O aplicativo não iniciou em 60 segundos. Consulte desktop.log.')


def run_commands(document, report_path, folder, *, port=None, start=False):
    report={'protocol':1,'status':'running','results':[]}
    write_json(report_path,report)
    try:
        commands=document.get('commands') if isinstance(document,dict) and 'commands' in document else document
        if isinstance(commands,dict):commands=[commands]
        if not isinstance(commands,list) or not 1<=len(commands)<=200:raise CommandError('Informe de 1 a 200 comandos JSON')
        if any(not isinstance(command,dict) or not isinstance(command.get('action'),str) for command in commands):raise CommandError('Cada comando deve conter action')
        client=None
        for index,command in enumerate(commands):
            report['current_index']=index;report['current_action']=command['action'];write_json(report_path,report)
            if command['action']=='schema':result=command_schema()
            else:
                if client is None:client=connect(folder,port,start)
                result=client.execute(command)
            report['results'].append({'action':command['action'],'result':result});write_json(report_path,report)
        report.update(status='complete');report.pop('current_index',None);report.pop('current_action',None)
    except Exception as error:
        report.update(status='failed',error=str(error))
        if isinstance(error,CommandError):report.update(error.details)
    write_json(report_path,report)
    return report
