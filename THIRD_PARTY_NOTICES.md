# Bibliotecas e licenças

A licença MIT na raiz cobre o código original do CAM Local. Dependências mantêm seus próprios avisos e termos.

| Componente | Versão declarada | Licença / fonte |
| --- | --- | --- |
| NumPy | 2.3.5 | BSD e avisos incluídos na distribuição; [fonte](https://github.com/numpy/numpy) |
| pyclipr / Clipper2 | 0.1.8 | Boost Software License 1.0; [fonte](https://github.com/drlukeparry/pyclipr) |
| OpenCAMLib, pacote Node | 2023.1.11 | O manifest npm declara LGPL-3.0; o tag upstream inclui também COPYING LGPL-2.1. Textos preservados; [fonte correspondente](https://github.com/aewallin/opencamlib/tree/2023.01.11) |
| Three.js | 0.180.0 | MIT; [fonte](https://github.com/mrdoob/three.js/tree/r180) |
| Manifold | 3.5.4 | Apache-2.0; [fonte](https://github.com/elalish/manifold) |
| pywebview | 6.2.1 | BSD-3-Clause; [fonte](https://github.com/r0x0r/pywebview) |
| Python.NET / clr-loader | 3.2.1 / 0.3.1 | MIT; avisos das distribuições instaladas |
| Python | 3.12 | PSF e componentes listados no seu LICENSE |
| Node.js | 24.x | MIT e avisos de terceiros do runtime distribuído |
| PyInstaller | 6.22.3 | GPL com exceção do bootloader; [licença](https://pyinstaller.org/en/stable/license.html) |

Os manifests e locks em `work/ui-runtime/` e `work/geometry-runtime/` registram as versões JavaScript resolvidas, inclusive dependências transitivas. A distribuição Windows inclui os textos em `licenses/` e as versões detectadas em `licenses/VERSIONS.json`.

O arquivo de fontes upstream de OpenCAMLib em `third_party/` é incluído também no pacote Windows, em `sources/`; URL e SHA256 estão em `third_party/SOURCES.json`. A biblioteca é usada por uma ponte Node separada. Para utilizar uma versão modificada, substitua a dependência em `work/geometry-runtime/` e reconstrua com `scripts/build.ps1`. O código original do CAM Local não altera a licença dessas fontes.

Os modelos de demonstração e de testes do projeto são geométricos e gerados pelo próprio código. Projetos locais, NCs fornecidos durante o desenvolvimento e ferramentas de análise externas não são necessários ao aplicativo.
