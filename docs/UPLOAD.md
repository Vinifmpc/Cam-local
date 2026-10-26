# Publicar no GitHub

Esta pasta contém o código para o repositório. O executável fica separado, em um ZIP de distribuição para anexar a uma **Release**.

## GitHub Desktop

1. Extraia `CAM-Local-GitHub.zip`.
2. No GitHub Desktop, escolha **File → Add local repository** e selecione a pasta `CAM-Local-GitHub`. Se extraiu o ZIP e ainda não houver um repositório Git, use a opção **create a repository here** apresentada pelo Desktop.
3. Confira os arquivos, faça o primeiro commit e use **Publish repository**.
4. Escolha o nome e a visibilidade do repositório.

## Terminal

Na pasta extraída, execute:

```powershell
git add .
git commit -m "Initial release of CAM Local"
git remote add origin https://github.com/SEU_USUARIO/CAM-Local.git
git push -u origin main
```

Substitua `SEU_USUARIO` e o nome pelo repositório que você criar. Se a pasta ainda não tiver `.git`, execute `git init -b main` primeiro. A identidade do commit e a autenticação são as da sua conta Git.

O `.gitignore` exclui `node_modules`, ambientes, builds, modelos STL, NCs, logs e perfis locais. Não envie a pasta de desenvolvimento inteira nem o ZIP do código como um único arquivo dentro do repositório: publique os arquivos extraídos.

## Executável

Depois de publicar o código, crie uma Release no GitHub e anexe `CAM-Local-Windows-publico.zip`. O workflow de build também permite gerar um ZIP no GitHub Actions pelo botão **Run workflow**. Dados pessoais, projetos locais e resultados da peça usada no desenvolvimento não fazem parte dessa distribuição pública.

## Publicação automática de uma versão

O workflow **Publish Windows release** testa, gera o pacote e publica uma Release com o ZIP e a soma SHA256. Execute-o por **Run workflow**, informando uma versão como `v0.1.1`, ou envie à `main` um commit cujo título seja exatamente `release: v0.1.1`. Commits normais executam os testes, sem publicar uma versão. Releases existentes não são sobrescritas; use um novo número de versão.
