"""Package only the standalone CNCjs widget, without models or credentials."""
import hashlib,json
from pathlib import Path
import shutil,zipfile
ROOT=Path(__file__).resolve().parents[1]
FILES=('index.html','style.css','app.js','connection.js','boot.js','install.html','install.js','README.md')
def main():
    source=ROOT/'work/cncjs-widget';destination=ROOT/'outputs/CNCjs-CAM-Perfil'
    destination.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for name in FILES:
        path=source/name;target=destination/name
        data=path.read_bytes();target.write_bytes(data)
        manifest.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    shutil.copy2(ROOT/'LICENSE',destination/'LICENSE')
    (destination/'MANIFEST.json').write_text(json.dumps({'application':'CAM Local · CNCjs','format':1,'files':manifest},ensure_ascii=False,indent=2),encoding='utf8')
    archive=destination.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for name in (*FILES,'LICENSE','MANIFEST.json'):output.write(destination/name,Path('cam-perfil')/name)
    print(json.dumps({'folder':str(destination),'zip':str(archive),'files':len(manifest)}))
if __name__=='__main__':main()
