"""Normalização da linha do CSV: valida, converte e devolve ``LinhaNormalizada``.

Fluxo de ``processar_linha``:

    1. valida a linha com ``validators.validar_linha``;
    2. se houver motivos → ``raise LinhaRejeitada(motivos)`` (quarentena);
    3. caso contrário, converte os campos para os tipos finais — todos os
       valores já chegam no formato em que serão gravados no banco; o resto
       do sistema NÃO reinterpreta nada.

Conversões (implementadas em ``data/validators.py`` e reaproveitadas aqui,
para validação e conversão nunca discordarem):

- ``preco``/``preco_promocional`` → ``Decimal`` de 2 casas, aceitando
  pt-BR (``R$ 1.234,56``, ``23,74``), en-US (``1234.56``) e só-ponto em
  grupos de 3 (``1.299`` = 1299). Texto não numérico ("Sob consulta") é
  rejeitado pela validação antes da conversão.
- ``coletado_em`` → datetime consciente de fuso, sempre em
  America/Sao_Paulo (datas com offset/``Z`` preservam o instante; as sem
  fuso são interpretadas em São Paulo).
- ``sku`` → ``strip()``; a caixa original é mantida (SKU é identificador
  sensível à caixa — decisão registrada no README).
- ``ean`` → 13 dígitos GTIN-13 válido; vazio → ``None`` (o serviço mantém o
  EAN já cadastrado no produto).
- ``produto`` → título padrão (caixa de título, espaços colapsados;
  tokens com dígitos preservados: ``500g``, ``15"``). Ex.:
  ``"cafeteira elétrica"`` → ``"Cafeteira Elétrica"``.
- ``vendedor`` → nome "bonito" da linha (espaços colapsados) + chave de
  identidade via ``normalizar_vendedor``.
- ``uf`` → sigla maiúscula de 2 letras (caixa é normalização; sigla fora
  dos 27 estados é rejeição).
- ``estoque`` → ``"esgotado"`` vira ``0``; vazio vira ``None``
  (desconhecido); negativo/não numérico é rejeitado pela validação.
- ``embalagem`` → inteiro ≥ 1; vazio usa o padrão 1.

Contrato de ``normalizar_vendedor``:

    normalizar_vendedor(nome: str) -> str

    Devolve a CHAVE de identidade do vendedor, usada pelo banco para
    deduplicar (constraint de unicidade de ``Vendedor.nome_normalizado``),
    pelo filtro ``GET /api/precos/?vendedor=`` e pela whitelist de
    concorrentes aceitos da validação. É determinística e independente de
    caixa, acentos e espaços: "Carrefour"/"CARREFOUR"/" carrefour " →
    ``carrefour``; "Casas Bahia"/"casasbahia" → ``casasbahia``.

Segurança: campos de texto com início de fórmula (``=``, ``+``, ``@``) e
vendedores fora da whitelist são rejeitados na validação — nada do CSV é
interpretado como fórmula/SQL pelo sistema.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .exceptions import LinhaRejeitada
from .validators import (
    data_em_datetime,
    estoque_em_inteiro,
    inteiro,
    preco_em_decimal,
    validar_linha,
)

_RE_ESPACOS = re.compile(r'\s+')

#: Conectores que permanecem minúsculos no título (fora da 1ª palavra).
CONECTORES = frozenset(
    {'a', 'o', 'ao', 'à', 'as', 'os', 'e', 'em', 'de', 'da', 'do', 'das', 'dos', 'com', 'por', 'para'}
)


@dataclass(frozen=True, slots=True)
class LinhaNormalizada:
    """Linha do CSV pronta para persistência (após validação e normalização)."""

    sku: str
    ean: str | None
    produto_nome: str
    embalagem: int
    vendedor_nome: str
    vendedor_chave: str
    uf: str
    preco: Decimal
    preco_promocional: Decimal | None
    moeda: str
    estoque: int | None
    coletado_em: datetime
    dados_originais: dict[str, str] = field(default_factory=dict)


def processar_linha(bruta: dict[str, str]) -> LinhaNormalizada:
    """Valida e normaliza uma linha do CSV. Ver docstring do módulo.

    Levanta ``LinhaRejeitada`` quando a linha não puder ser aproveitada.
    """
    motivos = validar_linha(bruta)
    if motivos:
        raise LinhaRejeitada(motivos)

    sku = _texto(bruta, 'sku')
    ean = _texto(bruta, 'ean') or None
    embalagem = inteiro(_texto(bruta, 'embalagem')) or 1
    vendedor_nome = _texto(bruta, 'vendedor')
    texto_promo = _texto(bruta, 'preco_promocional')

    return LinhaNormalizada(
        sku=sku,
        ean=ean,
        produto_nome=titulo(_texto(bruta, 'produto')),
        embalagem=embalagem,
        vendedor_nome=' '.join(vendedor_nome.split()),
        vendedor_chave=normalizar_vendedor(vendedor_nome),
        uf=_texto(bruta, 'uf').upper(),
        preco=preco_em_decimal(_texto(bruta, 'preco')),
        preco_promocional=preco_em_decimal(texto_promo) if texto_promo else None,
        moeda=_texto(bruta, 'moeda').upper(),
        estoque=estoque_em_inteiro(_texto(bruta, 'estoque')),
        coletado_em=data_em_datetime(_texto(bruta, 'coletado_em')),
        dados_originais=dict(bruta),
    )


def normalizar_vendedor(nome: str) -> str:
    """Devolve a chave de identidade (deduplicação) de um vendedor. Ver docstring do módulo."""
    texto = unicodedata.normalize('NFD', str(nome or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return _RE_ESPACOS.sub('', texto.casefold())


def titulo(texto: str) -> str:
    """Título padrão do produto: caixa de título com espaços colapsados.

    Regras por palavra: tokens com dígitos ficam como estão (``500g``,
    ``15"``); conectores portugueses minúsculos (``de``, ``em``...) ficam
    minúsculos; palavras já com caixa mista/alta são preservadas; só
    palavras inteiramente minúsculas ganham caixa de título. A 1ª palavra
    sempre termina capitalizada. Ex.: ``"cafeteira elétrica"`` →
    ``"Cafeteira Elétrica"``, ``"óleo de soja 900ml"`` →
    ``"Óleo de Soja 900ml"``.
    """
    palavras = str(texto).split()
    return ' '.join(_palavra_titulo(p, primeira=i == 0) for i, p in enumerate(palavras))


def _palavra_titulo(palavra: str, primeira: bool) -> str:
    if any(c.isdigit() for c in palavra):
        return palavra
    caixa_baixa = palavra.casefold()
    if not primeira and caixa_baixa in CONECTORES:
        return caixa_baixa
    if any(c.isupper() for c in palavra):
        return palavra
    return palavra.capitalize()


def nomes_coincidem(a: str, b: str) -> bool:
    """Compara nomes de produto ignorando caixa e espaços extras.

    Usado pela importação para detectar nome divergente do cadastro (a
    primeira linha define o nome; divergência posterior rejeita a linha).
    """
    return ' '.join(str(a).split()).casefold() == ' '.join(str(b).split()).casefold()


def _texto(bruta: dict[str, str], campo: str) -> str:
    return str(bruta.get(campo) or '').strip()
