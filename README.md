# CAM Local

CAM para Windows com janela própria: importe um STL, prepare desbaste, furação e recorte, simule a remoção de material e exporte NC para GRBL.

O aplicativo começa com a área de trabalho vazia. **Abrir STL** importa uma peça; **Abrir projeto** continua um arquivo ZIP salvo. **Exemplo simples** abre, somente quando solicitado, uma placa com bolsão gerada pelo próprio aplicativo.

## Funcionalidades

- Desbaste por regiões, com Keep In / Keep Out e desenhos de retângulo, círculo, elipse, polígono ou mão livre.
- Modo inteligente: Rough nas formas 3D, rebaixos e bolsões; recortes internos vantajosos preservam o miolo como sobra, antes do perfil externo.
- Posicionamento na própria vista 3D: ícones para girar, origem XY em nove pontos, origem Z, deslocamento em mm e desfazer posição.
- Drill com comparação entre fresa e furo; hélice opcional para furos maiores.
- Lista de operações com ativação e ordenação no modo manual.
- Rampas, ligações em áreas removidas e validação independente antes da exportação.
- Simulação de remoção em grade e reconstrução de superfície, com reprodução pelo feedrate e velocidades 2×, 3× e outras.
- Controle da aplicação por comandos JSON, sem automação de mouse.
- Presets nomeados de ferramenta, avanços, plunge, RPM e ajustes de corte; últimos valores restaurados automaticamente ao reabrir, com a área de trabalho vazia.

## Rodar pelo código

Ambiente testado: **Windows x64, Python 3.12, Node.js 24 e WebView2**. Os scripts usam PowerShell e não exigem ativar o ambiente virtual.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
```

Para gerar o executável:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

O resultado fica em `dist/CAM-local-Windows/`. Dependências são instaladas pelo `setup.ps1`; `node_modules`, ambientes virtuais, modelos pessoais e arquivos NC não fazem parte do repositório.

## Usar

1. Abra um STL e use **Girar**, **Origem** e **Mover** na vista 3D. As opções completas de unidade continuam disponíveis no painel Mover.
2. Confira diâmetro, comprimento de corte, avanços e RPM da ferramenta. Em **Presets de usinagem**, escolha um preset ou use **＋ Salvar** para cadastrar seus ajustes. **Atualizar preset** substitui o selecionado; as edições comuns ficam nos últimos ajustes automáticos.
3. Escolha as operações. No modo inteligente, os detalhes ficam no Rough; internos vantajosos são recortados antes de soltar o exterior.
4. Calcule e simule os percursos; depois exporte o NC.

O motor é experimental, aceita fresa de topo reto e não se conecta à CNC. A simulação não verifica haste, porta-ferramenta ou fixação. O Cutout segue a silhueta projetada, sem acabamento 3D de superfícies inferiores. Tempos são estimativas por velocidade constante. Consulte [limitações e geometria](docs/ARQUITETURA.md).

## Desenvolvimento

```powershell
.venv/Scripts/python.exe scripts/test.py
```

- `work/roughing/`: motor geométrico, operações, pós-processador e testes.
- `work/cam-ui/`: servidor local, janela nativa, controles e visualizador.
- `work/ui-runtime/` e `work/geometry-runtime/`: manifests e locks das dependências JavaScript.
- `scripts/`: instalação, testes e build reproduzível.

Veja [como contribuir](CONTRIBUTING.md), [comandos](docs/COMANDOS.md) e [publicação no GitHub](docs/UPLOAD.md).

## Licença

O código original do CAM Local está sob [MIT](LICENSE). Bibliotecas mantêm suas próprias licenças; versões e referências constam em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
