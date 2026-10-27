# Mega Harness

Interface de chat e comparação de modelos, com fornecedores OpenAI compatíveis, modo Agent e área de trabalho `projetos/`.

## Executar

Abre `index.html` num browser moderno ou importa `Kaggle-Qwen-Base-URL.ipynb` no Kaggle para iniciar o endpoint Qwen. No Kaggle, ativa Internet e GPU. A célula imprime apenas o Base URL; no Mega Harness configura um fornecedor Personalizado e usa o ID de modelo `qwen3.8-27b-abliterated`.

O notebook usa Q4_K_XL e descarrega o modelo na primeira execução; depois reutiliza a cache enquanto a sessão Kaggle mantiver os ficheiros. O túnel Quick Tunnel é temporário. O servidor não exige chave API para que a ligação use só o Base URL: qualquer pessoa que obtenha o endereço do túnel pode enviar pedidos enquanto a sessão estiver ativa. Não partilhes o endereço.

## Ficheiros

- `index.html` — aplicação Mega Harness completa.
- `Kaggle-Qwen-Base-URL.ipynb` — notebook Kaggle de uma célula.
