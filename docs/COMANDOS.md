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

O modelo padrão de tempo é `operations.timing_model="acceleration"`. Em **Tempo e perfil da máquina**, informe `machine_max_rate_mm_min:[X,Y,Z]` (valores $110–$112), `machine_acceleration_mm_s2:[X,Y,Z]` ($120–$122), `machine_steps_per_mm:[X,Y,Z]` ($100–$102), `machine_junction_deviation_mm` ($11) e `machine_planner_blocks` (blocos úteis). Os padrões são [1500,1500,1500], [10,10,10], [400,400,400], 0,01 e 15. As fases de aceleração/frenagem e os cantos entram no tempo e na reprodução 1×. O resultado inclui totais por operação e perfis por movimento; `state.timing_ui` mostra o modo e os controles disponíveis. O campo antigo `rapid_mm_min` só altera o modelo `"constant"`; com aceleração, G0 usa os máximos por eixo. Editar o perfil exige recálculo e não modifica o G-code, os avanços, a geometria nem a configuração do GRBL. Pode ser salvo em presets e projetos.

Transferência real para a controladora: `controller.ports` lista portas sem abri-las. `controller.read {port:"COM3",baudrate:115200}` consulta o estado e `$$`, mostra a leitura sem substituir a estimativa e fornece `read_id`. `controller.apply` grava os seis máximos/acelerações da tela; aceita `values:{machine_max_rate_mm_min:[...],machine_acceleration_mm_s2:[...]}` para um alvo explícito. Porta, baudrate e read_id podem ser omitidos após a leitura na mesma sessão. O GRBL precisa estar Idle; os valores anteriores são salvos em `%LOCALAPPDATA%/CAMLocal/grbl-backups` antes da escrita. A resposta registra verificação, alterações parciais e caminho do backup. Não há repetição automática após erro ou timeout. `controller.import` copia a leitura para a estimativa sem escrever na máquina; `state.controller` apresenta conexão, leitura e último resultado. A porta precisa estar livre no CNCjs e é liberada ao final. Esses comandos também funcionam sem um STL aberto. A conexão pode reiniciar certas placas USB; o aplicativo não envia reset, unlock, movimentos ou comandos do spindle.

Para manter o CNCjs conectado, use o painel separado em `work/cncjs-widget/`, empacotado por `scripts/package_cncjs_widget.py`. Ele roda dentro do CNCjs e usa sua própria API autenticada, sem chamar os comandos `controller.*` de conexão USB do EXE. A leitura e a gravação são ações explícitas do painel, com proteção contra trabalho/filas ativos, backup local no navegador e releitura. A ativação por `install.html` acrescenta somente o widget ao layout daquele navegador. [Instalação e funcionamento](../work/cncjs-widget/README.md).

Exemplo: `{"action":"config.patch","operations":{"timing_model":"acceleration","machine_acceleration_mm_s2":[10,10,10],"machine_max_rate_mm_min":[1500,1500,1500]}}`. Depois execute `calculate.start` e `calculate.wait`. A estimativa continua aproximada: não inclui atrasos de transmissão USB, espera do spindle ou pausas manuais, e assume origem alinhada aos passos. Os 15 blocos úteis correspondem ao buffer de 16 posições com uma reservada, coerente com o estado `Bf:15` informado.

`operations.cutout_smoothing_mm` controla a fluidez do Cutout, entre 0 e 0,1 mm. O padrão 0 conserva as facetas do projeto; 0,01 mm reduz microsegmentos por uma aproximação conservadora que pode deixar essa pequena sobra. A região protegida original precisa estar contida na nova, a nova precisa caber no limite de desvio, e os contornos devem preservar identidade e topologia. Se alguma prova falhar, usa o contorno original. O controle “Fluidez do contorno” fica na aba Cutout e acompanha presets/projetos. A exportação recompõe as mesmas provas a partir do STL e relê o NC. O pós elimina palavras modais repetidas (XYZ/F/G0/G1), mantendo cada movimento e sua precisão.

`config.patch` aceita `settings.strategy="hybrid"` para o **3D eficiente**, padrão em novas importações sem preferências salvas. Reconhece pisos horizontais do STL, redistribui camadas sem exceder o Stepdown, agrupa o contato em faixas elevadas por até `surface_error_mm` (padrão 0,15 mm) e simplifica contornos dentro da área permitida por até `path_tolerance_mm` (0,02 mm). O contato OpenCAMLib é reamostrado depois da simplificação. A sobra adicional em Z soma-se ao sobremetal axial e é relativa ao envelope conservador de contato, não uma garantia de sobra em cantos inacessíveis à fresa. Passadas raster só são omitidas quando o volume varrido já foi comprovadamente removido por passadas anteriores. Os dois ajustes ficam nos presets e em “Precisão do 3D eficiente” na aba Rough. Projetos antigos mantêm sua estratégia até uma alteração explícita.

