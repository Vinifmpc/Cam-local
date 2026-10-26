# Build with the Python environment in requirements-desktop.txt.
from pathlib import Path
import shutil
import sys
from PyInstaller.utils.hooks import collect_data_files

ROOT=Path(SPECPATH).resolve().parents[1]
UI=ROOT/'work/cam-ui'
datas=[]
# Keep the certificate policy shipped with this build's Python runtime.
certificate=Path(sys.base_prefix)/'Lib/codex-rejected-cas.pem'
if certificate.exists():datas.append((str(certificate),'.'))
def add(path,destination=None):
    path=Path(path)
    if path.is_file():datas.append((str(path),destination or path.parent.relative_to(ROOT).as_posix()))
def tree(path):
    for p in Path(path).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:add(p)

tree(UI/'static')
for name in ('build/three.module.js','build/three.core.js','examples/jsm/controls/OrbitControls.js','LICENSE','package.json'):
    add(ROOT/'work/ui-runtime/node_modules/three'/name)
for name in ('manifold.js','manifold.wasm','LICENSE','package.json'):
    add(ROOT/'work/ui-runtime/node_modules/manifold-3d'/name)
for p in (ROOT/'work/geometry-runtime/node_modules').rglob('*'):
    if not p.is_file():continue
    relative=p.relative_to(ROOT/'work/geometry-runtime/node_modules')
    if any(part in ('test','tests','example','examples','fixtures') for part in relative.parts):continue
    if p.suffix.lower() in ('.stl','.nc'):continue
    if relative.parts[:2]==('@opencamlib','opencamlib'):
        tail=relative.parts[2:]
        if not (tail[0]=='lib' and p.suffix=='.js' or
                tail==('package.json',) or tail[:3]==('build','Release','windows-nodejs-x64')):continue
    add(p)
add(ROOT/'work/roughing/ocl_contact_bridge.cjs')
node=shutil.which('node')
if not node:raise RuntimeError('Node x64 is needed to build the standalone CAM motor')
datas.append((node,'runtimes'))
tree(UI/'licenses')
datas+=collect_data_files('webview')

a=Analysis([str(UI/'desktop_app.py')],pathex=[str(UI),str(ROOT/'work/roughing'),str(ROOT/'work/geometry-libs')],
    binaries=[],datas=datas,hiddenimports=['webview.platforms.winforms','webview.platforms.edgechromium'],
    hookspath=[],runtime_hooks=[],excludes=['PyQt5','PyQt6','PySide2','PySide6','gi','cefpython3',
      'webview.platforms.qt','webview.platforms.gtk','webview.platforms.cocoa','webview.platforms.cef','webview.platforms.android',
      'matplotlib','pandas','scipy','IPython','notebook','pytest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='CAM Local',debug=False,bootloader_ignore_signals=False,
    strip=False,upx=False,console=False,disable_windowed_traceback=False,icon=str(UI/'desktop.ico'))
