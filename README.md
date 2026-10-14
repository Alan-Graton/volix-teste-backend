# Pipeline de preços de concorrentes — API Django

Serviço que recebe o CSV diário de preços dos concorrentes (`dados/precos_concorrentes.csv`),
o converte em JSON com **pandas**, processa em segundo plano e expõe o histórico/preço vigente
por uma API JWT. Linhas que não puderem ser aproveitadas caem em **quarentena com motivo** —
nenhuma linha é descartada em silêncio.

> **Tratamento do CSV:** implementado em `data/` — conversão CSV → JSON com
> **pandas** (`parsers.py`), regras de **validação** com os motivos em pt-BR
> (`validators.py`) e **normalização** para os tipos finais (`normalizers.py`),
> incluindo `tests/test_validators.py`, `tests/test_normalizers.py` e o teste
> de ponta a ponta com o arquivo real (`tests/test_importacao_real.py`).
> Veja [Tratamento do CSV](#tratamento-do-csv) e [Relatório de qualidade dos dados](#relatório-de-qualidade-dos-dados).

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
   viram linha `duplicada` com motivo apontando o registro existente (nada é perdido). A chave é
   montada com o vendedor normalizado, a UF em caixa alta e o instante já convertido — variações
   de caixa/espaços no vendedor (`CASASBAHIA` vs `Casas Bahia`) e de formato de data
   (`06/03/2025 17:26` vs ISO) casam entre si.
6. **Datas sem fuso** (ex.: `04/03/2025 13:41`) devem ser interpretadas em
   `America/Sao_Paulo`; o serviço converte datetimes *naive* para o fuso configurado como
   rede de segurança (`USE_TZ=True`). A conversão em si é responsabilidade de
   `data/normalizers.py`.
7. **Fuso/`Z`:** `2025-03-10 12:09:00Z` é UTC absoluto; a normalização decide o instante final
   (apresentação em America/Sao_Paulo).
8. **EAN:** campo opcional. Linha sem EAN aproveitável mantém o EAN já cadastrado no produto;
   EAN **divergente** para o mesmo SKU rejeita a linha (motivo único e explícito na quarentena).
   Quando presente, precisa ser GTIN-13 válido (13 dígitos + dígito verificador) — caso contrário
   a validação rejeita.
9. **Moeda:** o sistema trabalha apenas em BRL (moeda ≠ BRL é regra de rejeição da validação).
10. **Escopo de listagens:** `/api/importacoes/` mostra importações de todos os usuários
    (ferramenta do time de precificação, não é SaaS multi-tenant).
11. **Limites de upload:** 20 MiB e extensão `.csv` (acima → `413`; extensão inválida → `400`).
12. **Referência/UF:** `uf` é validada contra os **27 estados** (caixa normalizada: `sp` → `SP`;
    sigla inexistente como `XX` cai na quarentena com motivo).
13. **Whitelist de vendedores:** só entram as chaves conhecidas dos concorrentes do catálogo
    (`carrefour`, `amazonbr`, `mercadolivre`, `magazineluiza`, `casasbahia`). É a barreira
    anti-injeção em `vendedor` (ex.: `x'; DROP TABLE precos;--` → quarentena).
14. **Faixa de preço plausível:** R$ 0,05 a R$ 10.000,00 — `0,00`/`-5,90` são "não positivos"
    e `0,01`/`999.999,99` caem fora da faixa (ruído/extremos não contaminam o histórico).
15. **Cadastro de produto:** a **primeira linha** de cada SKU define nome, embalagem e EAN.
    Linhas seguintes com nome divergente (ignorando caixa/espaços) ou embalagem divergente
    rejeitam com motivo — o cadastro não é sobrescrito silenciosamente. Só o EAN ausente é
    preenchido depois.
16. **Formato de datas:** dia/mês primeiro (`04/03/2025` = 4 de março); se não for válida em
    dia/mês, tenta mês/dia (`03/25/2025` = 25 de março). Datas **no futuro** (com folga de 1 dia)
    rejeitam.
17. **Estoque/embalagem:** `esgotado` → estoque `0`; estoque vazio → `None` (desconhecido);
    estoque negativo ou não numérico rejeita; embalagem vazia → `1`; embalagem < 1 rejeita.
18. **Segurança de conteúdo:** texto com início de fórmula (`=`, `+`, `@`) em `sku`/`produto`
    rejeita (`=HYPERLINK(...)` nunca é interpretado); nada do CSV vira SQL — só ORM.
19. **Formatos numéricos aceitos:** pt-BR (`3.169,98`, `R$ 127,50`), en-US (`1234.56`) e
    só-ponto em grupos de 3 = milhar (`1.299` = R$ 1.299,00; `1.299.90` = R$ 1.299,90).
    Dinheiro é `Decimal` extraído da string — nunca passa por float.

---

## Tratamento do CSV

A fronteira entre o sistema e o CSV é o pacote **`data/`**:

| Arquivo | Situação | Papel |
|---|---|---|
| `data/parsers.py` | ✅ pandas | CSV → `list[dict]` JSON-áveis. Preserva linha truncada (campos `""`) e coluna extra (`_extras`). Falhas estruturais = `ArquivoInvalido` (importação inteira falha, com mensagem). |
| `data/validators.py` | ✅ pandas + stdlib | `validar_linha(bruta) -> list[str]` com **todos** os motivos de rejeição da linha (pt-BR): preços (ausente/não numérico/não positivo/fora da faixa), promoção > preço, moeda ≠ BRL, estoque, embalagem, UF (27 estados), datas (impossível/futura), EAN GTIN-13, whitelist de vendedores, fórmulas de planilha e coluna extra. |
| `data/normalizers.py` | ✅ | `processar_linha(bruta) -> LinhaNormalizada` (valida e converte; `LinhaRejeitada(motivos)` quando rejeita), `normalizar_vendedor(nome) -> str` (chave de deduplicação/filtro da API), `titulo` e `nomes_coincidem`. |
| `tests/test_validators.py` | ✅ | Regras de validação, caso a caso. |
| `tests/test_normalizers.py` | ✅ | Conversões (Decimal, datas, vendedor, título). |
| `tests/test_importacao_real.py` | ✅ | Ponta a ponta com o CSV real e o tratamento verdadeiro (288 importadas / 22 quarentena / 11 duplicadas). |
| `docs/relatorio-dados.md` | ✅ | Relatório: o que estava errado no CSV e como cada caso foi tratado. |

Fluxo: `POST` → pandas (`carregar_records`) → para cada registro:
`processar_linha` (valida + normaliza) → persiste, ou `LinhaRejeitada` → quarentena com motivos.
As conversões usadas pela validação são **as mesmas** reaproveitadas pela normalização
(`validators.preco_em_decimal`, `validators.data_em_datetime`, ...), então validação e
conversão nunca discordam.

### Bibliotecas de dados (justificativa — exigida pelo enunciado)

Usa-se **pandas** nos dois pontos pedidos, sem nenhuma biblioteca de IA/ML:

- **`data/parsers.py`** — `pd.read_csv` para a conversão estrutural CSV → registros JSON:
  separador `;`, aspas escapadas (`"Notebook 15"" 8GB"`) e coluna extra sem código manual
  de parsing.
- **`data/validators.py`** — `pd.to_datetime(..., errors='coerce')` para interpretar as
  datas (formato explícito no ramo com barra, fallback dia/mês → mês/dia) e
  `pd.to_numeric(..., errors='coerce')` como gate dos campos numéricos. O valor final de
  dinheiro é `Decimal` extraído da string canônica (exatidão de 2 casas, sem float).

As regras de conteúdo são determinísticas: Python padrão + regex + pandas + Django.

---

## Relatório de qualidade dos dados

Resultados da validação do arquivo real `dados/precos_concorrentes.csv` (321 linhas de dados;
a numeração abaixo é a **linha de dados**, a mesma usada pela API de quarentena — no arquivo
 físico, some 1 por causa do cabeçalho):

| Destino | Linhas | O que acontece |
|---|---:|---|
| Importadas | **288** | válidas → `Preco` (vigente/histórico) |
| Quarentena | **22** | inválidas → `ImportacaoLinha` com motivos em pt-BR |
| Duplicadas | **11** | repetição de chave natural (primeira ocorrência importada) |
| **Total** | **321** | nenhuma linha perdida |

### Erros encontrados (22 linhas → quarentena)

| Linha | Problema no dado | Motivo aplicado |
|---:|---|---|
| 41 | preço `0,00` | preço não positivo |
| 58 | preço vazio | preço ausente |
| 59 | nome `AÃºcar Cristal 1kg` (mojibake) divergente do cadastro do SKU | nome divergente do produto |
| 65 | preço `Sob consulta` | preço inválido (não numérico) |
| 128 | EAN `789000137019` — 12 dígitos | EAN fora do formato GTIN-13 |
| 131 | data `30/02/2025 10:00` (dia inexistente) | data inválida |
| 162 | nome `Fone "Pro"; edição limitada` divergente | nome divergente do produto |
| 163 | promoção `25,00` > preço `10,00` | promoção acima do preço cheio |
| 174 | preço `999.999,99` | fora da faixa (R$ 0,05–10.000,00) |
| 181 | estoque `-3` | estoque negativo |
| 190 | vendedor `x'; DROP TABLE precos;--` | fora da whitelist de vendedores |
| 206 | EAN `7890001370000` | dígito verificador GTIN-13 incorreto |
| 210 | produto `=HYPERLINK(...)` | início de fórmula de planilha |
| 225 | nome + embalagem `Caixa c/ 12` divergentes | cadastro divergente (nome/embalagem) |
| 226 | preço `0,01` | fora da faixa (mínimo R$ 0,05) |
| 237 | preço `-5,90` | preço não positivo |
| 241 | moeda `USD` | moeda ≠ BRL |
| 257 | data `2031-01-01` | data no futuro |
| 295 | UF `XX` | UF fora dos 27 estados |
| 306 | EAN `7,89E+12` | fora do formato GTIN-13 |
| 320 | linha **truncada** (só 4 campos) | 6 motivos: vendedor, UF, moeda, preço, data ausentes + EAN |
| 321 | **coluna extra** (`coluna-extra`) | coluna extra não prevista no cabeçalho |

### Duplicatas (11 linhas → `duplicada`)

A chave é (SKU + vendedor normalizado + UF + instante da coleta) **depois** da normalização:
a primeira ocorrência importa; a repetição aponta o registro existente.

- **6 byte a byte idênticas:** linhas 222, 274, 276, 278, 289, 313.
- **5 que diferem só em caixa/espaços** (mesmo dado, grafia diferente): 84, 192, 196, 215,
  296 — ex.: `casasbahia` vs `Casas Bahia`, `notebook 15" 8gb` vs `Notebook 15" 8GB`,
  `"  Carrefour "` vs `Carrefour`.

Pares completos (repetição → primeira ocorrência): 84→37, 192→53, 196→12, 215→159,
222→176, 274→242, 276→77, 278→104, 289→219, 296→25, 313→97.

### Casos "estranhos" que passam na validação (não são erros)

Convertidos pela normalização em vez de rejeitados: `R$ 127,50` e `3.169,98` (pt-BR),
`1.299` (só-ponto = milhar), estoque `esgotado` → `0`, estoque vazio → `None`, data só com
data ou com `Z`/offset → `America/Sao_Paulo`, `03/25/2025` (fallback mês/dia → 25 de março),
UF `sp` → `SP`, vendedor `"  Carrefour "` → `carrefour`, nome em caixa baixa
(`cafeteira elétrica` → `Cafeteira Elétrica`), EAN vazio → `None`, embalagem vazia → `1`.

### Anomalias estruturais (camada de conversão, `data/parsers.py`)

- **Aspas escapadas** (linhas 1 e 162): `"Notebook 15"" 8GB"` e `Fone "Pro"; ...` — pandas
  desescapa; o conteúdo só cai na quarentena se ferir regra de conteúdo (caso da linha 162).
- **Linha truncada** (320): campos ausentes viram `""` e a validação aponta cada motivo.
- **Coluna extra** (321): capturada em `_extras` e rejeitada.

Relatório completo, linha a linha, em [`docs/relatorio-dados.md`](docs/relatorio-dados.md).
Os números acima são garantidos pelos testes de ponta a ponta em
`tests/test_importacao_real.py` (arquivo real, tratamento verdadeiro, sem dublê).

---

## Segurança

- Todos os endpoints exigem JWT; senhas com validadores do Django.
- ORM do Django em toda a persistência — nenhum SQL montado por concatenação
  (tentativas de injeção viram dados literais/`motivos`).
- Upload: extensão `.csv` obrigatória, limite de 20 MiB, arquivo salvo com nome aleatório
  (`upload_to` com UUID) — sem confiar no nome original.
- Valores de texto do CSV nunca são interpretados como fórmula/função pelos nossos códigos;
  na API saem como strings JSON inertes, e a validação rejeita `sku`/`produto` com início de
  fórmula (`=`, `+`, `@`) — ex.: `=HYPERLINK(...)` cai na quarentena. `vendedor` é aceito
  apenas pela whitelist de concorrentes (anti-injeção).
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
├── data/                    # fronteira do CSV (parsers ✅ | validators ✅ | normalizers ✅)
├── tests/                   # suíte pytest (203 testes, inclui o CSV real de ponta a ponta)
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
| CSV → JSON (pandas) | `data/parsers.py`; testes em `tests/test_parsers.py` |
| Tratamento/validação do CSV | `data/validators.py` + `data/normalizers.py`; testes em `tests/test_validators.py`, `tests/test_normalizers.py` e `tests/test_importacao_real.py` (arquivo real) |
| Sem IA | Regras determinísticas: pandas + Python/Django (nenhuma lib de ML) |
