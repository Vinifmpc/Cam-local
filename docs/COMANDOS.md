# Controle por comandos — CAM Local

O executável recebe comandos JSON e controla o mesmo projeto aberto na janela.
Não depende de mouse, teclado, navegador externo ou capturas de tela. O serviço
escuta apenas em `127.0.0.1`, usa porta dinâmica e token por sessão.

Para ensaios que não devem disputar o foco com o usuário, inicie diretamente o EXE com `--data-dir <perfil-isolado> --hidden` e conecte o cliente a esse perfil. A janela e o serviço reais são usados; reprodução contínua permanece pausada quando a janela está oculta, mas cálculo, exportação e posicionamento da simulação por comandos funcionam normalmente. Feche o perfil ao terminar com `app.close`. O perfil padrão do usuário não aceita `--hidden`.

`app.show` mostra e restaura a janela através do host nativo, sem depender do laço de comandos JavaScript. Pode ser usado para retomar uma janela minimizada ou suspensa antes de consultar o estado ou a simulação.

## Posicionar a peça na vista 3D

A barra de ícones na própria visualização reúne Girar, Origem e Mover. `placement.panel` com `panel:"rotate"`, `"origin"`, `"move"` ou `null` abre ou recolhe os mesmos painéis visuais. Abrir um painel não altera a malha nem limpa regiões; a reprodução pausa e a peça fica visível em Percursos.

Use `placement.action` com `kind:"rotate",axis:"x",turns:1` para +90° em X, `kind:"flip"` para inverter a face em X, ou `kind:"reset"` para a orientação original. `origin_xy` recebe `anchor:[0,0]` para o canto mínimo, `[0.5,0.5]` para o centro, ou qualquer um dos nove pares de 0 / 0.5 / 1. `origin_z` recebe `anchor:"top"`, `"center"` ou `"bottom"`. `translate` recebe `delta_mm:[x,y,z]`, um deslocamento relativo em milímetros, inclusive quando o STL usa polegadas.

Uma mudança efetiva passa pela inspeção real do STL, ajusta as profundidades e limpa as regiões anteriores. `placement.undo` recupera a última posição, regiões e percurso anterior enquanto nenhuma outra configuração tiver sido alterada. Um deslocamento zero não invalida o percurso. `state` inclui `placement_ui`; com `detail:true`, informa também se os controles cabem na área 3D.

## Uso rápido no PowerShell

Na pasta deste executável:

```powershell
.\cam-command.ps1 -Action state
.\cam-command.ps1 -Json '{"action":"simulation.set","speed":3}'
.\cam-command.ps1 -Action state -Start
```

O script apenas inicia o próprio `.exe`, espera e mostra seu relatório JSON.
Para usar diretamente, sem o script:

```powershell
@{ action = 'state' } | ConvertTo-Json | Set-Content -LiteralPath pedido.json -Encoding UTF8
Start-Process -FilePath '.\CAM Local.exe' -ArgumentList '--command pedido.json --report resposta.json' -WindowStyle Hidden -Wait
Get-Content .\resposta.json -Raw
```

Também aceita `--command-json '{"action":"state"}'`. Use `--report` para escolher o
arquivo de resposta. Sem essa opção, ele fica em
`%LOCALAPPDATA%\CAMLocal\command-result.json`. Como o executável é gráfico,
utilize `Start-Process -Wait` ou o script para esperar a conclusão.

`--start` abre o app caso esteja fechado. `--data-dir CAM-perfil-teste` cria um
perfil separado, útil para ensaios sem mudar o projeto nem a biblioteca usuais.
`--port 8765` direciona os comandos a uma instância de desenvolvimento.
`schema` funciona mesmo com o aplicativo fechado e lista ações/campos válidos.

## Modo inteligente Rough + Cutout

