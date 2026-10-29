CAM Local para Windows x64, com janela própria e exportação NC para GRBL.

- Inteligente para peça já solta: Rough interno e recortes internos vantajosos, sem canal externo ou pele de retenção; preserva zero e orientação.
- Travessias contornam os Keep Out em XY com o raio da fresa e validação do arredondamento NC, inclusive no Drill.
- Rebaixos anulares em camadas simples podem usar percursos fechados, com prova de cobertura e retorno ao método anterior quando necessário.
- Cutout manual com seleção somente dos contornos internos.
- Preparar fixação mantém a orientação atual por padrão; giro adicional é explícito. Giro de ±45° em Z mantém a peça plana e gira pelo próprio centro.
- Material da remoção 2,5D mais claro, com sombras suavizadas.


- Estimativa e reprodução com aceleração, limites por eixo, frenagem nas mudanças de direção e antecipação do planejador. Perfil de máquina configurável em projetos/presets, sem alterar o controlador ou o NC; modelo constante legado disponível.
- Cutout com redução opcional de microsegmentos por aproximação conservadora dentro de tolerância; proteção da peça e topologia comprovadas, com retorno ao traçado original quando a simplificação não é válida. NC modal compacto reduz tráfego sem eliminar precisão.
- Rough 3D eficiente: pisos reconhecidos no STL, camadas redistribuídas dentro do Stepdown, sobra adicional em Z configurável e simplificação de contornos com novo cálculo de contato. Estratégia e precisão ficam nos presets; modos anteriores continuam disponíveis.
- Rough reduz retrações Z usando ligações curtas por corredores já cortados, inclusive recuos pequenos para dentro dos rasters e desvios ao redor de concavidades. Cada trecho mantém prova de folga, domínio e arredondamento NC; geometria e avanços permanecem os configurados.
- Camadas simples também escolhem a entrada mais rápida quando habilitada, mantendo os cortes em Z constante. Contornos de Rough usam simplificação dentro das áreas permitidas. Cópias auxiliares omitem trechos cujo volume já foi comprovadamente removido, com novas entradas verificadas e preservação das proteções.
- Zero XY automático em um clique: Esquerda, Direita, Frente, Trás e Centro. Referências pelos extremos do STL, linhas centrais na vista 3D e atração aos pontos alinhados na seleção manual; Alt permite seleção livre.
- Zero de trabalho na borda, com seleção visual do contorno e coordenadas manuais para XY/Z independentes. Regiões, bruto e profundidades acompanham a nova referência.
- A fase das passadas inclinadas acompanha a mudança do zero no sistema de coordenadas do raster, preservando o traçado físico.
- Preparo da segunda face: giro em X/Y, Rough na silhueta, Cutout desativado e área central protegida conforme diâmetro/altura informados para a fixação.
- Edições de usinagem agora são salvas automaticamente no preset selecionado, incluindo aceleração XYZ. Trocar de preset conclui o salvamento pendente; sem seleção, os últimos ajustes continuam sendo lembrados.
- Campos numéricos contínuos aceitam valores válidos ao apagar e redigitar, sem a restrição incorreta de incrementos. Contagens inteiras e limites continuam validados. Editor de ferramenta também disponível por comandos para testar o formulário real.
- Presets persistentes de ferramenta e usinagem, com restauração automática dos últimos avanços, plunge, RPM e passadas. Profundidades e regiões permanecem específicas de cada peça.
- Rough inteligente aproveita contornos de limpeza para entrar em passadas muito curtas, com prova do contato da fresa e validação independente, sem habilitar mergulho central automaticamente.
- Posicionamento integrado à vista 3D, com ícones de giro, nove pontos de origem XY, origem Z, deslocamento em mm e desfazer com recuperação das regiões e do percurso anterior.
- Modo inteligente reconhece miolos passantes vantajosos: Rough nos detalhes, recortes internos completos e liberação externa por último.
- Cálculo de áreas removidas otimizado, gravação compacta e paralelismo automático de até oito processos conforme o trabalho.
- Início com área de trabalho vazia; exemplo opcional de placa com bolsão gerado pelo aplicativo.
- Keep In / Keep Out com cinco formas de desenho.
- Remoção visual 2,5D na GPU WebGL2 com sweeps instanciados, textura de profundidade, raycast de paredes e furos passantes. Navegação e rewind sem reconstrução booleana por posição; grade CPU separada para os diagnósticos, com fallback quando necessário.
- Superfície final preparada em segundo plano após o cálculo. Cache limitado guarda o resultado final e posições já reconstruídas; reproduzir, pausar e voltar na barra não descartam mais esse trabalho. Novas posições continuam respeitando apenas o material removido até aquele instante.
- Controle por comandos JSON, inclusive posicionamento visual, retomada da janela e ensaios isolados com janela oculta; projeto ZIP.

O pacote é gerado a partir do código desta versão, após os testes do motor e da interface. A soma SHA256 está no arquivo anexado. Extraia o ZIP e execute **CAM Local.exe**; o WebView2 deve estar instalado no Windows.

O motor é experimental. A conexão GRBL permite somente leitura e gravação explícita do perfil de máximos/acelerações XYZ, com backup e releitura; não envia percursos. Não simula haste, porta-ferramenta ou fixação; confira ferramenta, origem, parâmetros e percursos antes do uso em máquina. O código original é MIT, e as bibliotecas mantêm suas próprias licenças, incluídas no pacote.