`settings.optimize_entries` (padrão `true`) permite ao 3D eficiente comparar a rampa com uma entrada vertical pelos avanços reais configurados. A entrada vertical só é escolhida se for mais rápida que o menor comprimento possível de rampa, a ferramenta estiver confirmada como cortante pelo centro no inteligente e a profundidade no material não exceder um Stepdown comprovado. Sem confirmação, mantém rampas. Desmarcar “Escolher a entrada mais rápida” conserva a política anterior de rampas, incluindo o recurso a mergulho confirmado quando a rampa não cabe. A exportação confere os avanços usados na decisão; o pós usa o Plunge rate configurado.

Eficiência: `config.patch` aceita `settings.strategy="planar"` para Rough bruto em alturas constantes e `"conformal"` para acompanhar a superfície. Aproximações verticais do Rough/Cutout percorrem em G0 a coluna já comprovadamente livre e mantêm a entrada final com avanço. Drill oferece `operations.drill_retract_mode` (`"full"` ou `"chip_break"`), `drill_retract_mm`, `drill_rapid_reentry` e `drill_reentry_gap_mm`. O modo completo continua retirando cavacos a cada mergulho; o curto sobe somente a distância configurada, mas sai à altura segura antes de mudar de furo. O rápido de retorno só percorre o cilindro já furado, parando antes do fundo anterior. Opções ficam salvas nos presets. `rapid_mm_min` ajusta apenas a estimativa; a máquina controla os G0 pelos seus próprios limites.

`cutout.depth` recebe `depth_mm` como profundidade total positiva do recorte, medida a partir do topo do bruto. Exemplo: `{"action":"cutout.depth","depth_mm":17.3}`. No inteligente, converte o total em corte extra abaixo do fundo declarado do bruto (ou fundo do STL quando automático), mantendo o limite do Rough. O comprimento de corte da fresa continua sendo validado. `state.depth_ui` informa os valores exibidos e se o campo está habilitado.

Para uma peça já recortada, selecione **Manual → Cutout → Contornos do Cutout → Somente internos · peça já recortada**. O percurso usa apenas os contornos internos passantes da silhueta, com compensação do raio da fresa, rampas e camadas; não acrescenta o perfil externo. Rebaixos com fundo continuam sendo trabalho do Rough. Sem internos ou se a fresa não couber em algum deles, o cálculo informa o problema, sem trocar para recorte externo. Rough e Drill continuam com sua ativação independente; desative-os para executar somente o recorte interno. A opção acompanha projetos e presets. `state.cutout_ui` mostra seleção, disponibilidade e orientação da tela.

Exemplo por comando, sem mudar a posição nem as profundidades atuais:

```json
{"action":"config.patch","operations":{"machining_mode":"manual","roughing_enabled":false,"drill_enabled":false,"cutout_enabled":true,"cutout_contours":"internal"}}
```

Depois execute `calculate.start`, `calculate.wait` e `nc.export`. `external` mantém somente o exterior; `all` faz internos + exterior. O modo inteligente continua destinado a Rough + recorte para soltar a peça inteira.

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

Marque **Peça já solta · usinar somente o interior** para trabalhar uma peça que já foi recortada. O Rough usa um envelope interno com o raio da fresa contido no contorno externo, segue rebaixos e bolsões e respeita os Keep In / Keep Out existentes. Não cria canal externo nem pele de retenção. A orientação, o zero e a fixação não são alterados. O plano pode escolher recortes internos passantes vantajosos; eles também precisam caber nos limites e evitar a fixação. Sem internos selecionados, não há operação Cutout no resultado. Uma operação Drill que atravesse a área protegida é rejeitada antes do Rough.

```json
{"action":"config.patch","operations":{"machining_mode":"smart","smart_part_released":true}}
```

Confira com `machining.plan`, depois `calculate.start` e `calculate.wait`. `part_released:true`, `exterior_strategy.mode:"interior_only"`, `release_contours:"none"` ou `"automatic_internal_only"` e `sequence` mostram a decisão real. `state.smart_ui` apresenta o checkbox e sua orientação na tela. Projetos e presets guardam `smart_part_released`; o padrão `false` conserva o plano para desbastar e soltar do bruto. **Preparar fixação** marca a condição de peça já solta para a próxima ativação do modo inteligente, mantendo a orientação atual por padrão.

