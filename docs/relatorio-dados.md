# Relatório de qualidade dos dados — `dados/precos_concorrentes.csv`

## Como ler este relatório

- **Fonte:** `dados/precos_concorrentes.csv` — separador `;`, UTF-8, cabeçalho + **321 linhas de dados**.
- **Numeração:** as linhas citadas são **linhas de dados** (1..321), como aparecem na API de
  quarentena (`ImportacaoLinha.numero_linha`). No arquivo físico, some 1 (cabeçalho = linha 1).
- **Método:** leitura e datas com pandas; regras determinísticas em
  `data/validators.py` (motivos de rejeição) e `data/normalizers.py` (conversões finais).
  Conversões compartilhadas: validação e normalização usam as mesmas funções
  (`preco_em_decimal`, `data_em_datetime`, `estoque_em_inteiro`, ...), então nunca discordam.

## Resultado agregado

| Destino | Linhas | Significado |
|---|---:|---|
| Importadas | **288** | linha válida → `Preco` (vigente/histórico) |
| Quarentena | **22** | linha inválida → `ImportacaoLinha` com motivos (pt-BR) |
| Duplicadas | **11** | repetição de chave natural dentro do arquivo (primeira ocorrência importada) |
| **Total** | **321** | nenhuma linha perdida, nenhum erro silencioso |

Catálogo final: 15 produtos, 5 vendedores, 4 moedas de negócio (BRL unicamente aceita),
27 UF's validadas.

## Anomalias linha a linha (→ quarentena)

| Linha | Problema no CSV | Motivo aplicado |
|---:|---|---|
| 41 | preço `0,00` | preço não positivo |
| 58 | preço vazio | preço ausente |
| 59 | nome `AÃºcar Cristal 1kg` (mojibake) divergente do cadastro do SKU | nome divergente do produto |
| 65 | preço `Sob consulta` | preço inválido (não numérico) |
| 128 | EAN `789000137019` — 12 dígitos | EAN fora do formato GTIN-13 |
| 131 | data `30/02/2025 10:00` (dia inexistente) | data inválida |
| 162 | nome `Fone "Pro"; edição limitada` divergente | nome divergente do produto |
| 163 | promoção `25,00` > preço `10,00` | promoção acima do preço cheio |
| 174 | preço `999.999,99` | fora da faixa plausível (R$ 0,05–10.000,00) |
| 181 | estoque `-3` | estoque negativo |
| 190 | vendedor `x'; DROP TABLE precos;--` | fora da whitelist de vendedores (anti-injeção) |
| 206 | EAN `7890001370000` | dígito verificador GTIN-13 incorreto |
| 210 | produto `=HYPERLINK(...)` | início de fórmula de planilha (segurança) |
| 225 | nome + embalagem `Caixa c/ 12` divergentes do cadastro | nome e embalagem divergentes |
| 226 | preço `0,01` | fora da faixa plausível (mínimo R$ 0,05) |
| 237 | preço `-5,90` | preço não positivo |
| 241 | moeda `USD` | moeda ≠ BRL |
| 257 | data `2031-01-01` | data no futuro |
| 295 | UF `XX` | UF fora dos 27 estados |
| 306 | EAN `7,89E+12` | fora do formato GTIN-13 |
| 320 | linha **truncada** (só 4 campos) | vendedor, UF, moeda, preço, data e EAN — 6 motivos |
| 321 | linha com **coluna extra** (`coluna-extra`) | coluna extra não prevista no cabeçalho |

Linha 320 (truncada) e 321 (extra) são anomalias **estruturais** detectadas pela camada de
conversão (`data/parsers.py`) e rejeitadas pela validação de conteúdo; ambas permanecem
consultáveis na quarentena com o registro original.

## Duplicatas (→ duplicada)

11 linhas repetem a chave natural (SKU + vendedor normalizado + UF + instante da coleta).
A **primeira** ocorrência é importada; a repetição vira linha `duplicada` apontando o
registro existente — nada é sobrescrito nem perdido.

| Repetição | Repete a linha | Diferença entre elas |
|---:|---:|---|
| 84 | 37 | caixa do nome (`cafeteira elétrica` vs `Cafeteira Elétrica`) e do vendedor (`casasbahia` vs `Casas Bahia`) |
| 192 | 53 | caixa do nome e do vendedor |
| 196 | 12 | caixa do nome e do vendedor (`CARREFOUR` vs `Carrefour`) |
| 215 | 159 | caixa do nome e do vendedor |
| 222 | 176 | byte a byte idêntica |
| 274 | 242 | byte a byte idêntica |
| 276 | 77 | byte a byte idêntica |
| 278 | 104 | byte a byte idêntica |
| 289 | 219 | byte a byte idêntica |
| 296 | 25 | caixa do nome (`notebook 15" 8gb`) e espaços no vendedor (`"  Carrefour "`) |
| 313 | 97 | byte a byte idêntica |

