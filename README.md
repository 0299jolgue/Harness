# Mega Harness

App de chat com interface escura inspirada em ferramentas de conversa, backend Python/FastAPI e modo Agent para trabalhar exclusivamente em `projetos/`.

## Iniciar no ShardCloud

Cria uma aplicação Python, liga o repositório `0299jolgue/Harness` e configura:

- **Comando de arranque:** `pip install -r requirements.txt && python app.py`
- **Host:** `0.0.0.0`
- **Porta:** usa a variável `PORT` que o ShardCloud fornecer; se não existir, a app usa `80`.
- **Diretório de trabalho:** raiz do repositório.

A aplicação serve a interface e a API no mesmo serviço. A pasta `projetos/` fica na raiz da app. Em alojamentos com disco efémero, os ficheiros mudam ou desaparecem quando a instância é substituída; ativa armazenamento persistente/mount de volume no ShardCloud se essa opção estiver disponível.

## Ligar o Qwen do Kaggle

Abre `Kaggle-Qwen-Base-URL.ipynb`, executa a única célula no Kaggle com GPU e copia a Base URL impressa para **Definições → Fornecedores**. O ID do Qwen já fica preenchido e a chave API é opcional. Deixa a sessão Kaggle ativa enquanto usas a ligação: o URL do Cloudflare é temporário.

O endpoint rápido do Kaggle não exige chave API: qualquer pessoa que obtenha o URL temporário pode enviar pedidos ao modelo enquanto a sessão estiver ativa. Não publiques nem partilhes a Base URL. Para fornecedores que exigem autenticação, podes preencher a chave opcional nas definições; fica no `localStorage` do navegador e é enviada ao backend apenas com os pedidos. O backend não a escreve em ficheiros nem regista o corpo dos pedidos.

## Agent

O Agent pode listar, ler, criar, escrever, editar, pesquisar, criar pastas e mover itens em `projetos/`. O backend bloqueia caminhos fora da pasta, ignora ligações simbólicas, limita ficheiros a 150 KB e restringe execuções a oito rondas de ferramentas. Apagar um ficheiro exige aprovação individual na interface. Não executa comandos do sistema. Confirma alterações importantes antes de as usar.

As conversas e o fornecedor são guardados no navegador atual. A app não sincroniza histórico entre dispositivos.

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Depois abre `http://localhost:80` (ou a porta definida em `PORT`).