O Rough deriva automaticamente o domínio do STL, incluindo as cavidades internas e respeitando concavidades. `machining.plan` fornece `automatic_regions` (domínio dos centros da fresa), `exterior_strategy` (distribuição entre Rough e Cutout e diagnóstico da geometria) e `preparation_contours`. A política `features_then_cutout` deixa os rebaixos, bolsões e formas 3D no Rough e o perfil completo em camadas no Cutout; `preparation_contours.not_required:true` indica que não foi acrescentado canal externo ao Rough. Não equivale a uma única passada de profundidade total. Rough sem geometria a remover pode ter zero movimentos. O mapa AUTO ciano usa a mesma camada `view.layers.regions`; `state.view.automatic_regions` informa sua visibilidade. `state` omite os vértices automáticos por padrão; `detail:true` os inclui.

Depois de `simulation.wait`, `{"action":"simulation.sample","points":[[44,44],[0,0]]}` lê até 64 posições XY da grade, sem mover a reprodução. Retorna a célula amostrada, seu centro, altura Z e profundidade removida. Pontos fora do bruto e resultados de uma geração/posição ainda pendente são rejeitados. Essa amostragem permite verificar por código se o retalho ficou intacto e se o canal de recorte atingiu a profundidade desejada.

Ative pelo mesmo estado da interface e confira o plano sem iniciar cálculo:

```json
[
  {"action":"config.patch","operations":{"machining_mode":"smart"}},
  {"action":"machining.plan"},
  {"action":"calculate.start"},
  {"action":"calculate.wait","timeout_s":900}
]
```

Campos persistidos em `operations`: `machining_mode` (`manual`/`smart`), `smart_stock_bottom_mm` (Z físico, `null` = fundo do STL), `smart_breakthrough_mm` (>= 0), `smart_skin_mm` (> 0 ou `null` = automático). Unidades em mm. Alterações exigem recálculo; `machining.plan` apenas confere a configuração. `state.smart_plan` e o resultado de cálculo mostram os valores derivados. O backend reconstrói o plano na exportação.

O modo inteligente fixa Rough + Cutout externo e a ordem Drill (se ativo) → Rough → Cutout. As regiões continuam exclusivas do Rough. A pele limita somente o exterior nas camadas profundas. Feedrates e RPM vêm do cadastro. Para voltar à ordenação livre: `{"action":"config.patch","operations":{"machining_mode":"manual"}}`.

## Formas do Rough e recuperação do Cutout

- `{"action":"regions.picker","kind":"keepin"}` abre os cinco ícones; `kind:keepout` troca o tipo. Repetir o mesmo tipo fecha a seleção.
- `{"action":"regions.draw","kind":"keepout","shape":"circle"}` escolhe a forma e inicia o mesmo desenho da interface. Formas: `rectangle`, `circle`, `ellipse`, `polygon`, `freehand`.
- `{"action":"regions.cancel"}` fecha as opções/cancela o desenho, sem criar ou excluir regiões.
- `state.regions_ui` contém o estado das opções e do desenho. `regions.add` continua disponível para adicionar geometria diretamente.
- `state.feedback.cutout_recovery` informa a sugestão de soltar a peça depois de erro de fresa nos contornos internos. `{"action":"cutout.recovery.apply"}` aplica apenas a sugestão atual, muda para contorno externo e exige novo cálculo. Não é executada automaticamente; sugestões antigas, cálculos ocupados e alterações durante a validação são rejeitados.

## Drill e três operações

`{"action":"drill.inspect"}` lê o STL e as opções atuais, sem criar cálculo nem alterar o projeto. Retorna furos detectados, diâmetro nominal/livre/usinado, profundidade, método, ajuste de facetas e motivo de incompatibilidade. `{"action":"operation.tab","tab":"drill"}` abre sua aba.

`operations.set` aceita qualquer permutação de `roughing`, `drill` e `cutout`, com ativação parcial em `enabled`. Os comandos legados de duas operações continuam aceitos e mantêm a posição do Drill. Exemplo:

```json
{"action":"operations.set","order":["drill","roughing","cutout"],"enabled":{"drill":true,"roughing":true,"cutout":true}}
```

