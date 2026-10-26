"""Run the portable engine/UI suite; no personal fixtures or app profile."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path)
    args=parser.parse_args();node=shutil.which('node')
    if not node:raise SystemExit('Node.js não encontrado. Execute scripts/setup.ps1.')
    commands=[[sys.executable,'-m','unittest','discover','-s',folder,'-p','test_*.py']
              for folder in ('work/roughing','work/cam-ui')]
    commands += [[node,str(path.relative_to(ROOT))] for path in sorted((ROOT/'work/cam-ui').glob('test_*.mjs'))]
    commands += [[node,'--check','work/cam-ui/static/app.js']]
    results=[]
    for command in commands:
        started=time.monotonic()
        process=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=240)
        output=process.stdout+process.stderr;count=re.search(r'Ran (\d+) tests',output)
        row={'command':command[1:],'status':'passed' if process.returncode==0 else 'failed',
             'tests':int(count[1]) if count else None,'elapsed_s':round(time.monotonic()-started,3)}
        results.append(row);print(json.dumps(row),flush=True)
        if process.returncode:print(output);break
    report={'status':'passed' if all(row['status']=='passed' for row in results) else 'failed','checks':results}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2),encoding='utf8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
