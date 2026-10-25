"""Valor de uma conta pela tabela de valores do usuário.

Regras (docs/superpowers/specs/2026-09-21-mercado-pw-design.md, seção 5):
- cada linha da tabela vale por unidade, em kk (1 bi = 1.000 kk);
- com várias faixas do mesmo item, vale a de maior refino_min que o item atinge;
- itens empilháveis contam qtd x valor, e cada pedra engastada conta uma unidade;
- o códice (coleção de visuais) e a recompra não são itens da conta e ficam de fora;
- uma linha de grupo (grupo_id) vale para cada item do grupo, com as mesmas faixas. O valor do próprio
  item vem antes: o do grupo só vale se nenhuma faixa do item serve. Com o item em vários grupos, vale
  o grupo que dá mais.
"""
from collections import defaultdict

KK_POR_BI = 1000
SECOES_FORA = frozenset({'codice', 'recompra'})


def kk_para_rs(kk, rs_por_bi):
    return kk / KK_POR_BI * rs_por_bi


def lucro(valor_kk, preco_tcc, rs_por_bi, rs_por_tcc):
    """(valor_rs, preco_rs, lucro_rs, lucro_pct). lucro_pct é o lucro sobre o valor estimado."""
    valor_rs = kk_para_rs(valor_kk, rs_por_bi)
    preco_rs = preco_tcc * rs_por_tcc
    lucro_rs = valor_rs - preco_rs
    return valor_rs, preco_rs, lucro_rs, (lucro_rs / valor_rs if valor_rs > 0 else 0.0)


class Tabela:
    """Linhas da tabela de valores indexadas por item_id e, para as ainda não vinculadas, por nome.

    grupos: {grupo_id: [item_ids]}, para as linhas de grupo; a de um grupo que não existe mais não vale.
    """

    def __init__(self, linhas, grupos=None):
        self.por_id = defaultdict(list)
        self.por_nome = defaultdict(list)
        self.por_grupo = defaultdict(lambda: defaultdict(list))  # item_id -> grupo_id -> faixas
        for linha in linhas:
            if linha.get('grupo_id') is not None:
                for item_id in (grupos or {}).get(linha['grupo_id'], ()):
                    self.por_grupo[item_id][linha['grupo_id']].append(linha)
            elif linha['item_id'] is not None:
                self.por_id[linha['item_id']].append(linha)
            else:
                self.por_nome[linha['nome_norm']].append(linha)
        for faixas in (*self.por_id.values(), *self.por_nome.values(),
                       *(f for g in self.por_grupo.values() for f in g.values())):
            faixas.sort(key=lambda l: -l['refino_min'])

    def __bool__(self):
        return bool(self.por_id or self.por_nome or self.por_grupo)

    def linha_para(self, item_id, nome_norm, refino):
        faixas = self.por_id.get(item_id) or self.por_nome.get(nome_norm) or ()
        if (linha := next((l for l in faixas if l['refino_min'] <= refino), None)) is not None:
            return linha
        do_grupo = [next((l for l in f if l['refino_min'] <= refino), None)
                    for f in self.por_grupo.get(item_id, {}).values()]
        return max((l for l in do_grupo if l is not None), key=lambda l: l['valor_kk'], default=None)


def avaliar(itens, tabela):
    """(valor_kk, detalhes) de uma conta.

    itens: dicts/Rows com secao, item_id, nome_norm, nome, refino e qtd.
    detalhes: uma entrada por linha da tabela usada, da que mais vale para a que menos vale.
    """
    total = 0.0
    por_linha = {}
    for it in itens:
        if it['secao'] in SECOES_FORA:
            continue
        linha = tabela.linha_para(it['item_id'], it['nome_norm'], it['refino'])
        if linha is None:
            continue
        subtotal = linha['valor_kk'] * it['qtd']
        total += subtotal
        d = por_linha.setdefault(linha['id'], {
            'valor_id': linha['id'], 'item_id': linha['item_id'] or it['item_id'], 'nome': linha['nome'],
            'grupo_id': linha.get('grupo_id'),
            'refino_min': linha['refino_min'], 'valor_kk': linha['valor_kk'],
            'qtd': 0, 'kk': 0.0, 'refino_max': 0, 'secoes': []})
        d['qtd'] += it['qtd']
        d['kk'] += subtotal
        d['refino_max'] = max(d['refino_max'], it['refino'])
        if it['secao'] not in d['secoes']:
            d['secoes'].append(it['secao'])
    return total, sorted(por_linha.values(), key=lambda d: -d['kk'])


def destaques(detalhes, limite=3):
    """Resumo curto dos itens que mais pesam, para a lista: [{nome, refino, qtd, item_id}]."""
    return [{'nome': d['nome'], 'refino': d['refino_max'], 'qtd': d['qtd'], 'item_id': d['item_id']}
            for d in detalhes[:limite]]
