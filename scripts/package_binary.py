"""Create a public Windows package without models, jobs, logs or runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path)
    args=parser.parse_args();folder=ROOT/'dist/CAM-local-Windows';folder.mkdir(parents=True,exist_ok=True)
    executable=args.exe or folder/'CAM Local.exe'
    if not executable.is_file():raise SystemExit('Gere o executável antes de empacotar.')
    target=folder/'CAM Local.exe'
    if executable.resolve()!=target.resolve():shutil.copyfile(executable,target)
    from collect_licenses import collect
    collect(folder/'licenses')
    for source,name in [(ROOT/'LICENSE','LICENSE'),(ROOT/'THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md'),
                        (ROOT/'docs/COMANDOS.md','COMANDOS.md'),(ROOT/'scripts/cam-command.ps1','cam-command.ps1')]:
        shutil.copyfile(source,folder/name)
    sources=folder/'sources';sources.mkdir(exist_ok=True)
    for archive in (ROOT/'third_party').glob('*.tar.gz'):shutil.copyfile(archive,sources/archive.name)
    (folder/'LEIA-ME.md').write_text('''# CAM Local para Windows

Abra **CAM Local.exe**. A janela inicia sem peça; use **Abrir STL** ou **Abrir projeto**. O exemplo opcional é uma placa com bolsão gerada pelo aplicativo.

O WebView2 precisa estar instalado no Windows. Dados persistentes ficam em `%LOCALAPPDATA%/CAMLocal`; este pacote não inclui projetos ou NCs pessoais.

Use os ícones Girar, Origem e Mover na vista 3D para posicionar a peça. O modo inteligente usa Rough nos detalhes e pode recortar miolos passantes antes de liberar o exterior, preservando a sobra para retirada. Confira ferramenta, unidade, posicionamento e avanços; simule antes de exportar. O motor é experimental e não se conecta à máquina.

Em Zero, selecione a borda da peça ou informe coordenadas para definir X0/Y0; o Z é independente. Em Girar, o preparo de segunda face vira a peça e deixa apenas Rough, protegendo a fixação central com o diâmetro e a altura informados. Use o mesmo zero G54 na CNC.

Presets de usinagem salvam ferramenta, avanços, plunge, RPM e ajustes de corte. Os últimos valores também são restaurados automaticamente ao reabrir. Profundidades, posicionamento e regiões continuam específicos da peça.

Comandos estão em COMANDOS.md. O código original é MIT; bibliotecas mantêm suas próprias licenças. Fontes de terceiros incluídos ficam em sources/. O código do CAM Local acompanha a publicação no GitHub e permite reconstruir o EXE após modificar as bibliotecas.
''',encoding='utf8')
    # Explicit inputs keep unrelated output files out of a subsequent release.
    files=[folder/name for name in ('CAM Local.exe','LEIA-ME.md','LICENSE','THIRD_PARTY_NOTICES.md','COMANDOS.md','cam-command.ps1')]
    files += sorted(p for part in ('licenses','sources') for p in (folder/part).rglob('*') if p.is_file())
    manifest=folder/'SHA256SUMS.txt'
    manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(folder).as_posix()+'\n' for p in files),encoding='utf8')
    archive=ROOT/'dist/CAM-Local-Windows-publico.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in files+[manifest]:bundle.write(path,Path(folder.name)/path.relative_to(folder))
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files)+1}))


if __name__=='__main__':main()