A chave de comparação é montada **depois** da normalização (vendedor sem acentos/espaços em
caixa baixa, UF em caixa alta, datas convertidas para `America/Sao_Paulo`), então variações
de caixa, espaços e formato que representam o mesmo instante casam entre si.

## Formatos "estranhos" que são válidos (aceitos e convertidos)

Estes casos passam na validação e são normalizados — não são erros:

| Caso | Exemplo no CSV | Tratamento |
|---|---|---|
| Preço com prefixo moeda | `R$ 127,50` | `Decimal('127.50')` |
| Milhar pt-BR | `3.169,98` | `Decimal('3169.98')` |
| Formato en-US | `1234.56`, `1,234.56` | reconhecido pela quantidade de pontos/vírgulas |
| Só-ponto em grupos de 3 | `1.299` | R$ 1.299,00 (milhar) |
| Último ponto como decimal | `1.299.90` | R$ 1.299,90 |
| Estoque textual | `esgotado` | estoque `0` (produto entra como indisponível) |
| Estoque vazio | campo vazio | estoque `None` (desconhecido, não é 0) |
| Data só com data | `2025-03-15` | meia-noite em `America/Sao_Paulo` |
| Data com offset | `2025-03-10 12:09:00-03:00` | instante absoluto convertido para SP |
| Data com `Z` | `2025-03-15 16:53:00Z` | UTC absoluto → SP |
| Data MM/DD (fallback) | `03/25/2025` | 25 de março (dia/mês inválido → mês/dia) |
| UF em caixa baixa | `sp` | `SP` |
| Nome do produto em caixa baixa | `cafeteira elétrica` (linha 13) | `Cafeteira Elétrica` — e define o cadastro do SKU |
| Vendedor com caixa/espaços extras | `"  Carrefour "`, `CARREFOUR` | chave `carrefour` |
| EAN vazio | campo vazio | `None` (mantém EAN já cadastrado no produto, se houver) |
| Embalagem vazia | campo vazio | `1` |

## Anomalias estruturais (camada de conversão — `data/parsers.py`)

| Linha | Problema | Tratamento |
|---:|---|---|
| 1 e 162 | aspas escapadas (`"Notebook 15"" 8GB"`, `Fone "Pro"; edição limitada`) | pandas desescapa corretamente; o conteúdo só cai na quarentena se ferir regra de conteúdo |
| 320 | linha truncada (4 campos) | campos ausentes viram `""` e a validação aponta cada motivo (6 ao todo) |
| 321 | coluna extra (`coluna-extra`) | capturada em `_extras` e rejeitada como "coluna extra não prevista" |

Falha estrutural de arquivo inteiro (cabeçalho/decodificação inválidos, separador errado) não
chega aqui: derruba a importação com `ArquivoInvalido` e mensagem explícita.

## Regras aplicadas (resumo)

- **Whitelist de vendedores:** `amazonbr`, `carrefour`, `casasbahia`, `magazineluiza`,
  `mercadolivre` — qualquer outro valor rejeita a linha (barreira anti-injeção).
- **Faixa de preço:** R$ 0,05 a R$ 10.000,00; promoção nunca acima do preço cheio;
  moeda obrigatoriamente BRL.
- **EAN:** GTIN-13 (13 dígitos + dígito verificador módulo 10); vazio → `None`.
- **Cadastro de produto:** a primeira linha de cada SKU define nome/embalagem/EAN; linhas
  seguintes divergentes rejeitam (o cadastro não é sobrescrito).
- **Datas:** dia/mês primeiro, fallback mês/dia; futuro (com folga de 1 dia) rejeita;
  tudo normalizado para `America/Sao_Paulo`.
- **Segurança:** `sku`/`produto` com início de fórmula (`=`, `+`, `@`) rejeitam; persistência
  100% via ORM; texto do CSV nunca é executado nem interpretado como SQL/fórmula.

Ver [premissas 12–19 do README](../README.md#premissas-assumidas-onde-o-enunciado-era-ambíguo)
para a versão completa das decisões.
