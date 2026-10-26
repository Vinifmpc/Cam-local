# Contribuir

Use Python 3.12 x64 e Node.js 24 no Windows. Execute `scripts/setup.ps1`, altere os fontes e rode `.venv/Scripts/python.exe scripts/test.py` antes de abrir uma proposta de mudança.

Mudanças no motor precisam manter as provas de profundidade, continuidade, proteção de regiões e releitura do NC. Prefira modelos sintéticos pequenos e determinísticos nos testes; não envie peças pessoais ou NCs de clientes.

A interface e o cliente de comandos usam as mesmas funções de estado. Acrescente novas ações em `command_control.py`, `command_client.py` e `executeCommand` em `static/app.js`, em vez de depender de cliques automatizados.

Ao relatar um problema, descreva a versão, parâmetros e resultado esperado. Logs e projetos podem conter caminhos e geometria privada; compartilhe apenas o material necessário.

O aplicativo inicia sem peça. Um novo exemplo deve ser opcional e gerado a partir de geometria original, sem dados particulares.
