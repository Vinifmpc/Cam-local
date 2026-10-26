CAM Local para Windows x64, com janela própria e exportação NC para GRBL.

- Início com área de trabalho vazia; exemplo opcional de placa com bolsão gerado pelo aplicativo.
- Rough por regiões e formas 3D, Cutout do perfil externo em camadas e Drill com hélice opcional.
- Keep In / Keep Out com cinco formas de desenho.
- Simulação pelo feedrate, remoção em grade e reconstrução de superfície.
- Controle por comandos JSON e projeto ZIP.

O pacote é gerado a partir do código desta versão, após os testes do motor e da interface. A soma SHA256 está no arquivo anexado. Extraia o ZIP e execute **CAM Local.exe**; o WebView2 deve estar instalado no Windows.

O motor é experimental e não se conecta à CNC. Não simula haste, porta-ferramenta ou fixação; confira ferramenta, origem, parâmetros e percursos antes do uso em máquina. O código original é MIT, e as bibliotecas mantêm suas próprias licenças, incluídas no pacote.