Opções em `config.patch.operations`: `drill_enabled`, `drill_allow_helix`, `drill_center_cutting`, `drill_compensate_facets`, `drill_bottom_mm`, `drill_peck_mm`, `drill_tolerance_mm`, `drill_feed_mm_min`. A sequência completa fica em `operation_sequence`. Os dois toggles de hélice/compensação e a confirmação de corte central são falsos por padrão. A inspeção informa incompatibilidades; calcular com Drill ativo exige ao menos um furo elegível. Alterações invalidam o percurso, seguindo o fluxo normal `calculate.start/status/wait` e `nc.export`.

## Lotes

Um arquivo pode conter um comando, uma lista ou `{"commands":[...]}`. A execução é
sequencial e para no primeiro erro. Não é uma transação: os comandos anteriores
ao erro continuam aplicados. O relatório conserva esses resultados e informa
`current_index`, `current_action` e `error`. Código de saída: **0 sucesso, 1 erro**.

Exemplo, partindo do projeto já configurado:

```json
{
  "commands": [
    {"action":"state"},
    {"action":"calculate.start"},
    {"action":"calculate.wait","timeout_s":900},
    {"action":"nc.export","path":"C:/CAM/resultado.nc"},
    {"action":"simulation.set","mode":"stock","speed":3},
    {"action":"simulation.seek","fraction":1},
    {"action":"simulation.wait","surface":"solid","timeout_s":120},
    {"action":"project.save","path":"C:/CAM/projeto.zip"}
  ]
}
```

A pasta de destino deve existir. Arquivos existentes só são substituídos com
`"overwrite":true`. Caminhos relativos são resolvidos a partir da pasta de quem
executa o comando. Os arquivos são lidos/escritos pelo cliente local; o servidor
não oferece execução de shell nem JavaScript arbitrário.

## Ações

| Área | Ações |
| --- | --- |
| Estado | `ping`, `schema`, `state`, `diagnostics`, `command.result` |
| Arquivos | `stl.open`, `project.open`, `project.save`, `demo.open`, `nc.export` |
| Usinagem | `config.patch`, `placement.set`, `tools.list`, `tool.set`, `tool.save`, `operations.set` |
| Regiões do Rough | `regions.add`, `regions.remove`, `regions.clear`, `operation.tab` |
| Cálculo | `calculate.start`, `calculate.status`, `calculate.wait`, `calculate.cancel` |
| Visualização | `view.set`, `view.capture` |
| Simulador | `simulation.set`, `simulation.play`, `simulation.pause`, `simulation.seek`, `simulation.reset`, `simulation.wait` |
| Aplicativo | `app.close` |

`state` retorna limites e dimensões do STL, ferramenta, parâmetros, regiões,
identificadores/progresso do cálculo, câmera e simulador. Omite a malha e os
milhares de movimentos; `"detail":true` inclui os vértices das regiões.
`calculate.status` também retorna apenas o resumo do percurso.

### Parâmetros e ferramenta

```json
{"action":"config.patch",
 "settings":{"stepdown_mm":0.7,"stepover_mm":1.27,"bottom_mm":-17},
 "operations":{"roughing_enabled":true,"cutout_enabled":true,
   "order":"roughing_then_cutout","roughing_order":"region_first",
   "cutout_bottom_mm":-17.1,"cutout_contours":"external",
   "cutout_use_prior_roughing":true,
   "roughing_feed_mm_min":700,"cutout_feed_mm_min":900,
   "plunge_mm_min":150,"spindle_rpm":8000}}
```

Estes números são exemplos de formato. Comprimentos em **mm**, feeds em
**mm/min**, tempos em **segundos**, Z no sistema do modelo posicionado. O fundo
usa Z absoluto; `stepover_mm` usa milímetros. `schema` lista os demais campos.
A interface usa `region_mode=layer` e `compress_collinear=true`.

`tool.set` aceita `id` da biblioteca ou um objeto `tool` para alterar a ferramenta
do projeto. `tool.save` também grava na biblioteca; para substituir um ID use
`"replace":true`. `config.patch` aceita `tool`, `stock` e `notes` junto com os
parâmetros, validando tudo antes de aplicar. Passo lateral maior que a nova fresa
é rejeitado; altere ferramenta e passo no mesmo `config.patch` quando necessário.

