# Central de Lojas

Visão por loja para o cliente de uma equipe de trade marketing: o que foi feito em cada ponto de venda, antes e depois, comparação com a concorrência e fotos de execução.

## Pipeline

1. `tools/extrair.py`: lê o data warehouse (SQL Server) e salva um snapshot.
2. `tools/montar.py`: aplica as regras de negócio (o que conta como visita, como calcular share, como tratar respostas duplicadas e visitas inválidas) e gera um resumo geral e um JSON por loja.
3. `tools/publicar.py`: grava no Firestore. O site (`public/index.html`) só lê os dados, com login.

## Uso de IA: fotos deitadas

O app de coleta salva parte das fotos deitadas e sem EXIF. Modelos locais não acertaram a orientação (`tools/orientacao.py`), então `tools/orientacao_claude.py` manda cada miniatura para um modelo de visão do Claude e grava quantos graus girar.

- Modo **piloto**: roda em fotos rotuladas à mão e mede **acerto e custo por foto** antes de processar tudo.
- Modo **lote**: usa a Batch API para processar o restante com custo menor.
- A chave da API vem de variável de ambiente, nunca do código.

## Stack

Python, pandas, SQL Server, Claude API (visão e Batch API), JavaScript, Firebase Auth, Firestore, Hosting.

---
Projeto feito no trabalho, publicado sem dados nem fotos do cliente.
