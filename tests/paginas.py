"""Cópias reais do site, salvas compactadas em tests/paginas/ (baixadas em 2026-09-21; o histórico em 2026-10-28)."""
import functools
import gzip
import json
from pathlib import Path

PASTA = Path(__file__).resolve().parent / 'paginas'


@functools.cache
def texto(nome):
    with gzip.open(PASTA / nome, 'rt', encoding='utf-8') as arq:
        return arq.read()


def lista():
    return texto('lista.html.gz')


def conta(rid):
    return texto(f'conta_{rid}.html.gz')


def catalogo():
    return json.loads(texto('catalogo.json.gz'))


def historico(nome):
    """O histórico de vendas buscado pelo nome (q=nome)."""
    return texto(f'historico_{nome}.html.gz')


def venda(numero):
    """A página de uma conta vendida (/pw187/vendida/{numero})."""
    return texto(f'vendida_{numero}.html.gz')
