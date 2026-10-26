# Arquitetura e limites

A janela nativa usa pywebview / WebView2. Um servidor HTTP restrito ao loopback serve a interface, Three.js e os workers de simulação. Escritas e comandos exigem um token efêmero; a descoberta do runtime fica no diretório de dados do usuário.

O STL é lido, convertido para milímetros e posicionado antes de calcular. Clipper2, através de pyclipr, executa as operações de polígonos. O contato da ponta plana com a malha usa OpenCAMLib, chamado em processo Node.js separado. Sombras por altura protegem a geometria 3D.

No modo inteligente, a projeção externa preenchida define o envelope de planejamento do Rough. O gerador desconta a peça protegida em cada altura, incluindo formas abertas à borda. Keep In e Keep Out limitam somente o Rough. O perfil externo nominal fica no Cutout; camadas só são omitidas quando cortes já concluídos comprovam remoção integral.

O cálculo roda em processo separado, com progresso e cancelamento. A validação reconstrói as entradas, profundidades e ligações; a exportação relê o NC arredondado. O pós-processador usa movimentos lineares, milímetros, coordenadas absolutas e G54.

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
