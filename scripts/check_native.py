"""Test a native EXE with its supported commands and synthetic example only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'work/cam-ui'),str(ROOT/'work/roughing')]
from command_client import CommandClient


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--profile',type=Path);parser.add_argument('--report',type=Path,default=ROOT/'dist/native-test.json')
    args=parser.parse_args();profile=(args.profile or Path(tempfile.mkdtemp(prefix='cam-local-native-'))).resolve()
    user=(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'CAMLocal').resolve()
    if profile==user or (profile/'desktop-runtime.json').exists():raise ValueError('Use um perfil isolado sem janela em execução.')
    profile.mkdir(parents=True,exist_ok=True);args.report.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'running','checks':[]};client=None
    def save():args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    def check(name,condition):
        if not condition:raise AssertionError(name)
        report['checks'].append(name);save();print(name,flush=True)
    def start():
        reply=profile/'startup-reply.json'
        process=subprocess.run([str(args.exe.resolve()),'--data-dir',str(profile),'--start',
            '--command-json',json.dumps({'action':'ping'}),'--report',str(reply)],timeout=90)
        response=json.loads(reply.read_text('utf8'))
        check('EXE command startup succeeds',process.returncode==0 and response['status']=='complete')
        return CommandClient(profile)
    def close():
        client.execute({'action':'app.close'})
        deadline=time.monotonic()+20
        while (profile/'desktop-runtime.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('A janela de teste não encerrou')
            time.sleep(.2)
    try:
        client=start();run=lambda action,**values:client.execute({'action':action,**values})
        state=run('state')
        check('Fresh window starts empty',state['model'] is None and state['simulation']['moves']==0)
        check('Empty workspace is visible and project actions are disabled',state['workspace']=={
            'empty':True,'empty_visible':True,'can_calculate':False,'can_save':False})
        scene=run('demo.open')
        check('Optional example is a small generated pocket plate',scene['model']['bounds_mm']['size']==[20,20,5]
            and scene['model']['triangle_count']==68 and scene['simulation']['moves']==0)
        check('Loaded model enables preparation and save',not scene['workspace']['empty_visible']
              and scene['workspace']['can_calculate'] and scene['workspace']['can_save'])
        task=run('calculate.start');status=run('calculate.status',job=task['job'])
        check('Progress status is available',status['job']==task['job'])
        result=run('calculate.wait',job=task['job'],timeout_s=180)
        check('Generated example reaches the real engine',result['status']=='complete'
            and result['motion_summary']['validation']['status']=='passed' and result['motion_summary']['moves']>0)
        exported=run('nc.export',path=str(profile/'example.nc'),overwrite=True,timeout_s=180)
        check('Export independently validates NC',exported['report']['status']=='passed' and Path(exported['path']).stat().st_size>100)
        run('simulation.set',mode='paths',speed=2)
        run('simulation.seek',fraction=1);ready=run('simulation.wait',surface='grid',timeout_s=120)
        samples=run('simulation.sample',points=[[10,10],[2,2],[-4,-4]])['samples']
        check('Grid simulates pocket removal and preserves the part and waste corner',ready['stock_ready']
            and abs(samples[0]['z_mm']+2)<.001 and abs(samples[1]['z_mm'])<.001 and abs(samples[2]['z_mm'])<.001)
        saved=run('project.save',path=str(profile/'example-project.zip'),overwrite=True)
        restored=run('project.open',path=saved['path'])
        check('Project roundtrip preserves geometry and requires recalculation',restored['model']['bounds_mm']['size']==[20,20,5]
            and restored['simulation']['moves']==0)
        close();client=start();state=run('state')
        check('Restart stays empty even after using an example and saving a project',state['model'] is None
            and state['workspace']['empty_visible'] and state['simulation']['moves']==0)
        report['status']='passed'
    except Exception as error:report.update(status='failed',error=str(error));raise
    finally:
        if client:
            try:close();report['isolated_window_closed']=True
            except Exception as error:report['close_note']=str(error)
        save()


if __name__=='__main__':main()
