# Remoção visual 2,5D na GPU

A superfície de remoção usa o WebGL2 do WebView2, pelo Three.js já incluído no aplicativo. Cada movimento cortante é uma instância com a caixa XY varrida pela ferramenta. O fragment shader calcula o menor Z da interseção disco/segmento, incluindo rampas, e o depth test acumula esse mínimo numa textura de profundidade. Os rápidos não removem material.

Um segundo shader apresenta o mapa como colunas de material por raycast/DDA numa caixa. Isso mantém paredes verticais e furos passantes sem criar uma malha booleana na CPU. Uma fração de movimento usa somente seu trecho já percorrido; voltar na barra recompõe o prefixo correspondente na GPU. Nenhum corte futuro é usado. A textura final pode ser guardada separadamente para acesso direto.

A resolução padrão é até 2048 amostras por eixo, mantendo o aspecto do bruto. Num bruto de 94 mm, são aproximadamente 0,046 mm por célula. A superfície continua sendo amostrada em XY: não representa rebaixos inferiores, deformação, queda de retalhos ou colisões com haste e fixação. O fundo físico usa o valor do bruto no modo inteligente ou assume o fundo do STL; ele não é a profundidade de um bolsão raso. A profundidade extra do Cutout pode ultrapassar esse fundo sem criar um chão falso.

O orçamento padrão do módulo é 96 MiB para texturas e atributos. Dois alvos 2048² usam aproximadamente 64 MiB, além dos movimentos. A reprodução normal não lê a textura inteira na CPU nem sincroniza cada quadro com gl.finish. O diagnóstico de volume e regiões protegidas continua em um worker CPU, separado da superfície visual. Se o contexto gráfico não for compatível, o simulador anterior permanece como fallback.

## Verificação por comandos

Depois de calcular, use simulation.set com mode stock e simulation.wait com surface gpu. state.simulation.gpu informa placa/driver expostos pelo WebGL, resolução, memória, target e geração. ready significa que os comandos da posição atual foram submetidos; não é uma medição de conclusão física da GPU.

simulation.sample com surface gpu lê até 64 pontos e identifica os centros das células efetivamente amostradas. A leitura sincroniza somente esse diagnóstico. A comparação com a grade CPU deve usar o centro de cada grade, porque suas resoluções podem ser diferentes.

simulation.benchmark aceita até 16 frações e até três repetições, limitadas a 32 quadros. completed_ms inclui a remoção, o desenho e uma sincronização gl.finish explícita, usada apenas nesse benchmark. last_seek_ms e submission_ms medem a submissão de comandos na CPU, não devem ser apresentados como tempo concluído da GPU. O benchmark restaura a vista e a posição de reprodução.

Os testes comparam alturas com a equação analítica, incluindo rampas ascendentes/descendentes, mergulho, frações, rápidos e rewind. O teste nativo também compara o hash do NC exportado; a simulação não altera os percursos.

## Repositórios e documentação consultados

- [jscut: rasterização do percurso em framebuffer](https://github.com/tbfleming/jscut/blob/e22fb34b01e946a808b03bce959a80b25719c822/js/RenderPath.js#L351): referência da arquitetura. O projeto é GPL; nenhum código dele foi incorporado.
- [CNCWebSim](https://github.com/filipecaixeta/cncwebsim/blob/c0fe81aeda797f9a4a871f9f35e0199c23d6ec61/js/mill.js): referência MIT de rasterização do corte; seu readback de malha para a CPU foi evitado no caminho visual.
- [GridSpace/raster-path](https://github.com/GridSpace/raster-path): referência MIT de heightmaps e compute WGSL, orientada à geração de percursos.
- [Three.js: DepthTexture](https://threejs.org/docs/pages/DepthTexture.html), [render targets](https://threejs.org/manual/pages/rendertargets.html) e [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html): biblioteca MIT efetivamente usada.
- [Especificação WebGL2](https://registry.khronos.org/webgl/specs/latest/2.0/): instancing, depth textures e fragment depth.

Os shaders do CAM Local foram escritos para sua equação de corte e continuam sob a licença MIT do projeto. Não foi adicionada uma dependência GPU externa nem é necessária uma instalação separada de CUDA ou Vulkan.
