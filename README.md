# Case técnico: pipeline de preços de concorrentes

Vaga: Engenheiro(a) de Software Back-end (Python/Django). Prazo sugerido: 4 a 6 horas.

## Contexto

O time de Web Scraping entrega, todo dia, um arquivo CSV com os preços coletados nos concorrentes. O arquivo vem sujo. Sua tarefa é transformar esse arquivo em dados confiáveis e expô-los por uma API que o time de precificação usa para tomar decisões.

O arquivo está em `dados/precos_concorrentes.csv` (321 linhas de dados, separador `;`).

## O que construir

1. **Importação.** Endpoint que recebe o CSV (`POST /api/importacoes/`), responde de imediato e processa em segundo plano. Outro endpoint informa o andamento e o resultado de cada importação.
2. **Tratamento dos dados.** Normalize preços, datas, identificadores, vendedores e demais campos. Linhas que não puderem ser aproveitadas vão para uma quarentena, cada uma com o motivo.
3. **Persistência.** Modele o banco para guardar o histórico de preços e permitir a consulta do preço vigente.
4. **Consultas.**
   - `GET /api/precos/?sku=&uf=&vendedor=`: lista paginada do preço vigente.
   - `GET /api/produtos/{sku}/referencia/`: preço de referência de mercado do produto e o preço líquido de ICMS, com alíquota de 18%.
   - `GET /api/importacoes/{id}/quarentena/`: linhas rejeitadas e motivos.
5. **Testes automatizados** das regras de tratamento e dos endpoints.

## Requisitos

- O upload deve responder em até 2 segundos, qualquer que seja o tamanho do arquivo.
- Importar o mesmo arquivo duas vezes não pode duplicar dados.
- O preço vigente de um produto é o da última coleta.
- Nenhuma linha do arquivo pode ser descartada em silêncio.
- Os endpoints exigem autenticação.

## Regra sobre o tratamento dos dados

**Sem IA.** O tratamento deve ser feito com regras determinísticas e testáveis: Python padrão, expressões regulares e Django. Não use LLMs, modelos de machine learning, APIs de IA nem bibliotecas de correspondência opaca para limpar ou classificar os dados. Se precisar de uma biblioteca de parsing, justifique no README.

## Entrega

- Faça um fork (ou cópia) deste repositório e trabalhe nele, com histórico de commits legível.
- Projeto Django que sobe com um comando documentado (Docker Compose é bem-vindo, mas opcional).
- Substitua este README pelo seu, contendo: como rodar, como testar, decisões de modelagem e **todas as premissas que você assumiu**. Onde o enunciado for ambíguo, decida, registre o motivo e siga em frente.
- Inclua um relatório curto (no README ou em arquivo à parte) listando o que você encontrou de errado nos dados e como tratou cada caso.

## Como avaliamos

| Critério | O que olhamos |
|---|---|
| Qualidade dos dados | Quantos problemas foram percebidos e se cada tratamento é correto e rastreável |
| Correção e robustez | Casos de borda, tipos adequados para dinheiro e datas, comportamento em reimportações |
| Arquitetura | Modelagem, separação de responsabilidades, processamento assíncrono |
| Segurança | Tratamento de entrada não confiável e controle de acesso |
| Testes | Cobertura das regras de negócio e dos casos de borda |
| Comunicação | Clareza do README, das premissas e das decisões |

Não esperamos que você acerte tudo. Esperamos que você perceba o que está errado, decida com critério e deixe isso explícito.
