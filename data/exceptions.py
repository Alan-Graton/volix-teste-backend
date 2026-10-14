"""Erros usados pelo contrato entre o pipeline de importação e o tratamento do CSV."""


class LinhaRejeitada(Exception):
    """Uma linha do CSV não pôde ser aproveitada e vai para a quarentena.

    Os motivos devem ser claros e específicos (ex.:
    ``["Preço ausente", "UF inválida: XX"]``), pois são expostos na API
    de quarentena sem nenhum processamento adicional.
    """

    def __init__(self, motivos):
        if isinstance(motivos, str):
            motivos = [motivos]
        self.motivos = [str(m) for m in motivos]
        if not self.motivos:
            raise ValueError('LinhaRejeitada exige ao menos um motivo.')
        super().__init__('; '.join(self.motivos))


class ArquivoInvalido(Exception):
    """O arquivo como um todo não pôde ser interpretado (ex.: cabeçalho inesperado).

    A importação inteira passa para ``status=falhou`` com a mensagem em ``erro``.
    """