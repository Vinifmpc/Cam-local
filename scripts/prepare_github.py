"""Curate a small source upload; never recurse through the development workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ENGINE='annular_pocket audit_gcode camadas_desbaste cam_operations cam_project cam_setup cam_tools cleared_area contour_flow cutout cutout_rest depth_staging drill fixture_travel grbl_post internal_cutouts layer_regions layer_roughing mesh_geometry motion_planner motion_timing parallel_workers planar_roughing reference_keepout region_core region_order roughing_compare rough_quality short_entries smart_planner stl_roughing track_index'.split()
UI='calculation_worker command_client command_control desktop_app server sample_model machining_presets grbl_controller'.split()


def source_files():
    files=[Path(name) for name in ('README.md','LICENSE','CONTRIBUTING.md','THIRD_PARTY_NOTICES.md',
           '.gitignore','.gitattributes','requirements.txt','requirements-dev.txt')]
    for folder in ('docs','scripts','.github/workflows','third_party','work/cncjs-widget'):
        files += [p.relative_to(ROOT) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    for folder,names in (('work/roughing',ENGINE),('work/cam-ui',UI)):
        files += [Path(folder)/(name+'.py') for name in names]
        files += [p.relative_to(ROOT) for p in (ROOT/folder).glob('test_*.py')]
    files += [p.relative_to(ROOT) for p in (ROOT/'work/cam-ui').glob('test_*.mjs')]
    for folder in ('work/cam-ui/static','work/cam-ui/licenses'):
        files += [p.relative_to(ROOT) for p in (ROOT/folder).rglob('*') if p.is_file()]
    files += [Path('work/cam-ui')/name for name in ('CAMLocal.spec','desktop.ico','package.json','requirements-desktop.txt')]
    files += [Path('work/roughing/ocl_contact_bridge.cjs')]
    for folder in ('ui-runtime','geometry-runtime'):
        files += [Path('work')/folder/name for name in ('package.json','package-lock.json')]
    return sorted(set(files))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,default=ROOT/'outputs/CAM-Local-GitHub')
    parser.add_argument('--update',action='store_true');args=parser.parse_args();destination=args.destination.resolve()
    if destination==ROOT or ROOT.is_relative_to(destination):raise SystemExit('Escolha uma pasta de saída dedicada.')
    marker=destination/'SOURCE_MANIFEST.json'
    if destination.exists() and any(destination.iterdir()) and not (args.update and marker.is_file()):
        raise SystemExit('A pasta de saída já contém arquivos; use outra pasta ou --update em um pacote anterior.')
    destination.mkdir(parents=True,exist_ok=True)
    marker.write_text(json.dumps({'format':1,'status':'preparing'}),encoding='utf8')
    records=[]
    for relative in source_files():
        source=ROOT/relative;target=destination/relative
        if not source.is_file():raise SystemExit('Fonte ausente: '+str(relative))
        if source.suffix.lower() in ('.exe','.nc','.stl','.node','.dll','.log'):raise SystemExit('Artefato inesperado: '+str(relative))
        target.parent.mkdir(parents=True,exist_ok=True)
        content=source.read_bytes()
        if source.suffix.lower() not in ('.ico','.gz'):content=content.replace(b'\r\n',b'\n')
        target.write_bytes(content)
        records.append({'path':relative.as_posix(),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    agent=destination/'AGENTS.md';agent.write_bytes((ROOT/'docs/AGENTS_PUBLIC.md').read_text('utf8').encode('utf8'))
    records.append({'path':'AGENTS.md','bytes':agent.stat().st_size,'sha256':hashlib.sha256(agent.read_bytes()).hexdigest()})
    # Test strings such as C:/secret.stl exercise hostile ZIP input; actual local
    # user paths, credentials, job data and analysis outputs must never ship.
    for record in records:
        path=destination/record['path']
        if path.suffix not in ('.py','.js','.mjs','.cjs','.md','.ps1','.json','.yml','.html','.css','.txt'):continue
        content=path.read_text('utf8')
        for fragment in ('C:'+ '/Users/','C:'+ '\\Users\\','github_'+'pat_','gh'+'p_','-----BEGIN '+'PRIVATE KEY-----'):
            if fragment in content:raise SystemExit('Revise conteúdo local/segredo em '+record['path'])
    manifest={'format':1,'application':'CAM Local','license':'MIT (original code)','files':records}
    marker.write_bytes(json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
    archive=destination.parent/'CAM-Local-GitHub.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for relative in [Path(row['path']) for row in records]+[Path(marker.name)]:
            bundle.write(destination/relative,Path(destination.name)/relative)
    if not (destination/'.git').exists():
        subprocess.run(['git','init','-b','main',str(destination)],check=True,capture_output=True)
    print(json.dumps({'folder':str(destination),'archive':str(archive),'files':len(records)+1,
        'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':main()