Nesse modo, as travessias também contornam os Keep Out em XY, mesmo acima da altura declarada da fixação. O desvio considera o raio da fresa e confere os pontos arredondados para o NC; a exportação refaz essa validação. `fixture_travel` no plano descreve a política e `fixture_detour_moves` no resumo de cada operação conta os trechos desviados. Um ponto de travessia dentro da própria fixação é rejeitado; não há retorno silencioso a uma travessia reta bloqueada.

Em **Camadas simples**, rebaixos anulares podem usar contornos fechados em vez de centenas de segmentos raster. A substituição exige menor comprimento de corte e menos entradas, contornos dentro da área permitida e prova de cobertura por varreduras conservadoras da ferramenta. A sobra XY adicional fica limitada pelo desvio de percurso configurado, até 1% do diâmetro. Tolerância insuficiente, geometria incompatível ou contornos fragmentados pela avaliação de contato mantêm o método anterior. O Rough continua usinando o rebaixo; feeds, Stepdown, zero e Keep Out são preservados. `annular_pocket_layers` informa quantas camadas utilizaram essa estratégia.

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
concluída, use `simulation.wait` com `surface:grid` ou `surface:solid`. `surface:final`
espera somente a superfície final preparada em segundo plano, sem avançar a barra
nem trocar a vista. `state.simulation.solid_precompute` informa estado/progresso;
`solid_cache` informa construções, acertos e memória do cache. `solid_volume_mm3`
é o volume restante da superfície sólida da posição atual, quando disponível.
O resultado final e posições já visitadas são reaproveitados ao voltar na barra;
posições novas ainda podem exigir uma primeira reconstrução. A reprodução
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

Os últimos ajustes são gravados automaticamente no perfil local e restaurados ao reabrir, sem carregar uma peça. As edições de usinagem, incluindo aceleração XYZ, atualizam automaticamente o preset selecionado. Sem preset selecionado, ficam apenas nos últimos ajustes. Abrir um projeto ou exemplo não sobrescreve o preset: é preciso editar os ajustes. Antes de trocar de preset, edições pendentes são salvas no anterior.

```json
{"action":"presets.list"}
{"action":"presets.save","name":"MDF · fresa 3,175 mm"}
{"action":"presets.apply","id":"ID retornado"}
{"action":"presets.save","id":"ID retornado","name":"MDF atualizado"}
{"action":"presets.delete","id":"ID retornado"}
{"action":"presets.remember"}
```

