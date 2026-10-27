CAM Local para Windows x64, com janela própria e exportação NC para GRBL.

- Presets persistentes de ferramenta e usinagem, com restauração automática dos últimos avanços, plunge, RPM e passadas. Profundidades e regiões permanecem específicas de cada peça.
- Rough inteligente aproveita contornos de limpeza para entrar em passadas muito curtas, com prova do contato da fresa e validação independente, sem habilitar mergulho central automaticamente.
- Posicionamento integrado à vista 3D, com ícones de giro, nove pontos de origem XY, origem Z, deslocamento em mm e desfazer com recuperação das regiões e do percurso anterior.
- Modo inteligente reconhece miolos passantes vantajosos: Rough nos detalhes, recortes internos completos e liberação externa por último.
- Cálculo de áreas removidas otimizado, gravação compacta e paralelismo automático de até oito processos conforme o trabalho.
- Início com área de trabalho vazia; exemplo opcional de placa com bolsão gerado pelo aplicativo.
- Keep In / Keep Out com cinco formas de desenho.
- Simulação pelo feedrate, remoção em grade e reconstrução de superfície.
- Controle por comandos JSON, inclusive posicionamento visual, retomada da janela e ensaios isolados com janela oculta; projeto ZIP.

O pacote é gerado a partir do código desta versão, após os testes do motor e da interface. A soma SHA256 está no arquivo anexado. Extraia o ZIP e execute **CAM Local.exe**; o WebView2 deve estar instalado no Windows.

O motor é experimental e não se conecta à CNC. Não simula haste, porta-ferramenta ou fixação; confira ferramenta, origem, parâmetros e percursos antes do uso em máquina. O código original é MIT, e as bibliotecas mantêm suas próprias licenças, incluídas no pacote.
