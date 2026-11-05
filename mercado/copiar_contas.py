"""Leva as contas já lidas de um PC para outro, para o outro não ter que ler tudo de novo.

    py -m mercado.copiar_contas exportar           grava o contas-de-outro-pc.db com as contas lidas aqui
    py -m mercado.copiar_contas juntar [arquivo]   junta neste PC as contas do arquivo (com o programa fechado)

O "Juntar contas.bat" faz o juntar com o contas-de-outro-pc.db da pasta do programa.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

from .__main__ import ARQ_BANCO, PASTA, instancia_aberta
from .banco import Banco

ARQ_CONTAS = PASTA / 'contas-de-outro-pc.db'


def _n(numero):
    return f'{numero:,}'.replace(',', '.')


def exportar():
    if not ARQ_BANCO.exists():
        return 'Este PC ainda não tem contas lidas (falta o mercado.db).'
    banco = Banco(ARQ_BANCO)
    n = banco.exportar_contas(ARQ_CONTAS)
    banco.fechar()
    print(f'{_n(n)} contas lidas foram para o {ARQ_CONTAS.name} ({ARQ_CONTAS.stat().st_size / 1e6:.0f} MB).')
    print('No outro PC: ponha o arquivo na pasta do programa, feche o Mercado PW e abra o "Juntar contas.bat".')
    return None


def juntar(arquivo):
    if instancia_aberta():
        return 'O Mercado PW está aberto. Feche o programa e rode de novo.'
    if not arquivo.exists():
        return f'Não achei o {arquivo}. Ponha na pasta do programa o arquivo que veio do outro PC.'
    sem_lista = ('Este PC ainda não tem a lista de contas. Abra o Mercado PW, espere a lista aparecer, '
                 'feche e rode de novo.')
    if not ARQ_BANCO.exists():
        return sem_lista
    banco = Banco(ARQ_BANCO)
    try:
        if not banco.contagem()['ativas']:
            return sem_lista
        try:
            n = banco.juntar_contas(arquivo)
        except (ValueError, sqlite3.DatabaseError) as e:
            return f'Não consegui juntar as contas do {arquivo.name}: {e}'
        c = banco.contagem()
    finally:
        banco.fechar()
    print(f'Vieram {_n(n)} contas lidas do outro PC.')
    print(f'Das {_n(c["ativas"])} contas no ar, faltam ler {_n(c["ativas"] - c["lidas"])}. Pode abrir o Mercado PW.')
    return None


def main():
    p = argparse.ArgumentParser(prog='py -m mercado.copiar_contas', description=__doc__.splitlines()[0])
    acoes = p.add_subparsers(dest='acao', required=True)
    acoes.add_parser('exportar', help=f'grava o {ARQ_CONTAS.name} com as contas lidas neste PC')
    j = acoes.add_parser('juntar', help='junta neste PC as contas lidas em outro (com o programa fechado)')
    j.add_argument('arquivo', nargs='?', type=Path, default=ARQ_CONTAS)
    args = p.parse_args()
    erro = exportar() if args.acao == 'exportar' else juntar(args.arquivo)
    if erro:
        print(erro)
        sys.exit(1)


if __name__ == '__main__':
    main()
