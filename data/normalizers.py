"""Normalização de campos — PENDENTE DE IMPLEMENTAÇÃO.

Responsabilidade exclusiva de quem trata o CSV. Este é o ponto principal de
entrada do tratamento: o serviço de importação chama ``processar_linha`` para
cada linha e persiste o resultado. Se a linha não puder ser aproveitada,
levante ``LinhaRejeitada`` com os motivos — o sistema grava a quarentena.

Contrato de ``processar_linha``:

    processar_linha(bruta: dict[str, str]) -> LinhaNormalizada

    1. Valida a linha (sugestão: chame ``validators.validar_linha``).
    2. Se houver motivos: ``raise LinhaRejeitada(motivos)``.
    3. Caso contrário, converta os campos para os tipos finais e retorne
       ``LinhaNormalizada`` preenchido. Todos os valores já vêm no formato
       em que serão gravados no banco — o resto do sistema NÃO reinterpreta.

Sugestão de formatação determinística (regex + stdlib; sem IA):
    - preco/preco_promocional -> Decimal com ``.`` como separador decimal;
      aceitar "R$ 1.234,56" (pt-BR), "1234.56" (en-US), "1.234,56";
      rejeitar texto ("Sob consulta") via validação.
    - coletado_em -> datetime consciente de fuso (``datetime`` com tz).
      Formatos presentes no arquivo: ISO com offset ("2025-03-16T09:44:00-03:00"),
      ISO com "Z" ("2025-03-10 12:09:00Z"), "DD/MM/YYYY HH:MM",
      "MM/DD/YYYY HH:MM", "YYYY-MM-DD" (sem hora). Sem fuso -> assuma
      America/Sao_Paulo (USE_TZ=True; o serviço corrige naive datetimes
      como rede de segurança, mas o contrato é retornar tz-aware).
    - sku -> strip; decidir caixa (ex.: manter "SKU-1011" e aplicar
      ``.upper()``) e registrar a decisão no README.
    - ean -> só dígitos, GTIN-13 válido ou ``None`` (decisão sobre EAN
      ausente é sua; se ``None``, o serviço mantém o EAN já cadastrado no
      produto — conflito de EAN entre linhas do mesmo SKU é rejeitado pelo
      serviço com o motivo "EAN divergente...").
    - produto -> título padrão do caso (ex.: "cafeteira elétrica" ->
      "Cafeteira Elétrica"), removendo espaços extras.
    - vendedor -> ver ``normalizar_vendedor`` abaixo.
    - uf -> sigla maiúscula de 2 letras (normalização, não rejeição).
    - estoque -> int; decida o destino de "esgotado" (0? None? rejeição?)
      e de valores negativos; registre no README.
    - embalagem -> int >= 1 (padrão 1).

Contrato de ``normalizar_vendedor``:

    normalizar_vendedor(nome: str) -> str

    - Devolve a CHAVE de identidade do vendedor, usada pelo banco para
      deduplicar (constraint de unicidade) e pelo filtro
      ``GET /api/precos/?vendedor=``.
    - Deve ser determinística, independente de caixa/acentos/espaços:
      "Carrefour", "CARREFOUR" e " carrefour " -> mesma chave;
      "Casas Bahia" e "casasbahia" -> mesma chave.
    - O valor exibido (``Vendedor.nome``) vem de
      ``LinhaNormalizada.vendedor_nome`` (nome "bonito" visto na linha);
      a chave vem daqui.

Observação: enquanto estas funções levantarem ``NotImplementedError``,
nenhuma importação conseguirá processar linhas (elas cairão para
``status=falhou``) — implemente-as para o sistema funcionar de ponta a ponta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .exceptions import LinhaRejeitada


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
    raise NotImplementedError(
        'data.normalizers.processar_linha não implementado: o tratamento do '
        'CSV é de responsabilidade de quem trata os dados '
        '(ver data/normalizers.py).'
    )


def normalizar_vendedor(nome: str) -> str:
    """Devolve a chave de identidade (deduplicação) de um vendedor. Ver docstring do módulo."""
    raise NotImplementedError(
        'data.normalizers.normalizar_vendedor não implementado: o tratamento '
        'do CSV é de responsabilidade de quem trata os dados '
        '(ver data/normalizers.py).'
    )