"""Keep the installed libraries' license texts with the public executable."""
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def collect(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'work/cam-ui/licenses').iterdir():
        if source.is_file():shutil.copyfile(source,destination/source.name)
    versions={'python':sys.version.split()[0],'node':subprocess.check_output(['node','--version'],text=True).strip(),'python_packages':{}}
    names=('numpy','pyclipr','pywebview','pythonnet','clr-loader','cffi','pycparser','proxy_tools','bottle',
           'typing_extensions','packaging','pyinstaller','pyinstaller-hooks-contrib')
    for name in names:
        try:dist=metadata.distribution(name)
        except metadata.PackageNotFoundError:continue
        versions['python_packages'][name]=dist.version
        for item in dist.files or []:
            path=Path(str(item))
            if not path.name.upper().startswith(('LICENSE','COPYING','COPYRIGHT','AUTHORS')):continue
            source=dist.locate_file(item)
            if source.is_file():
                target=destination/name/Path(*[part for part in path.parts if part not in ('.','..')])
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for base in (Path(sys.base_prefix),Path(sys.base_prefix)/'Lib'):
        for name in ('LICENSE.txt','LICENSE'):
            source=base/name
            if source.is_file():shutil.copyfile(source,destination/'Python-LICENSE.txt')
    (destination/'VERSIONS.json').write_text(json.dumps(versions,indent=2),encoding='utf8')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path)
    collect(parser.parse_args().destination)
