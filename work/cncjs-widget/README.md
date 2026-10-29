# CAM · Perfil GRBL para CNCjs

Painel personalizado para CNCjs 1.9.12–1.x. Usa o Socket.IO e a porta já aberta pelo CNCjs; não precisa do EXE do CAM Local nem de uma segunda conexão USB.

No servidor, coloque esta pasta em um caminho estático do CNCjs. Como alternativa suportada, configure `mountPoints` com `{ "route": "/cam-perfil", "target": "/caminho/cam-perfil" }`. A montagem configurada exige reinício do servidor; copiar a pasta para um diretório estático que já é servido permite instalar sem reiniciar. Atualizações do CNCjs podem remover arquivos adicionados ao diretório do pacote; mantenha esta cópia para reinstalar.

Abra `/cam-perfil/install.html` no mesmo navegador e endereço que você usa para o CNCjs. O instalador acrescenta o widget ao layout local e preserva os outros painéis e a autenticação. Também é possível adicioná-lo em **Manage Widgets → Custom**, usando o título **CAM · Perfil GRBL** e a URL `/cam-perfil/index.html`. A seleção é por navegador, como os outros widgets do CNCjs.

Conecte a CNC normalmente no CNCjs. No painel, **Ler do GRBL** mostra os valores reais; os campos editados permanecem intactos. **Gravar no GRBL** envia somente os máximos $110–$112 e as acelerações $120–$122 e confirma os valores por releitura. Requer Idle, workflow parado e filas vazias; não use Console, Jog ou Iniciar durante a transferência. Outra atividade interrompe as próximas escritas. Falha ou resposta incerta exige nova leitura; a gravação não é repetida automaticamente.

O backup anterior à escrita fica no armazenamento local do navegador, limitado às dez últimas operações, e no JSON do próprio painel. Use **Copiar JSON** quando o sandbox do CNCjs bloquear downloads. Tokens de autenticação não entram no backup. Se não for possível persistir o backup, a gravação é interrompida antes da próxima alteração.

O widget se associa apenas a uma porta que o CNCjs acabou de informar como aberta. A API pública faz essa associação pelo evento `open`, cujo caminho de porta já aberta não reinicia nem fecha o USB. Ela não oferece uma associação atômica condicionada à porta aberta; não desconecte a porta enquanto o widget se associa. Sair do painel desconecta somente seu cliente de observação, sem emitir fechamento da porta, reset, desbloqueio ou movimentos.

Referências: [widget oficial](https://github.com/cncjs/cncjs-widget-boilerplate), [API do servidor](https://github.com/cncjs/cncjs/blob/master/src/server/services/cncengine/CNCEngine.js). O código deste painel é original e MIT. O cliente Socket.IO é fornecido pelo próprio CNCjs, sem CDN.