O preset inclui o snapshot da ferramenta, feedrates de Rough/Cutout/Drill, plunge, rápido, RPM, stepdown, stepover em porcentagem, rampa, perfil de tempo (máximos, acelerações XYZ, passos/mm e junções) e opções das operações. A confirmação de corte pelo centro é salva junto da ferramenta e é desmarcada ao trocar de ferramenta. Ao aplicar em um projeto, o posicionamento, as regiões, os limites do bruto e as profundidades finais da peça são preservados.

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
{"action":"placement.second_side","fixture":{"diameter_mm":20,"height_mm":3}}
```

`placement.outline` devolve os contornos externos projetados do STL já posicionado. `placement.reference` aproxima o par XY à borda por projeção no segmento; `snap:false` aceita o ponto informado diretamente. `placement.pick` mostra a vista de topo e realça o contorno para selecionar com o mouse. Os nove pontos da caixa e as referências Topo/Meio/Base continuam disponíveis.

`placement.second_side` exige as dimensões da fixação: `diameter_mm` é o diâmetro do círculo a proteger no centro da caixa da peça; `height_mm` é a altura da fixação acima do topo do bruto. O padrão `axis:"current"` mantém a orientação, o zero, as profundidades, o bruto e os limites Keep In atuais, inclusive se a peça já foi invertida em X/Y. Preparar novamente não vira a peça. A operação substitui os Keep Out pelo círculo central circunscrito. Fora de Inteligente + peça já solta, muda para Manual e ativa só Rough em `domain_mode:silhouette`. Percursos anteriores são invalidados; Desfazer posição recupera o estado anterior.

Somente `axis:"x"` ou `axis:"y"` aplica um giro adicional de 180°, com reajuste de profundidades e regiões para a nova face. Na interface, **Preparar fixação** usa **Manter orientação atual** por padrão; depois de um giro explícito, a seleção volta a esse padrão para evitar uma segunda inversão acidental. Se Inteligente e Peça já solta já estão ativos, preparar a fixação mantém esse modo; nos demais casos, prepara Rough manual na silhueta. `state.placement_ui.second_side` mostra a seleção e os campos da fixação. A travessia passa acima do topo declarado da fixação mais a folga configurada. Confira a referência da segunda face; mudar o zero preserva essa nova fixação.

A seleção do zero não comanda homing nem altera offsets no controlador: o NC contém G54 e usa as coordenadas do projeto. A referência física correspondente deve ser definida na CNC. A simulação não importa o bruto restante da primeira face.

## Referências XY automáticas

```json
{"action":"placement.zero","anchor":"left"}
{"action":"placement.zero","anchor":"right"}
{"action":"placement.zero","anchor":"front"}
{"action":"placement.zero","anchor":"back"}
{"action":"placement.zero","anchor":"center"}
{"action":"placement.reference","point_mm":[84.1,42.1],"snap":true,"magnet_mm":1}
```

`placement.zero` aplica a referência em um passo, sem ponto de mouse ou confirmação adicional: `left` = X mínimo/Y central, `right` = X máximo/Y central, `front` = X central/Y mínimo, `back` = X central/Y máximo, `center` = ambos centrais. As coordenadas vêm dos limites do STL já posicionado; em peças irregulares a interseção desses planos pode ficar fora da superfície. Z, regiões, bruto, alturas e profundidades físicas são preservados. Repetir a referência ativa não invalida um percurso já calculado. A referência é compatível com desfazer e salva no posicionamento do projeto.

`placement.reference` continua apenas preenchendo o ponto personalizado. Com `magnet_mm > 0`, ele atrai aos pontos laterais alinhados que pertençam ao contorno externo real. O padrão é zero. Na seleção com o mouse, a atração usa 14 pixels da vista; Alt desativa a atração. Centro e pontos da caixa fora do contorno nunca atraem a seleção de borda.

`state detail:true` inclui `placement_ui.reference.automatic_points`; `automatic_anchor` identifica a referência ativa. As linhas tracejadas na vista mostram os eixos centrais. O painel principal prioriza os cinco botões; caixa/cantos e seleção manual ficam em opções recolhidas.

Editor de ferramenta: tool.editor com mode:open abre o formulário real, mode:set preenche values com os nomes dos campos da ferramenta, mode:state retorna textos e validade nativa, mode:save valida e grava pela mesma função do botão, e mode:close fecha sem salvar. Exemplo: {"action":"tool.editor","mode":"set","values":{"cutting_length_mm":"22"}}. Uma string vazia apaga o campo; valores ainda inválidos permanecem como rascunho e não alteram a biblioteca. Campos numéricos contínuos aceitam decimais sem exigir múltiplos de um incremento; os limites e os campos inteiros continuam sendo validados.

Simulação GPU: state.simulation.gpu informa backend, placa/driver expostos pelo WebGL, resolução, fundo físico, memória e target. simulation.wait aceita surface:gpu sem esperar a grade CPU. simulation.sample aceita surface:gpu para ler até 64 células; o padrão continua grid. O campo center_mm identifica a amostra exata. simulation.benchmark aceita fractions e repeats (até 32 quadros): completed_ms inclui desenho e uma sincronização gl.finish explícita; last_seek_ms mede apenas a submissão dos comandos. O benchmark restaura a vista e a posição. Nenhuma sincronização ou leitura integral da GPU ocorre na reprodução normal.

Ligações baixas: na prioridade region_first, o Rough tenta desvios curtos por cortes já concluídos quando a reta de ligação não tem prova de folga. O resumo de cálculo em motion_summary.operations.roughing informa stay_down_entries e routed_stay_down_entries; o segundo conta as ligações que precisaram de desvio. Não reduz o clearance configurado nem usa o simulador para autorizar o corte.

Giro de 45 graus: placement.action aceita {"kind":"rotate","axis":"x","angle_deg":45} (ou y, valor -45 para o sentido inverso). Os botões ±45° ficam no painel Girar da vista 3D para X/Y. turns continua sendo um inteiro de quartos de volta, compatível com os botões de 90°. Não combine turns e angle_deg. A inspeção do STL, o ajuste das referências e o desfazer são os mesmos dos giros anteriores.

Para girar a peça plana como um ponteiro de relógio, use placement.action kind:rotate, axis:z, angle_deg:45 ou -45. Esse giro conserva o centro e os limites Z, sem reposicionar a caixa para o canto mínimo. X/Y inclinam a peça.