### Lista de operações

`operations.set` controla a mesma lista arrastável da interface:

```json
{"action":"operations.set","order":["cutout","roughing"],"enabled":{"roughing":true,"cutout":true}}
```

`order` deve conter as duas operações uma vez cada; `enabled` aceita alteração
parcial. Uma operação desativada preserva sua posição e fica fora da execução.
`state.operation_list` retorna a ordem e as caixas atuais. Comandos existentes
em `config.patch.operations` atualizam a mesma lista. A lista aceita ambas
desativadas para edição, mas cálculo e salvamento exigem pelo menos uma operação ativa.
Uma alteração efetiva invalida o percurso; repetir o estado atual é uma operação
sem efeito. `project.save`/`project.open` preservam essa configuração.

### Keep In e Keep Out

As duas opções afetam apenas o Rough. Coordenadas no plano XY do modelo já
posicionado. O primeiro Keep In substitui o limite automático do bruto.

```json
{"action":"regions.add","kind":"keepin","shape":"rectangle","min":[0,0],"max":[84,84]}
{"action":"regions.add","kind":"keepout","shape":"circle","center":[42,42],"radius":8}
{"action":"regions.add","kind":"keepout","shape":"ellipse","center":[42,42],"radius_x":8,"radius_y":5}
{"action":"regions.add","kind":"keepin","shape":"polygon","points":[[0,0],[30,0],[30,20],[0,20]]}
{"action":"regions.add","kind":"keepout","shape":"freehand","points":[[5,5],[10,5],[10,10],[5,10],[5,5]]}
{"action":"regions.remove","kind":"keepout","index":0}
{"action":"regions.clear","kind":"all"}
```

Cada linha acima é um exemplo independente. Para executar juntas, coloque-as em
uma lista JSON. Regiões cruzadas/degeneradas são rejeitadas.

### Câmera e reprodução

`view.set`: `preset` = `iso`, `top` ou `front`; `zoom`; ou `position`/`target`
com três coordenadas. `depth_coloring:true` liga cores pela profundidade do STL e
contornos dos degraus; `false` volta à cor uniforme. O estado aparece em `state.view`, junto dos limites Z em `depth_scale`. A legenda
mostra profundidade abaixo do topo do modelo. É uma alteração visual: não exige
recálculo. `view.capture` salva somente a imagem do visualizador em
PNG no `path` solicitado, sem capturar a tela do computador.

`simulation.set`: `mode` = `paths` ou `stock`; `speed` = 1 para o feedrate real,
2 para 2×, 3 para 3×; `layers` aceita `model`, `paths`, `rapids`, `regions`.
`simulation.seek` aceita `time_s` ou `fraction` de 0 a 1. Para consultar a remoção
concluída, use `simulation.wait` com `surface:grid` ou `surface:solid`. A reprodução
pausa se a janela for ocultada/minimizada, como no uso manual. Seek e reconstrução
podem ser comandados diretamente, sem aguardar a reprodução.

## Erros, espera e recuperação

Alterações de usinagem invalidam os percursos. Abrir um STL ou alterar seu
posicionamento redefine profundidades/regiões para o modelo novo. ZIP importado
precisa ser recalculado. Durante cálculo/exportação, alterações por comando são
recusadas: consulte o progresso ou cancele antes de editar.

O prazo padrão para receber/executar um comando de interface é 30 s; pode usar
`timeout_s` até 300 s (por exemplo, na exportação). Um comando ainda na fila
expira sem executar. Se ele **já começou**, o prazo do cliente não desfaz a ação.
O erro informa `command_id`; consulte
`{"action":"command.result","command_id":"..."}` antes de repetir. Não existe
reexecução automática de comandos. `calculate.wait` tem prazo próprio e não
cancela o cálculo ao expirar; `calculate.cancel` faz o cancelamento explícito.

