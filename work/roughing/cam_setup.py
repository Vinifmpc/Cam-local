"""Small command-line front end for persistent tools and STL setups.

Run --help. No machine connection, spindle command, or G-code emission.
"""
import argparse
import json
from pathlib import Path
import sys
from cam_tools import Tool,ToolLibrary,write_json
from mesh_geometry import place_stl,topology_report
from cam_project import RoughingSettings,create_project,load_project,calculate_project

FLIP_X=[[1,0,0],[0,-1,0],[0,0,-1]]


def placement(parser):
    parser.add_argument('--stl',required=True)
    parser.add_argument('--units',required=True,choices=['mm','inch'],help='Unidade das coordenadas do STL')
    parser.add_argument('--flip-x',action='store_true',help='Rotação de 180 graus em X')
    parser.add_argument('--xy-origin',choices=['keep','minimum','center'],default='keep')
    parser.add_argument('--z-origin',choices=['keep','top','bottom'],default='keep')
    parser.add_argument('--translate-mm',type=float,nargs=3,default=[0,0,0],metavar=('X','Y','Z'))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Ferramentas, STL e projetos do motor de desbaste experimental')
    commands=parser.add_subparsers(dest='command',required=True)
    listing=commands.add_parser('tool-list',help='Listar biblioteca')
    listing.add_argument('--library',required=True)
    add=commands.add_parser('tool-add',help='Cadastrar ou substituir ferramenta de topo reto')
    add.add_argument('--library',required=True)
    add.add_argument('--id',required=True);add.add_argument('--name',required=True)
    add.add_argument('--units',required=True,choices=['mm','inch'])
    add.add_argument('--diameter',type=float,required=True)
    add.add_argument('--cutting-length',type=float,required=True)
    add.add_argument('--shank-diameter',type=float);add.add_argument('--overall-length',type=float)
    add.add_argument('--flutes',type=int);add.add_argument('--feed',type=float)
    add.add_argument('--plunge',type=float);add.add_argument('--spindle-rpm',type=float)
    add.add_argument('--notes',default='');add.add_argument('--replace',action='store_true')
    inspect=commands.add_parser('inspect',help='Conferir formato, dimensões, orientação e malha')
    placement(inspect);inspect.add_argument('--out')
    prepare=commands.add_parser('prepare',help='Salvar configuração validada com cópia da ferramenta')
    placement(prepare)
    prepare.add_argument('--library',required=True);prepare.add_argument('--tool',required=True)
    prepare.add_argument('--settings',required=True,help='JSON RoughingSettings; todas as distâncias em mm')
    prepare.add_argument('--out',required=True);prepare.add_argument('--notes',default='')
    check=commands.add_parser('check',help='Reabrir projeto, conferir hash do STL e validar configuração')
    check.add_argument('--project',required=True)
    run=commands.add_parser('calculate',help='Calcular o desbaste; rampas opcionais; saída JSON')
    run.add_argument('--project',required=True);run.add_argument('--out',required=True)
    run.add_argument('--motion',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='tool-list':
            result=ToolLibrary.load(args.library).as_dict()
        elif args.command=='tool-add':
            library=ToolLibrary.load(args.library) if Path(args.library).exists() else ToolLibrary()
            tool=Tool.from_units(id=args.id,name=args.name,units=args.units,diameter=args.diameter,
                cutting_length=args.cutting_length,shank_diameter=args.shank_diameter,
                overall_length=args.overall_length,flutes=args.flutes,feed=args.feed,
                plunge=args.plunge,spindle_rpm=args.spindle_rpm,notes=args.notes)
            library.add(tool,replace=args.replace);library.save(args.library)
            result=tool.as_dict()
        elif args.command in ('inspect','prepare'):
            options={'units':args.units,'rotation':FLIP_X if args.flip_x else None,
                     'xy_origin':args.xy_origin,'z_origin':args.z_origin,'translation_mm':args.translate_mm}
            if args.command=='inspect':
                mesh=place_stl(args.stl,**options)
                result={**mesh.summary(),'topology':topology_report(mesh)}
                if args.out:
                    if Path(args.out).resolve()==Path(args.stl).resolve():
                        raise ValueError('Relatório não pode sobrescrever o STL')
                    write_json(args.out,result)
            else:
                protected={Path(p).resolve() for p in (args.stl,args.library,args.settings)}
                if Path(args.out).resolve() in protected:
                    raise ValueError('Projeto não pode sobrescrever STL, biblioteca ou parâmetros')
                tool=ToolLibrary.load(args.library).get(args.tool)
                settings=RoughingSettings.from_dict(json.loads(Path(args.settings).read_text(encoding='utf-8-sig')))
                result=create_project(args.stl,args.out,tool=tool,settings=settings,notes=args.notes,**options)['inspection']
        elif args.command=='check':
            result=load_project(args.project)[4]
        else:
            project=Path(args.project).resolve()
            record=load_project(project)[0]
            source=Path(record['source']['path'])
            if not source.is_absolute():source=project.parent/source
            if Path(args.out).resolve() in (project,source.resolve()):
                raise ValueError('Resultado não pode sobrescrever projeto ou STL')
            result=calculate_project(project,include_motion=args.motion)
            write_json(args.out,result)
            job=result['roughing']
            result={'output':str(Path(args.out).resolve()),'tool_id':job['tool_profile']['id'],
                    'layers':job['layer_count'],'cutting_edges':job['cutting_edges'],
                    'polylines':job['polyline_count'],'motion_included':bool(args.motion),
                    'gcode_emitted':False}
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (ValueError,OSError,RuntimeError,TimeoutError) as error:
        print('Erro: '+str(error),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
