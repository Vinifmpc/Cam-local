# Arquitetura e limites

A janela nativa usa pywebview / WebView2. Um servidor HTTP restrito ao loopback serve a interface, Three.js e os workers de simulação. Escritas e comandos exigem um token efêmero; a descoberta do runtime fica no diretório de dados do usuário.

O STL é lido, convertido para milímetros e posicionado antes de calcular. Clipper2, através de pyclipr, executa as operações de polígonos. O contato da ponta plana com a malha usa OpenCAMLib, chamado em processo Node.js separado. Sombras por altura protegem a geometria 3D.

No modo inteligente, a projeção externa preenchida define o envelope de planejamento do Rough. O gerador desconta a peça protegida em cada altura, incluindo formas abertas à borda. Aberturas na projeção completa do STL são avaliadas como recortes internos: quando há um miolo compatível com a fresa e o custo estimado compensa, o Rough preserva essa sobra e o Cutout conclui o interno antes do exterior. Bolsões com fundo, ilhas de material, malhas abertas, sobremetal solicitado e miolos pequenos continuam na estratégia de Rough. Paredes variáveis mantêm o Rough 3D fora da região delegada. Keep In e Keep Out limitam somente o Rough. Camadas do Cutout só são omitidas quando cortes já concluídos comprovam remoção integral.

Recortar um miolo não equivale a desbastá-lo: a simulação conserva essa sobra no lugar, separada pelo canal cortado. Seu apoio e sua remoção física continuam sendo necessários. A exportação recalcula a seleção dos internos e confere cada contorno e as passadas originais, rejeitando miolos omitidos ou provas alteradas.

O cálculo roda em processo separado, com progresso e cancelamento. A validação reconstrói as entradas, profundidades e ligações; a exportação relê o NC arredondado. O pós-processador usa movimentos lineares, milímetros, coordenadas absolutas e G54.

## Desempenho do cálculo

As regiões por camada e os lotes de contato OpenCAMLib são independentes e usam até oito processos automaticamente, conforme o tamanho do trabalho e os processadores disponíveis. Trabalhos pequenos permanecem seriais para evitar o custo de iniciar processos. A variável de ambiente `CAM_WORKERS`, de 1 a 32, permite limitar o orçamento; o valor também respeita o número de processadores disponíveis. Reinicie o aplicativo após mudar essa variável. Usar mais processos não garante menor tempo em trabalhos pequenos.

As provas de material removido respeitam a ordem dos cortes. Para bordas curvas densas, o motor procura um subconjunto de passadas já concluídas e verifica a cobertura integral por diferença de polígonos. Subconjuntos locais podem ser reutilizados após conferir novamente a profundidade; quando não comprovam cobertura, a união completa continua sendo usada. As caches têm limites de entradas e memória. Amostragem, margens da fresa e limites de profundidade não são reduzidos para acelerar o cálculo.

## Simulação

A grade acompanha o volume removido e as regiões protegidas. Ao pausar, uma reconstrução com Manifold suaviza a superfície exibida. A reprodução 1× segue o feedrate programado; a velocidade rápida é uma hipótese configurável. A simulação é aproximada e não substitui as provas geométricas nem o preparo da máquina.

## Limitações

- Ferramentas de topo reto; sem simulação da haste ou do porta-ferramenta.
- Sem controle de máquina, pontes de fixação ou verificação de colisões com acessórios.
- Cutout da silhueta completa; não substitui acabamento de paredes variáveis ou superfícies inferiores.
- Diagnóstico de superfícies inacessíveis não certifica a usinabilidade completa de qualquer malha.
- Furos menores que o envelope conservador da fresa são sinalizados, sem ativar Drill automaticamente.
- Tempos não incluem aceleração, troca de ferramenta ou espera do spindle.

Nenhum modelo particular ou percurso pré-calculado é necessário para iniciar o programa.
