# Pipeline de preços de concorrentes — API Django

Serviço que recebe o CSV diário de preços dos concorrentes (`dados/precos_concorrentes.csv`),
o converte em JSON com **pandas**, processa em segundo plano e expõe o histórico/preço vigente
por uma API JWT. Linhas que não puderem ser aproveitadas caem em **quarentena com motivo** —
nenhuma linha é descartada em silêncio.

> **Tratamento do CSV:** a camada de conversão (`data/parsers.py`, CSV → JSON com pandas) está
> implementada. As regras de **validação e normalização** do conteúdo
> (`data/validators.py` e `data/normalizers.py`) ficaram **vazias de propósito** e são de
> implementação manual — veja [Onde implementar o tratamento](#onde-implementar-o-tratamento).

---

## Como rodar

### Opção A — Docker Compose (recomendado)

```bash
docker compose up --build
```

Sobe Postgres, Redis, API (`http://localhost:8000`) e o worker Celery, com migrations
automáticas. Crie um usuário de API:

```bash
docker compose exec web python manage.py criar_usuario \
  --username pricing --password senha-forte-123 --superuser
```

### Opção B — local (sem Docker)

Requer Postgres e Redis rodando (ou `docker compose up -d db redis`):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                # ajuste senhas/host se preciso
python manage.py migrate
python manage.py criar_usuario --username pricing --password senha-forte-123
python manage.py runserver                          # API em http://localhost:8000
celery -A core worker --loglevel=INFO               # em outro terminal (processamento)
```

### Comandos úteis

| Comando | O que faz |
|---|---|
| `python manage.py migrate` | Cria/atualiza o schema |
| `python manage.py criar_usuario --username X --password Y [--superuser]` | Cria usuário de API |
| `python manage.py runserver` | Sobe o Django (dev) |
| `celery -A core worker --loglevel=INFO` | Worker de processamento |
| `python manage.py check` | Sanidade da configuração |

---

## Como testar

```bash
pip install -r requirements-dev.txt
pytest                    # roda tudo
pytest -q                 # resumido
pytest tests/test_imports_api.py -v
pytest --cov=apps --cov=data --cov-report=term-missing   # cobertura
```

A suíte usa SQLite em memória e Celery em modo síncrono (`core/settings/test.py`), sem
dependência de Postgres/Redis.

---

## Autenticação

Todos os endpoints exigem JWT (`Authorization: Bearer <access>`).

```bash
# obter token
curl -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username": "pricing", "password": "senha-forte-123"}'

# renovar
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H 'Content-Type: application/json' -d '{"refresh": "<refresh>"}'

# usuário autenticado
curl http://localhost:8000/api/auth/me/ -H "Authorization: Bearer <access>"
```

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/importacoes/` | Upload do CSV (`campo: arquivo`). Responde **202 imediato** (<2s); processa em background (Celery). |
| `GET` | `/api/importacoes/` | Lista paginada: status e contadores de cada importação |
| `GET` | `/api/importacoes/{id}/` | Andamento/resultado: `status`, `total_linhas`, `processadas`, `quarentena_count`, `duplicadas_count`, `erro` |
| `GET` | `/api/importacoes/{id}/quarentena/` | Linhas não aproveitadas + motivos. Filtro `?status=nao_importadas\|quarentena\|duplicada\|importada\|todas` |
| `GET` | `/api/precos/?sku=&uf=&vendedor=` | Lista **paginada do preço vigente** (filtros opcionais) |
| `GET` | `/api/produtos/{sku}/referencia/?uf=` | Preço de referência de mercado (mediana dos vigentes) + preço líquido de ICMS (18%) |

Exemplos:

```bash
# importar
curl -X POST http://localhost:8000/api/importacoes/ \
  -H "Authorization: Bearer $TOKEN" -F "arquivo=@dados/precos_concorrentes.csv"

# acompanhar (poll até status=concluida|falhou)
curl http://localhost:8000/api/importacoes/1/ -H "Authorization: Bearer $TOKEN"

# quarentena
curl "http://localhost:8000/api/importacoes/1/quarentena/" -H "Authorization: Bearer $TOKEN"

# preço vigente
curl "http://localhost:8000/api/precos/?sku=SKU-1011&uf=SP" -H "Authorization: Bearer $TOKEN"

# referência de mercado + ICMS
curl "http://localhost:8000/api/produtos/SKU-1011/referencia/" -H "Authorization: Bearer $TOKEN"
```

Resposta de upload:

```json
{"id": 1, "status": "pendente", "duplicado": false, "detalhe": "Importação aceita; acompanhe o andamento neste recurso.", ...}
```

Reenviar o **mesmo arquivo** devolve `202` com `"duplicado": true` e o `id` da importação
anterior (nenhum dado novo é processado).

---

## Decisões de modelagem

- **`Importacao`** — um upload; guarda hash SHA-256 do conteúdo, status
  (`pendente → processando → concluida|falhou`), contadores e erro.
- **`ImportacaoLinha`** — auditoria linha a linha: *toda* linha lida vira um registro
  (`importada`, `quarentena` ou `duplicada`) com os dados originais (JSON) e os motivos.
  Garante o requisito "nenhuma linha descartada em silêncio".
- **`Produto`** (SKU único, EAN opcional), **`Vendedor`** (identidade pela chave normalizada)
  e **`Preco`** — histórico imutável: cada coleta é um registro novo, nunca atualizado in place.
- **Chave natural** `UNIQUE(produto, vendedor, uf, coletado_em)` em `Preco` — proteção no nível
  do banco contra duplicação (reimportações e repetições dentro do mesmo arquivo).
- **Preço vigente** — coluna `is_vigente` por (produto, vendedor, UF), mantida na importação:
  o da última coleta (`coletado_em` maior). Consulta filtrada em `?` via `is_vigente=True`.
- **Processamento assíncrono** — `POST` grava o arquivo, calcula o hash, agenda a tarefa com
  `transaction.on_commit` e responde 202; o worker Celery faz o resto (requisito: ≤2s).
- **Quarentena é endpoint** — `ImportacaoLinha` exposta paginada com `motivos` (lista de strings
  em português, pronta para exibição) e `dados_originais` (linha crua do CSV).
- **Paginação** — `PageNumberPagination`, 20 por página (padrão DRF).

## Premissas assumidas (onde o enunciado era ambíguo)

1. **ICMS:** o preço de mercado **já inclui** ICMS → líquido = `preço / 1.18`
   (e não `preço × (1 − 0,18)`). Arredondamento: 2 casas, meio para cima (ROUND_HALF_UP).
2. **Preço de referência de mercado:** **mediana** dos preços *vigentes* do produto
   (robusta a outliers), opcionalmente restrita a uma UF (`?uf=`). Sem preço vigente → `404`.
3. **Preço vigente:** o da última coleta por (produto, vendedor, UF). Empate de data/hora é
   impossível — a chave natural única impede dois registros com o mesmo instante.
4. **Idempotência:** arquivos com SHA-256 idêntico não são reprocessados (o `id` anterior é
   reutilizado com `duplicado: true`). Importações `falharam` ficam fora da checagem para
   permitir nova tentativa; além disso a chave natural única barra duplicatas na camada do banco.
5. **Duplicatas dentro do arquivo:** a *primeira* ocorrência é importada; repetições posteriores
   viram linha `duplicada` com motivo apontando o registro existente (nada é perdido).
6. **Datas sem fuso** (ex.: `04/03/2025 13:41`) devem ser interpretadas em
   `America/Sao_Paulo`; o serviço converte datetimes *naive* para o fuso configurado como
   rede de segurança (`USE_TZ=True`). A conversão em si é responsabilidade de
   `data/normalizers.py`.
7. **Fuso/`Z`:** `2025-03-10 12:09:00Z` é UTC absoluto; a normalização decide o instante final.
8. **EAN:** campo opcional. Linha sem EAN aproveitável mantém o EAN já cadastrado no produto;
   EAN **divergente** para o mesmo SKU rejeita a linha (motivo único e explícito na quarentena).
9. **Moeda:** o sistema trabalha apenas em BRL (moeda ≠ BRL é regra de rejeição da validação).
10. **Escopo de listagens:** `/api/importacoes/` mostra importações de todos os usuários
    (ferramenta do time de precificação, não é SaaS multi-tenant).
11. **Limites de upload:** 20 MiB e extensão `.csv` (acima → `413`; extensão inválida → `400`).
12. **Referência/UF:** `uf` é validada por formato (2 letras, caixa normalizada). Siglas
    plausíveis porém inexistentes (ex.: `XX`) passam no formato e simplesmente não casam com dados.

---

## Onde implementar o tratamento

A fronteira entre o sistema e o CSV é o pacote **`data/`**:

| Arquivo | Situação | Papel |
|---|---|---|
| `data/parsers.py` | ✅ implementado (pandas) | CSV → `list[dict]` JSON-áveis. Preserva linha truncada (campos `""`) e coluna extra (`_extras`). Falhas estruturais = `ArquivoInvalido` (importação inteira falha, com mensagem). |
| `data/validators.py` | ⬜ **vazio — implementar** | `validar_linha(bruta) -> list[str]` com os motivos de rejeição (pt-BR). |
| `data/normalizers.py` | ⬜ **vazio — implementar** | `processar_linha(bruta) -> LinhaNormalizada` (levanta `LinhaRejeitada(motivos)` quando rejeitar) e `normalizar_vendedor(nome) -> str` (chave de deduplicação usada por `/api/precos/?vendedor=`). |
| `tests/test_validators.py` | ⬜ scaffold com `skip` | Seus testes das regras de validação. |
| `tests/test_normalizers.py` | ⬜ scaffold com `skip` | Seus testes das regras de normalização. |
| `docs/relatorio-dados.md` | ⬜ scaffold | Relatório: o que estava errado no CSV e como cada caso foi tratado. |

Fluxo: `POST` → pandas (`carregar_records`) → para cada registro:
`processar_linha` (valida + normaliza) → persiste, ou `LinhaRejeitada` → quarentena com motivos.
O resto do pipeline (deduplicação, vigência, contadores, quarentena, API) já está implementado e
testado — a única coisa que falta são as funções acima.

### Biblioteca de parsing (justificativa — exigida pelo enunciado)

Usa-se **pandas** (`pd.read_csv`) apenas para a conversão estrutural CSV → registros JSON
(`data/parsers.py`), a pedido de quem trata os dados. pandas lida com o separador `;`, aspas
escapadas (`"Notebook 15"" 8GB"`) e a coluna extra sem código manual de parsing. Nenhuma
biblioteca de IA/ML é usada; as regras de conteúdo são determinísticas, em Python padrão +
regex + Django.

---

## Relatório de qualidade dos dados

Em [`docs/relatorio-dados.md`](docs/relatorio-dados.md) — scaffold pronto para o relatório
linha a linha (problema → tratamento → motivo). As anomalias **estruturais** já tratadas pela
camada de conversão estão listadas no próprio relatório.

---

## Segurança

- Todos os endpoints exigem JWT; senhas com validadores do Django.
- ORM do Django em toda a persistência — nenhum SQL montado por concatenação
  (tentativas de injeção viram dados literais/`motivos`).
- Upload: extensão `.csv` obrigatória, limite de 20 MiB, arquivo salvo com nome aleatório
  (`upload_to` com UUID) — sem confiar no nome original.
- Valores de texto do CSV nunca são interpretados como fórmula/função pelos nossos códigos;
  na API saem como strings JSON inertes (a neutralização de `=`, `+`, `-`, `@` cabe na
  validação de conteúdo, em `data/validators.py`).
- Cabeçalho/decodificação inválidos falham com mensagem explícita (`ArquivoInvalido`), nunca
  com meio-processamento silencioso.

---

## Estrutura do projeto

```
├── core/                    # settings (base/dev/prod/test), urls, wsgi, celery
├── apps/
│   ├── imports/             # upload assíncrono, contadores, quarentena, task Celery
│   ├── products/            # Produto/Vendedor/Preco, /api/precos, /referencia
│   └── authentication/      # JWT (token/refresh/me) + comando criar_usuario
├── data/                    # fronteira do CSV (parsers ✅ | validators ⬜ | normalizers ⬜)
├── tests/                   # suíte pytest (84 testes + scaffolds pendentes)
├── docs/relatorio-dados.md  # relatório de qualidade dos dados
├── dados/precos_concorrentes.csv
├── docker-compose.yml / Dockerfile / entrypoint.sh
└── pytest.ini / requirements*.txt / .env.example
```

## Requisitos do enunciado → implementação

| Requisito | Onde |
|---|---|
| Upload responde ≤2s | `apps/imports/views.py` (202 + `transaction.on_commit`); teste `test_upload_do_csv_real_responde_em_ate_2s` |
| Reimportar não duplica | SHA-256 em `Importacao` + chave natural única em `Preco`; testes em `tests/test_dedup.py` |
| Vigente = última coleta | `services._atualizar_vigente`; testes em `tests/test_services.py` |
| Nenhuma linha em silêncio | `ImportacaoLinha` para toda linha; invariantes testados em `tests/test_imports_api.py` |
| Autenticação | JWT global (`REST_FRAMEWORK`); `tests/test_auth.py` |
| Sem IA | Regras determinísticas: pandas + Python/Django (nenhuma lib de ML) |
