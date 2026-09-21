"""Banco local (SQLite) do Mercado PW: anúncios, itens das contas, tabela de valores, buscas e avisos."""
import hashlib
import json
import sqlite3
import statistics
import threading
import zlib
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta

from . import valor
from .site import norm

ESQUEMA = """
CREATE TABLE IF NOT EXISTS anuncios (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL DEFAULT '', nome_norm TEXT NOT NULL DEFAULT '',
    classe TEXT NOT NULL DEFAULT '', ocupacao INTEGER NOT NULL DEFAULT 0,
    nivel INTEGER NOT NULL DEFAULT 0, ceu TEXT NOT NULL DEFAULT '', ceu_norm TEXT NOT NULL DEFAULT '',
    preco INTEGER NOT NULL,
    primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL,
    nova INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1,
    itens_lidos_em TEXT, preco_lido INTEGER,
    valor_kk REAL, destaques TEXT
);
CREATE INDEX IF NOT EXISTS anuncios_ativo ON anuncios(ativo, preco);

CREATE TABLE IF NOT EXISTS itens (
    anuncio_id INTEGER NOT NULL, ordem INTEGER NOT NULL, secao TEXT NOT NULL,
    item_id INTEGER, nome TEXT NOT NULL, nome_norm TEXT NOT NULL,
    refino INTEGER NOT NULL DEFAULT 0, qtd INTEGER NOT NULL DEFAULT 1,
    efeito TEXT NOT NULL DEFAULT '', tooltip_id TEXT
);
CREATE INDEX IF NOT EXISTS itens_anuncio ON itens(anuncio_id);
CREATE INDEX IF NOT EXISTS itens_item ON itens(item_id);
CREATE INDEX IF NOT EXISTS itens_nome ON itens(nome_norm);

CREATE TABLE IF NOT EXISTS tooltips (id TEXT PRIMARY KEY, dados BLOB NOT NULL);

CREATE TABLE IF NOT EXISTS conhecidos (
    item_id INTEGER PRIMARY KEY, nome TEXT NOT NULL, nome_norm TEXT NOT NULL,
    tipo TEXT NOT NULL, efeito TEXT NOT NULL DEFAULT '', no_catalogo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS conhecidos_nome ON conhecidos(nome_norm);

CREATE TABLE IF NOT EXISTS valores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, nome TEXT NOT NULL, nome_norm TEXT NOT NULL,
    refino_min INTEGER NOT NULL DEFAULT 0, valor_kk REAL NOT NULL,
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buscas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, filtros TEXT NOT NULL,
    avisar INTEGER NOT NULL DEFAULT 1, lucro_min_rs REAL, lucro_min_pct REAL,
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, busca_id INTEGER NOT NULL, anuncio_id INTEGER NOT NULL,
    preco INTEGER NOT NULL, lucro_rs REAL, motivo TEXT NOT NULL DEFAULT '', quando TEXT NOT NULL,
    UNIQUE (busca_id, anuncio_id, preco)
);

CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""

PADROES = {
    'intervalo_s': 60, 'pausa_s': 2, 'rs_por_bi': 500.0, 'rs_por_tcc': 1.0,
    'aviso_windows': True, 'aviso_bipes': True, 'aviso_navegador': False,
    'telegram_token': '', 'telegram_chat': '', 'discord_webhook': '',
    'largura_filtros': 27, 'largura_detalhes': 33, 'detalhes_recolhidos': False,
}
LIMITES = {'intervalo_s': (30, 3600), 'pausa_s': (1, 60), 'rs_por_bi': (0.01, 10_000_000),
           'rs_por_tcc': (0.01, 100_000), 'largura_filtros': (15, 45), 'largura_detalhes': (20, 50)}

# Campo "onde" das condições de item -> seções do banco (None = qualquer lugar da conta)
ONDE = {'equipado': ('equipado',), 'mochila': ('inventario',), 'banco': ('banco',),
        'cartas': ('cartas',), 'engastada': ('engastada',), 'mascotes': ('mascotes',)}
_FORA = ','.join(f"'{s}'" for s in sorted(valor.SECOES_FORA))

ORDENS = {
    'lucro_rs': 'lucro_rs IS NULL, lucro_rs DESC, a.preco',
    'lucro_pct': 'lucro_pct IS NULL, lucro_pct DESC, a.preco',
    'preco': 'a.preco, a.id',
    'valor': 'a.valor_kk IS NULL, a.valor_kk DESC, a.preco',
    'nivel': 'a.nivel DESC, a.preco',
    'novas': 'a.primeiro_visto DESC, a.preco',
}


def agora():
    return datetime.now().isoformat(timespec='seconds')


def _numero(v):
    if v is None or isinstance(v, bool) or v == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except ValueError:
        return None


def _marcadores(n):
    return ','.join('?' * n)


class Banco:
    def __init__(self, caminho):
        self.caminho = str(caminho)
        self._local = threading.local()
        self._escrita = threading.Lock()  # o SQLite aceita um escritor por vez
        with self._escrita:
            self.con.executescript(ESQUEMA)

    @property
    def con(self):
        """Uma conexão por thread (o servidor atende cada pedido numa thread)."""
        con = getattr(self._local, 'con', None)
        if con is None:
            con = sqlite3.connect(self.caminho, timeout=15, isolation_level=None, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=NORMAL')
            self._local.con = con
        return con

    @contextmanager
    def _transacao(self):
        with self._escrita:
            con = self.con
            con.execute('BEGIN IMMEDIATE')
            try:
                yield con
            except BaseException:
                con.execute('ROLLBACK')
                raise
            con.execute('COMMIT')

    def fechar(self):
        con = getattr(self._local, 'con', None)
        if con is not None:
            con.close()
            self._local.con = None

    # -------------------------------------------------------------- configuração

    def config(self):
        cfg = dict(PADROES)
        for r in self.con.execute('SELECT chave, valor FROM config'):
            if r['chave'] in PADROES:
                cfg[r['chave']] = json.loads(r['valor'])
        return cfg

    def salvar_config(self, mudancas):
        limpo = {}
        for chave, v in (mudancas or {}).items():
            padrao = PADROES.get(chave)
            if padrao is None:
                continue
            if isinstance(padrao, bool):
                v = bool(v)
            elif isinstance(padrao, (int, float)):
                v = _numero(v)
                if v is None:
                    continue
                lo, hi = LIMITES.get(chave, (float('-inf'), float('inf')))
                v = min(max(v, lo), hi)
                v = int(round(v)) if isinstance(padrao, int) else round(v, 2)
            else:
                v = str(v or '').strip()
            limpo[chave] = v
        with self._transacao() as con:
            con.executemany('INSERT INTO config(chave, valor) VALUES (?, ?) '
                            'ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor',
                            [(k, json.dumps(v)) for k, v in limpo.items()])
        return self.config()

    def meta(self, chave, padrao=None):
        r = self.con.execute('SELECT valor FROM config WHERE chave = ?', ('_' + chave,)).fetchone()
        return json.loads(r['valor']) if r else padrao

    def salvar_meta(self, chave, v):
        with self._transacao() as con:
            con.execute('INSERT INTO config(chave, valor) VALUES (?, ?) '
                        'ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor', ('_' + chave, json.dumps(v)))

    # -------------------------------------------------------------- anúncios

    def atualizar_lista(self, anuncios, quando=None):
        """Grava a lista lida do site e devolve o que mudou.

        Na primeira lista de um banco novo nada conta como novo: é a base.
        """
        quando = quando or agora()
        novos, baixaram, reativados = [], [], []
        with self._transacao() as con:
            antes = {r['id']: r for r in con.execute('SELECT id, preco, ativo FROM anuncios')}
            primeira = not antes
            for a in anuncios.values():
                campos = (a.nome, norm(a.nome), a.classe, a.ocupacao, a.nivel, a.ceu, norm(a.ceu), a.preco, quando)
                r = antes.get(a.id)
                if r is None:
                    con.execute('INSERT INTO anuncios (nome, nome_norm, classe, ocupacao, nivel, ceu, ceu_norm, '
                                'preco, ultimo_visto, id, primeiro_visto, nova) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                (*campos, a.id, quando, 0 if primeira else 1))
                    if not primeira:
                        novos.append(a.id)
                    continue
                con.execute('UPDATE anuncios SET nome=?, nome_norm=?, classe=?, ocupacao=?, nivel=?, ceu=?, '
                            'ceu_norm=?, preco=?, ultimo_visto=?, ativo=1 WHERE id=?', (*campos, a.id))
                if not r['ativo']:
                    con.execute('UPDATE anuncios SET nova=1, primeiro_visto=?, itens_lidos_em=NULL, '
                                'preco_lido=NULL, valor_kk=NULL, destaques=NULL WHERE id=?', (quando, a.id))
                    reativados.append(a.id)
                elif a.preco < r['preco']:
                    baixaram.append((a.id, r['preco'], a.preco))
            sumiram = [rid for rid, r in antes.items() if r['ativo'] and rid not in anuncios]
            con.executemany('UPDATE anuncios SET ativo=0 WHERE id=?', [(rid,) for rid in sumiram])
        return {'primeira': primeira, 'novos': novos, 'baixaram': baixaram,
                'reativados': reativados, 'removidos': len(sumiram)}

    def anuncio(self, anuncio_id):
        r = self.con.execute('SELECT * FROM anuncios WHERE id = ?', (anuncio_id,)).fetchone()
        return dict(r) if r else None

    def contas_para_ler(self):
        """Anúncios ativos sem itens lidos (ou lidos com outro preço), dos mais baratos aos mais caros."""
        return [dict(r) for r in self.con.execute(
            'SELECT id, preco FROM anuncios WHERE ativo = 1 AND '
            '(itens_lidos_em IS NULL OR preco_lido IS NULL OR preco_lido != preco) ORDER BY preco, id')]

    def contagem(self):
        r = self.con.execute(
            'SELECT COUNT(*) AS ativas, '
            'SUM(itens_lidos_em IS NOT NULL AND preco_lido = preco) AS lidas FROM anuncios WHERE ativo = 1').fetchone()
        classes = [dict(c) for c in self.con.execute(
            "SELECT classe, MIN(ocupacao) AS ocupacao, COUNT(*) AS n FROM anuncios "
            "WHERE ativo = 1 AND classe != '' GROUP BY classe ORDER BY n DESC")]
        ceus = [c['ceu'] for c in self.con.execute(
            "SELECT DISTINCT ceu FROM anuncios WHERE ativo = 1 AND ceu != '' ORDER BY ceu")]
        return {'ativas': r['ativas'] or 0, 'lidas': r['lidas'] or 0, 'classes': classes, 'ceus': ceus}

    # -------------------------------------------------------------- itens das contas

    def gravar_itens(self, anuncio_id, itens, preco, quando=None):
        """Substitui os itens de uma conta e recalcula o valor dela."""
        quando = quando or agora()
        linhas, tooltips, conhecidos = [], {}, {}
        for ordem, it in enumerate(itens):
            tid = None
            if it.tooltip:
                bruto = json.dumps(it.tooltip, ensure_ascii=False, separators=(',', ':')).encode()
                tid = hashlib.sha1(bruto).hexdigest()[:20]
                tooltips[tid] = zlib.compress(bruto, 6)
            nome_norm = norm(it.nome)
            linhas.append((anuncio_id, ordem, it.secao, it.item_id, it.nome, nome_norm,
                           it.refino, it.qtd, it.efeito, tid))
            if it.item_id is not None and it.item_id not in conhecidos:
                tipo = 'pedra' if it.secao == 'engastada' else 'item'
                conhecidos[it.item_id] = (it.item_id, it.nome, nome_norm, tipo, it.efeito)
        with self._transacao() as con:
            con.execute('DELETE FROM itens WHERE anuncio_id = ?', (anuncio_id,))
            con.executemany('INSERT INTO itens (anuncio_id, ordem, secao, item_id, nome, nome_norm, refino, qtd, '
                            'efeito, tooltip_id) VALUES (?,?,?,?,?,?,?,?,?,?)', linhas)
            con.executemany('INSERT OR IGNORE INTO tooltips (id, dados) VALUES (?, ?)', tooltips.items())
            con.executemany('INSERT OR IGNORE INTO conhecidos (item_id, nome, nome_norm, tipo, efeito) '
                            'VALUES (?,?,?,?,?)', conhecidos.values())
            pendentes = {r['nome_norm'] for r in con.execute('SELECT nome_norm FROM valores WHERE item_id IS NULL')}
            for item_id, _, nome_norm, _, _ in conhecidos.values():
                if nome_norm in pendentes:  # valor cadastrado só pelo nome ganha o item_id
                    con.execute('UPDATE valores SET item_id = ? WHERE item_id IS NULL AND nome_norm = ?',
                                (item_id, nome_norm))
                    pendentes.discard(nome_norm)
            con.execute('UPDATE anuncios SET itens_lidos_em = ?, preco_lido = ? WHERE id = ?',
                        (quando, preco, anuncio_id))
        self.recalcular([anuncio_id])

    def gravar_catalogo(self, itens):
        with self._transacao() as con:
            con.executemany(
                'INSERT INTO conhecidos (item_id, nome, nome_norm, tipo, no_catalogo) VALUES (?,?,?,?,1) '
                'ON CONFLICT(item_id) DO UPDATE SET nome = excluded.nome, nome_norm = excluded.nome_norm, '
                'tipo = excluded.tipo, no_catalogo = 1',
                [(it['item_id'], it['nome'], norm(it['nome']), it['grupo'] or 'equipamento') for it in itens])
        self.salvar_meta('catalogo_em', agora())

    def ids_no_catalogo(self):
        return {r[0] for r in self.con.execute('SELECT item_id FROM conhecidos WHERE no_catalogo = 1')}

    def ids_valorizados(self):
        """item_ids da tabela de valores e das condições de item das buscas salvas."""
        ids = {r[0] for r in self.con.execute('SELECT DISTINCT item_id FROM valores WHERE item_id IS NOT NULL')}
        for b in self.buscas():
            ids.update(int(c['item_id']) for c in b['filtros'].get('itens') or () if str(c.get('item_id') or '').isdigit())
        return ids

    def sugestoes(self, texto, limite=12):
        """Itens conhecidos (catálogo do site + vistos nas contas) cujo nome contém o texto."""
        q = norm(texto)
        if len(q) < 2:
            return []
        linhas = self.con.execute('SELECT * FROM conhecidos WHERE nome_norm LIKE ? LIMIT 400',
                                  (f'%{q}%',)).fetchall()
        contagem = self._contas_com([r['item_id'] for r in linhas])
        itens = []
        for r in linhas:
            contas, unidades = contagem.get(r['item_id'], (0, 0))
            itens.append({'item_id': r['item_id'], 'nome': r['nome'], 'tipo': r['tipo'], 'efeito': r['efeito'],
                          'no_catalogo': bool(r['no_catalogo']), 'contas': contas, 'unidades': unidades})
        itens.sort(key=lambda it: (not norm(it['nome']).startswith(q), -it['contas'], len(it['nome'])))
        return itens[:limite]

    def _contas_com(self, item_ids, refino_min=0):
        """{item_id: (contas ativas que têm, unidades somadas)}."""
        if not item_ids:
            return {}
        return {r[0]: (r[1], r[2]) for r in self.con.execute(
            f'SELECT i.item_id, COUNT(DISTINCT i.anuncio_id), SUM(i.qtd) FROM itens i JOIN anuncios a ON a.id = i.anuncio_id '
            f'WHERE a.ativo = 1 AND i.secao NOT IN ({_FORA}) AND i.refino >= ? '
            f'AND i.item_id IN ({_marcadores(len(item_ids))}) GROUP BY i.item_id', (refino_min, *item_ids))}

    def conta(self, anuncio_id):
        """Tudo o que o painel de detalhes mostra de uma conta."""
        a = self.anuncio(anuncio_id)
        if a is None:
            return None
        itens = self.con.execute('SELECT secao, item_id, nome, nome_norm, refino, qtd, efeito, tooltip_id '
                                 'FROM itens WHERE anuncio_id = ? ORDER BY ordem', (anuncio_id,)).fetchall()
        ids = sorted({r['tooltip_id'] for r in itens if r['tooltip_id']})
        tooltips = {}
        for i in range(0, len(ids), 500):
            parte = ids[i:i + 500]
            for r in self.con.execute(f'SELECT id, dados FROM tooltips WHERE id IN ({_marcadores(len(parte))})', parte):
                tooltips[r['id']] = json.loads(zlib.decompress(r['dados']))
        cfg = self.config()
        lida = a['itens_lidos_em'] is not None
        kk, detalhes = valor.avaliar(itens, self._tabela()) if lida else (None, [])
        return {
            'anuncio': self._publico(a, cfg, kk),
            'itens': [{'secao': r['secao'], 'item_id': r['item_id'], 'nome': r['nome'], 'refino': r['refino'],
                       'qtd': r['qtd'], 'efeito': r['efeito'], 'tooltip': r['tooltip_id']} for r in itens],
            'tooltips': tooltips,
            'detalhes': [{**d, 'rs': valor.kk_para_rs(d['kk'], cfg['rs_por_bi'])} for d in detalhes],
        }

    def limpar_antigos(self, dias=7):
        """Apaga os itens de anúncios que saíram do ar há mais de `dias` dias."""
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec='seconds')
        with self._transacao() as con:
            velhos = [r[0] for r in con.execute(
                'SELECT id FROM anuncios WHERE ativo = 0 AND ultimo_visto < ? AND itens_lidos_em IS NOT NULL',
                (limite,))]
            con.executemany('DELETE FROM itens WHERE anuncio_id = ?', [(i,) for i in velhos])
            con.executemany('UPDATE anuncios SET itens_lidos_em = NULL, preco_lido = NULL, valor_kk = NULL, '
                            'destaques = NULL WHERE id = ?', [(i,) for i in velhos])
            if velhos:
                con.execute('DELETE FROM tooltips WHERE id NOT IN '
                            '(SELECT DISTINCT tooltip_id FROM itens WHERE tooltip_id IS NOT NULL)')
        return len(velhos)

    # -------------------------------------------------------------- valor das contas

    def _tabela(self):
        return valor.Tabela([dict(r) for r in self.con.execute(
            'SELECT id, item_id, nome, nome_norm, refino_min, valor_kk FROM valores')])

    def recalcular(self, ids=None):
        """Recalcula valor e destaques das contas lidas (todas, ou só as de `ids`)."""
        tabela = self._tabela()
        if ids is None:
            alvo = [r[0] for r in self.con.execute('SELECT id FROM anuncios WHERE itens_lidos_em IS NOT NULL')]
        else:
            alvo = [r[0] for r in self.con.execute(
                f'SELECT id FROM anuncios WHERE itens_lidos_em IS NOT NULL AND id IN ({_marcadores(len(ids))})',
                list(ids))] if ids else []
        por_conta = defaultdict(list)
        if tabela and alvo:
            conds, params = [], []
            if tabela.por_id:
                conds.append(f'item_id IN ({_marcadores(len(tabela.por_id))})')
                params += list(tabela.por_id)
            if tabela.por_nome:
                conds.append(f'nome_norm IN ({_marcadores(len(tabela.por_nome))})')
                params += list(tabela.por_nome)
            sql = f'SELECT anuncio_id, secao, item_id, nome, nome_norm, refino, qtd FROM itens WHERE ({" OR ".join(conds)})'
            if ids is not None:
                sql += f' AND anuncio_id IN ({_marcadores(len(alvo))})'
                params += alvo
            for r in self.con.execute(sql, params):
                por_conta[r['anuncio_id']].append(r)
        atualizacoes = []
        for rid in alvo:
            kk, detalhes = valor.avaliar(por_conta.get(rid, ()), tabela)
            atualizacoes.append((kk, json.dumps(valor.destaques(detalhes), ensure_ascii=False), rid))
        with self._transacao() as con:
            con.executemany('UPDATE anuncios SET valor_kk = ?, destaques = ? WHERE id = ?', atualizacoes)

    def _publico(self, r, cfg, valor_kk=None):
        """Anúncio no formato que a interface usa, com valor e lucro em R$."""
        kk = r['valor_kk'] if valor_kk is None else valor_kk
        lida = r['itens_lidos_em'] is not None
        dados = {'id': r['id'], 'nome': r['nome'], 'classe': r['classe'], 'ocupacao': r['ocupacao'],
                 'nivel': r['nivel'], 'ceu': r['ceu'], 'preco': r['preco'], 'ativo': bool(r['ativo']),
                 'nova': bool(r['nova']) and r['primeiro_visto'] >= _ha_24h(),
                 'primeiro_visto': r['primeiro_visto'], 'lida': lida,
                 'destaques': json.loads(r['destaques'] or '[]'),
                 'valor_kk': None, 'valor_rs': None, 'preco_rs': r['preco'] * cfg['rs_por_tcc'],
                 'lucro_rs': None, 'lucro_pct': None}
        if lida and kk is not None:
            valor_rs, preco_rs, lucro_rs, pct = valor.lucro(kk, r['preco'], cfg['rs_por_bi'], cfg['rs_por_tcc'])
            dados.update(valor_kk=kk, valor_rs=valor_rs, preco_rs=preco_rs)
            if kk > 0:  # sem nenhum item da tabela não há o que comparar com o preço
                dados.update(lucro_rs=lucro_rs, lucro_pct=pct)
        return dados

    # -------------------------------------------------------------- busca

    def buscar(self, filtros, ids_do_site=None):
        """Contas ativas que batem com os filtros, já com valor e lucro.

        ids_do_site(condicao) devolve os ids que a busca do site encontrou para uma
        condição de item (ou None se não der para usar o site). Esses ids incluem
        contas ainda não lidas, que voltam marcadas "a_confirmar".
        """
        f = filtros or {}
        cfg = self.config()
        p = {'bi': cfg['rs_por_bi'], 'tcc': cfg['rs_por_tcc'], 'kk_bi': float(valor.KK_POR_BI)}
        conds = ['a.ativo = 1']
        if f.get('ids') is not None:  # usado pelo coletor para conferir só as contas que acabou de ler
            conds.append(f'a.id IN ({",".join(str(int(i)) for i in f["ids"]) or "NULL"})')
        if nome := norm(f.get('nome')):
            conds.append('a.nome_norm LIKE :nome')
            p['nome'] = f'%{nome}%'
        classes = [str(c) for c in (f.get('classes') or []) if c]
        if classes:
            conds.append(f'a.classe IN ({",".join(f":c{i}" for i in range(len(classes)))})')
            p.update({f'c{i}': c for i, c in enumerate(classes)})
        for chave, op in (('preco_min', '>='), ('preco_max', '<=')):
            if (v := _numero(f.get(chave))) is not None:
                conds.append(f'a.preco {op} :{chave}')
                p[chave] = v
        if (v := _numero(f.get('nivel_min'))) is not None:
            conds.append('a.nivel >= :nivel_min')
            p['nivel_min'] = v
        if ceu := norm(f.get('ceu')):
            conds.append('a.ceu_norm LIKE :ceu')
            p['ceu'] = f'%{ceu}%'
        if f.get('so_novas'):
            conds.append('a.nova = 1 AND a.primeiro_visto >= :h24')
            p['h24'] = _ha_24h()
        base = list(conds)

        condicoes = [c for c in (f.get('itens') or []) if c and (c.get('item_id') or norm(c.get('nome')))]
        for n, cond in enumerate(condicoes):
            sub = self._sql_item(cond, n, p)
            site = ids_do_site(cond) if ids_do_site else None
            if site is None:
                conds.append(f'(a.itens_lidos_em IS NOT NULL AND a.id IN ({sub}))')
            else:
                lista = ','.join(str(int(i)) for i in site) or 'NULL'
                conds.append(f'((a.itens_lidos_em IS NOT NULL AND a.id IN ({sub})) '
                             f'OR (a.itens_lidos_em IS NULL AND a.id IN ({lista})))')
        lucro_sql = 'CASE WHEN a.valor_kk > 0 THEN a.valor_kk / :kk_bi * :bi - a.preco * :tcc END'
        if f.get('so_lucro'):
            conds.append(f'({lucro_sql}) > 0')
        ordem = ORDENS.get(f.get('ordem'), ORDENS['lucro_rs'])
        linhas = self.con.execute(
            f'SELECT a.*, {lucro_sql} AS lucro_rs, '
            f'CASE WHEN a.valor_kk > 0 THEN ({lucro_sql}) / (a.valor_kk / :kk_bi * :bi) END AS lucro_pct '
            f'FROM anuncios a WHERE {" AND ".join(conds)} ORDER BY {ordem}', p).fetchall()

        contas = []
        for r in linhas:
            conta = self._publico(r, cfg)
            conta['a_confirmar'] = bool(condicoes) and not conta['lida']
            contas.append(conta)
        precos = [c['preco'] for c in contas]
        nao_lidas = 0
        if condicoes or f.get('so_lucro'):
            fora = self.con.execute(f'SELECT COUNT(*) FROM anuncios a WHERE {" AND ".join(base)} '
                                    'AND a.itens_lidos_em IS NULL', p).fetchone()[0]
            nao_lidas = fora - sum(c['a_confirmar'] for c in contas)
        return {'contas': contas, 'batem': len(contas),
                'preco_min': min(precos) if precos else None,
                'preco_mediana': statistics.median(precos) if precos else None,
                'a_confirmar': sum(c['a_confirmar'] for c in contas), 'nao_lidas': max(0, nao_lidas)}

    @staticmethod
    def _sql_item(cond, n, p):
        """Subconsulta: contas lidas que têm o item da condição n (refino, quantidade e onde)."""
        if cond.get('item_id'):
            alvo = f'i.item_id = :i{n}_id'
            p[f'i{n}_id'] = int(cond['item_id'])
        else:
            alvo = f'i.nome_norm = :i{n}_nome'
            p[f'i{n}_nome'] = norm(cond.get('nome'))
        secoes = ONDE.get(cond.get('onde'))
        onde = (f'i.secao IN ({",".join(repr(s) for s in secoes)})' if secoes else f'i.secao NOT IN ({_FORA})')
        p[f'i{n}_ref'] = int(_numero(cond.get('refino_min')) or 0)
        p[f'i{n}_qtd'] = max(1, int(_numero(cond.get('qtd_min')) or 1))
        return (f'SELECT i.anuncio_id FROM itens i WHERE {alvo} AND i.refino >= :i{n}_ref AND {onde} '
                f'GROUP BY i.anuncio_id HAVING SUM(i.qtd) >= :i{n}_qtd')

    # -------------------------------------------------------------- tabela de valores

    def valores(self):
        cfg = self.config()
        linhas = self.con.execute(
            'SELECT v.*, c.tipo, c.efeito, c.no_catalogo FROM valores v LEFT JOIN conhecidos c ON c.item_id = v.item_id '
            'ORDER BY v.nome_norm, v.refino_min DESC').fetchall()
        saida = []
        for r in linhas:
            if r['item_id'] is not None:
                contas, unidades = self._contas_com([r['item_id']], r['refino_min']).get(r['item_id'], (0, 0))
            else:
                contas, unidades = self.con.execute(
                    f'SELECT COUNT(DISTINCT i.anuncio_id), COALESCE(SUM(i.qtd), 0) FROM itens i '
                    f'JOIN anuncios a ON a.id = i.anuncio_id '
                    f'WHERE a.ativo = 1 AND i.secao NOT IN ({_FORA}) AND i.nome_norm = ? AND i.refino >= ?',
                    (r['nome_norm'], r['refino_min'])).fetchone()
            saida.append({'id': r['id'], 'item_id': r['item_id'], 'nome': r['nome'], 'refino_min': r['refino_min'],
                          'valor_kk': r['valor_kk'], 'valor_rs': valor.kk_para_rs(r['valor_kk'], cfg['rs_por_bi']),
                          'tipo': r['tipo'] or 'item', 'efeito': r['efeito'] or '', 'no_catalogo': bool(r['no_catalogo']),
                          'visto': r['item_id'] is not None, 'contas': contas, 'unidades': unidades})
        return saida

    def salvar_valor(self, dados, valor_id=None):
        nome = str(dados.get('nome') or '').strip()
        if not nome:
            raise ValueError('Informe o item.')
        valor_kk = _numero(dados.get('valor_kk'))
        if valor_kk is None or valor_kk <= 0:
            raise ValueError('Informe um valor maior que zero.')
        refino_min = int(_numero(dados.get('refino_min')) or 0)
        if not 0 <= refino_min <= 20:
            raise ValueError('O refino mínimo vai de 0 a 20.')
        item_id = dados.get('item_id')
        item_id = int(item_id) if str(item_id or '').isdigit() else None
        nome_norm = norm(nome)
        if item_id is None:
            r = self.con.execute('SELECT item_id FROM conhecidos WHERE nome_norm = ? ORDER BY no_catalogo DESC LIMIT 1',
                                 (nome_norm,)).fetchone()
            item_id = r['item_id'] if r else None
        quando = agora()
        with self._transacao() as con:
            if item_id is not None:
                dup = con.execute('SELECT id FROM valores WHERE item_id = ? AND refino_min = ? AND id IS NOT ?',
                                  (item_id, refino_min, valor_id)).fetchone()
            else:
                dup = con.execute('SELECT id FROM valores WHERE item_id IS NULL AND nome_norm = ? AND refino_min = ? '
                                  'AND id IS NOT ?', (nome_norm, refino_min, valor_id)).fetchone()
            if dup:
                raise ValueError('Esse item já tem um valor para essa faixa de refino.')
            if valor_id:
                cur = con.execute('UPDATE valores SET item_id=?, nome=?, nome_norm=?, refino_min=?, valor_kk=?, '
                                  'atualizado_em=? WHERE id=?',
                                  (item_id, nome, nome_norm, refino_min, valor_kk, quando, valor_id))
                if cur.rowcount == 0:
                    raise KeyError(valor_id)
            else:
                valor_id = con.execute('INSERT INTO valores (item_id, nome, nome_norm, refino_min, valor_kk, criado_em, '
                                       'atualizado_em) VALUES (?,?,?,?,?,?,?)',
                                       (item_id, nome, nome_norm, refino_min, valor_kk, quando, quando)).lastrowid
        self.recalcular()
        return valor_id

    def apagar_valor(self, valor_id):
        with self._transacao() as con:
            con.execute('DELETE FROM valores WHERE id = ?', (valor_id,))
        self.recalcular()

    def resumo_valores(self):
        cfg = self.config()
        r = self.con.execute('SELECT COUNT(*) AS n, COUNT(DISTINCT COALESCE(item_id, nome_norm)) AS itens '
                             'FROM valores').fetchone()
        com_item = self.con.execute('SELECT COUNT(*) FROM anuncios WHERE ativo = 1 AND valor_kk > 0').fetchone()[0]
        ativas = self.con.execute('SELECT COUNT(*) FROM anuncios WHERE ativo = 1').fetchone()[0]
        melhor = self.con.execute(
            'SELECT *, valor_kk / :kk_bi * :bi - preco * :tcc AS lucro FROM anuncios '
            'WHERE ativo = 1 AND valor_kk > 0 ORDER BY lucro DESC LIMIT 1',
            {'kk_bi': float(valor.KK_POR_BI), 'bi': cfg['rs_por_bi'], 'tcc': cfg['rs_por_tcc']}).fetchone()
        return {'valores': r['n'], 'itens': r['itens'], 'contas_com_item': com_item, 'ativas': ativas,
                'melhor': self._publico(melhor, cfg) if melhor else None}

    # -------------------------------------------------------------- buscas salvas e avisos

    def buscas(self):
        return [{**dict(r), 'filtros': json.loads(r['filtros']), 'avisar': bool(r['avisar'])}
                for r in self.con.execute('SELECT * FROM buscas ORDER BY id')]

    def busca(self, busca_id):
        r = self.con.execute('SELECT * FROM buscas WHERE id = ?', (busca_id,)).fetchone()
        return {**dict(r), 'filtros': json.loads(r['filtros']), 'avisar': bool(r['avisar'])} if r else None

    def salvar_busca(self, dados, busca_id=None):
        nome = str(dados.get('nome') or '').strip()
        if not nome:
            raise ValueError('Dê um nome para a busca.')
        filtros = dados.get('filtros') or {}
        if not isinstance(filtros, dict):
            raise ValueError('Filtros inválidos.')
        campos = (nome, json.dumps(filtros, ensure_ascii=False), 1 if dados.get('avisar', True) else 0,
                  _numero(dados.get('lucro_min_rs')), _numero(dados.get('lucro_min_pct')), agora())
        with self._transacao() as con:
            if busca_id:
                cur = con.execute('UPDATE buscas SET nome=?, filtros=?, avisar=?, lucro_min_rs=?, lucro_min_pct=?, '
                                  'atualizado_em=? WHERE id=?', (*campos, busca_id))
                if cur.rowcount == 0:
                    raise KeyError(busca_id)
            else:
                busca_id = con.execute('INSERT INTO buscas (nome, filtros, avisar, lucro_min_rs, lucro_min_pct, '
                                       'atualizado_em, criado_em) VALUES (?,?,?,?,?,?,?)',
                                       (*campos, campos[-1])).lastrowid
        return busca_id

    def apagar_busca(self, busca_id):
        with self._transacao() as con:
            con.execute('DELETE FROM avisos WHERE busca_id = ?', (busca_id,))
            con.execute('DELETE FROM buscas WHERE id = ?', (busca_id,))

    def registrar_aviso(self, busca_id, anuncio_id, preco, lucro_rs, motivo):
        """True se o aviso é inédito (mesma busca + conta + preço só avisa uma vez)."""
        with self._transacao() as con:
            cur = con.execute('INSERT OR IGNORE INTO avisos (busca_id, anuncio_id, preco, lucro_rs, motivo, quando) '
                              'VALUES (?,?,?,?,?,?)', (busca_id, anuncio_id, preco, lucro_rs, motivo, agora()))
            return cur.rowcount == 1

    def avisos(self, limite=100):
        return [dict(r) for r in self.con.execute(
            'SELECT v.*, b.nome AS busca, a.nome AS conta, a.classe, a.nivel, a.ativo '
            'FROM avisos v JOIN buscas b ON b.id = v.busca_id LEFT JOIN anuncios a ON a.id = v.anuncio_id '
            'ORDER BY v.id DESC LIMIT ?', (limite,))]

    def ultimos_avisos_por_busca(self):
        return {r[0]: r[1] for r in self.con.execute('SELECT busca_id, MAX(quando) FROM avisos GROUP BY busca_id')}


def _ha_24h():
    return (datetime.now() - timedelta(hours=24)).isoformat(timespec='seconds')
