# Mega Harness

App de chat com backend Python/FastAPI, modo Agent para `projetos/`, anexos em blocos até 10 GB, leitura de texto por partes, inspeção de ZIP e imagens no chat.

## ShardCloud

Liga o repositório `0299jolgue/Harness` a uma app Python e configura:

- Arranque: `pip install -r requirements.txt && python app.py`
- Host: `0.0.0.0`
- Porta: variável `PORT` do ShardCloud; por omissão usa 80.
- Diretório de trabalho: raiz do repositório.
- Segredo estável: cria a variável `MEGA_HARNESS_KEY` no ShardCloud. Se não a definires, a app cria uma chave aleatória a cada arranque e escreve-a uma vez nos logs. Usa-a no primeiro acesso ao site.

Ativa armazenamento persistente no ShardCloud se quiseres conservar os ficheiros de `projetos/` entre substituições da instância. A pasta está no servidor ShardCloud; não é uma pasta do iPad.

## Qwen no Kaggle

Executa `Kaggle-Qwen-Base-URL.ipynb` com Internet e GPU e copia o endereço para **Definições → Fornecedores**. O notebook descarrega também `mmproj-model-bf16.gguf`: o projetor multimodal é necessário para o llama.cpp aceitar imagens. A primeira transferência/carregamento pode demorar mais. O túnel Cloudflare é temporário e não exige chave nesta versão do notebook; mantém o URL privado.

Para outro fornecedor, configura a chave API em Definições. A chave fica no navegador e é enviada ao backend apenas com os pedidos.

## Imagens no chat e Z-Image-Turbo

O botão `+` anexa imagens e outros ficheiros. Imagens são enviadas ao Qwen como entrada visual, desde que o servidor esteja com o `mmproj` carregado. ZIPs podem ser listados, lidos por partes ou extraídos pelo Agent.

Para gerar imagens, abre [Z-Image-Turbo-Colab.ipynb](https://colab.research.google.com/github/0299jolgue/Harness/blob/main/Z-Image-Turbo-Colab.ipynb), ativa GPU e executa a célula. Copia a Base URL e a chave API mostradas para **Definições → Imagens**. Depois pede ao Agent para criar a imagem; a imagem aparece diretamente na conversa e fica guardada em `projetos/geradas/`. O runtime e o túnel do Colab têm de continuar ligados.

## Agent e ficheiros

Uploads são enviados em blocos de 8 MB até ao limite de 10 GB por ficheiro. O Agent lê ficheiros de texto em blocos de 8 KB, pode procurar texto em ficheiros grandes, e tem ferramentas para listar/ler/extrair ZIPs. O conteúdo completo de um ficheiro de 10 GB não cabe numa única mensagem do modelo: o Agent lê partes ou pesquisa só o que precisa. Edição do Agent está limitada a 64 MB; criação/escrita por chamada a 8 MB. O Agent não executa comandos do sistema e só acede a `projetos/`. Apagar continua a exigir aprovação individual.

O histórico e as configurações dos fornecedores ficam neste navegador. O backend protege a API e os ficheiros com uma sessão autenticada pelo segredo de acesso da app.

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
MEGA_HARNESS_KEY='escolhe-uma-chave-local' python app.py
```

Abre `http://localhost:80` (ou a porta em `PORT`).