O aplicativo inicia vazio, sem importar um modelo automaticamente. `demo.open`
abre uma placa com bolsão gerada pelo código, somente quando solicitado.
`state.workspace` informa a tela vazia e a disponibilidade de salvar/calcular.

Ensaio nativo reproduzível: `.venv/Scripts/python.exe scripts/check_native.py
--exe "dist/CAM-local-Windows/CAM Local.exe"`. O teste usa perfil isolado,
importação opcional, cálculo real, exportação, remoção na grade, ZIP e reinício.

## Presets de usinagem

Os últimos ajustes são gravados automaticamente no perfil local e restaurados ao reabrir, sem carregar uma peça. Presets nomeados ficam separados dos últimos ajustes: editar um campo não substitui o preset salvo.

```json
{"action":"presets.list"}
{"action":"presets.save","name":"MDF · fresa 3,175 mm"}
{"action":"presets.apply","id":"ID retornado"}
{"action":"presets.save","id":"ID retornado","name":"MDF atualizado"}
{"action":"presets.delete","id":"ID retornado"}
{"action":"presets.remember"}
```

O preset inclui o snapshot da ferramenta, feedrates de Rough/Cutout/Drill, plunge, rápido, RPM, stepdown, stepover em porcentagem, rampa e opções das operações. A confirmação de corte pelo centro é salva junto da ferramenta e é desmarcada ao trocar de ferramenta. Ao aplicar em um projeto, o posicionamento, as regiões, os limites do bruto e as profundidades finais da peça são preservados.

O arquivo `machining-presets.json` fica ao lado de `ferramentas.json` no perfil (`%LOCALAPPDATA%/CAMLocal` por padrão). Perfis de teste isolados usam seus próprios presets. Atualizações de versões antigas recuperam os ajustes do projeto local mais recente, sem abrir seu STL.

## Zero da peça na borda e segunda face

O zero G54 é a referência das coordenadas do projeto. Selecionar uma borda apenas preenche a referência; aplicar `origin_point` muda o zero. XY e Z podem mudar separadamente. O sistema desloca também polígonos Keep In/Out, limites do bruto, fase do raster, alturas de obstáculos e profundidades absolutas, mantendo a configuração física. Os percursos são invalidados e precisam de novo cálculo; desfazer recupera a configuração anterior.

```json
{"action":"placement.outline"}
{"action":"placement.pick","enabled":true}
{"action":"placement.pick","enabled":false}
{"action":"placement.reference","point_mm":[20.3,7],"snap":true}
{"action":"placement.action","kind":"origin_point","point_mm":[20,7,0],"axes":"xy"}
{"action":"placement.action","kind":"origin_point","point_mm":[0,0,2],"axes":"z"}
{"action":"placement.second_side","axis":"x","fixture":{"diameter_mm":20,"height_mm":3}}
```

`placement.outline` devolve os contornos externos projetados do STL já posicionado. `placement.reference` aproxima o par XY à borda por projeção no segmento; `snap:false` aceita o ponto informado diretamente. `placement.pick` mostra a vista de topo e realça o contorno para selecionar com o mouse. Os nove pontos da caixa e as referências Topo/Meio/Base continuam disponíveis.

`placement.second_side` é explícito e exige as dimensões da fixação: `diameter_mm` é o diâmetro do círculo a proteger no centro da caixa da peça; `height_mm` é a altura da fixação acima do topo da peça após virar. O eixo de giro pode ser `x` ou `y`, sempre 180°. A operação muda para Manual, ativa só Rough, usa `domain_mode:silhouette`, remove as regiões da primeira face e cria o Keep Out central circunscrito. A travessia passa acima do topo declarado da fixação mais a folga configurada. Escolha a referência da segunda face depois do giro; a alteração do zero preserva essa nova fixação.

A seleção do zero não comanda homing nem altera offsets no controlador: o NC contém G54 e usa as coordenadas do projeto. A referência física correspondente deve ser definida na CNC. A simulação não importa o bruto restante da primeira face.
