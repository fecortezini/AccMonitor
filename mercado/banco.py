"""Banco local (SQLite) do Mercado PW: anúncios, itens das contas, tabela de valores, buscas e avisos.

A tabela de valores, as buscas, os grupos, as favoritas e as configurações também ficam no meus-dados.json,
que vai pelo git para os outros PCs (ver Banco.sincronizar). O resto é de cada PC: as contas, o coletor lê do site.
"""
import hashlib
import json
import logging
import os
import sqlite3
import statistics
import threading
import zlib
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from pathlib import Path

from . import valor
from .site import norm

log = logging.getLogger('mercado')

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
    valor_kk REAL, destaques TEXT,
    lances INTEGER, maior_lance INTEGER, lances_em TEXT, lance_novo_em TEXT
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
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
    grupo_id INTEGER  -- linha de um grupo de itens: vale para cada item dele (nome = o do grupo)
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

CREATE TABLE IF NOT EXISTS grupos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, itens TEXT NOT NULL,
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);

-- Favoritas: id = o da conta. Vão no meus-dados.json; a situação e os avisos delas são de cada PC.
CREATE TABLE IF NOT EXISTS favoritas (
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS situacao_favoritas (
    id INTEGER PRIMARY KEY, situacao TEXT NOT NULL, desde TEXT NOT NULL,  -- a_venda, confirmando ou retirada
    sumiu_em TEXT, visto_antes TEXT, tentativas INTEGER NOT NULL DEFAULT 0, proxima_em TEXT
);
CREATE TABLE IF NOT EXISTS avisos_favoritas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, anuncio_id INTEGER NOT NULL, nome TEXT NOT NULL, evento TEXT NOT NULL,
    texto TEXT NOT NULL, preco INTEGER, quando TEXT NOT NULL
);
"""

PADROES = {
    'intervalo_s': 60, 'pausa_s': 2, 'leituras_simultaneas': 1, 'rs_por_bi': 500.0, 'rs_por_tcc': 1.0,
    'aviso_windows': True, 'aviso_bipes': True, 'aviso_navegador': False,
    'telegram_token': '', 'telegram_chat': '', 'discord_webhook': '',
    'largura_filtros': 27, 'largura_detalhes': 33, 'detalhes_recolhidos': False,
}
LIMITES = {'intervalo_s': (30, 3600), 'pausa_s': (1, 60), 'leituras_simultaneas': (1, 8),
           'rs_por_bi': (0.01, 10_000_000), 'rs_por_tcc': (0.01, 100_000),
           'largura_filtros': (15, 45), 'largura_detalhes': (20, 50)}
# Ficam só em cada PC, fora do meus-dados.json: o tamanho dos painéis (a tela pode ser outra) e os
# tokens do Telegram e do Discord (o arquivo vai para o git)
SO_NESTE_PC = frozenset({'largura_filtros', 'largura_detalhes', 'detalhes_recolhidos',
                         'telegram_token', 'telegram_chat', 'discord_webhook'})
COMPARTILHADAS = tuple(k for k in PADROES if k not in SO_NESTE_PC)
# Versão do meus-dados.json. A 2 tem valores de grupo, e a 3 tem favoritas; o arquivo só é gravado numa versão
# quando tem o que ela trouxe, para um PC com o programa antigo recusar o arquivo (e pedir para atualizar) em vez
# de perder esses dados.
FORMATO_DADOS = 3
_GRAVAR_CONFIG = ('INSERT INTO config(chave, valor) VALUES (?, ?) '
                  'ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor')

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
# Ordens pelos itens pesquisados (só valem com condições de item): "itens" (soma das unidades),
# "item:N" (unidades da condição N) e "preco_item" (menor preço por unidade). Ver _ordenar_por_itens.


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


def _condicao(c):
    """Condição de item da busca com os campos já no formato certo (a interface recebe de volta).

    Ela é de um item (item_id), de parte do nome (nome) ou de um grupo de itens (grupo_id). O grupo
    exige todos os itens dele no "Tem item" (as cartas de um combo) e qualquer um no "Tem pelo menos
    um" (a arma de um rank): ver Banco._resolver_grupos.
    """
    item_id = c.get('item_id')
    return {'item_id': int(item_id) if item_id else None, 'grupo_id': _inteiro(c.get('grupo_id')),
            'nome': str(c.get('nome') or ''), 'refino_min': int(_numero(c.get('refino_min')) or 0),
            'qtd_min': max(1, int(_numero(c.get('qtd_min')) or 1)), 'onde': str(c.get('onde') or '')}


def _condicoes(lista):
    """Condições de item de uma lista dos filtros, só as que têm o item, o grupo ou um texto do nome."""
    return [_condicao(c) for c in (lista or [])
            if isinstance(c, dict) and (c.get('item_id') or c.get('grupo_id') or norm(c.get('nome')))]


def _filtros_do_anuncio(f, p):
    """Condições SQL (tabela a) dos filtros que não dependem dos itens: nome, classe, preço, nível, céu, novas."""
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
    return conds


def _ids_sql(ids):
    return ','.join(str(int(i)) for i in ids) or 'NULL'


# Conta que falta ler: sem itens lidos, ou lidos com outro preço
_PARA_LER = '(a.itens_lidos_em IS NULL OR a.preco_lido IS NULL OR a.preco_lido != a.preco)'


def _lidas_ou_do_site(sub, site):
    """Contas lidas que estão na subconsulta e, das ainda não lidas, as que a busca do site aponta (site None: nenhuma)."""
    if site is None:
        return f'(a.itens_lidos_em IS NOT NULL AND a.id IN ({sub}))'
    lista = ','.join(str(int(i)) for i in site) or 'NULL'
    return f'((a.itens_lidos_em IS NOT NULL AND a.id IN ({sub})) OR (a.itens_lidos_em IS NULL AND a.id IN ({lista})))'


def _ordem_por_itens(ordem):
    return ordem in ('itens', 'preco_item') or (ordem.startswith('item:') and ordem[5:].isdigit())


def _ordenar_por_itens(contas, ordem):
    """Ordena pelas unidades dos itens pesquisados; os empates ficam com o menor preço.

    As contas ainda não lidas ("a confirmar") vão para o fim, porque não se sabe quanto têm.
    """
    n = int(ordem[5:]) if ordem.startswith('item:') else None

    def chave(c):
        q = c['qtd_busca']
        if not q:
            return (1, 0, 0, c['preco'], c['id'])
        total = sum(q)
        if ordem == 'preco_item':
            return (0, c['preco'] / total if total else float('inf'), -total, c['preco'], c['id'])
        return (0, -(q[n] if n is not None and n < len(q) else total), -total, c['preco'], c['id'])

    contas.sort(key=chave)


def _limpar_config(mudancas):
    """Configurações conhecidas, no tipo certo e dentro dos limites; as outras chaves são ignoradas."""
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
    return limpo


# ------------------------------------------------------------------ meus-dados.json

def _inteiro(v):
    """Id (inteiro positivo) ou None."""
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _dicts(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _numerar(linhas):
    """Dá um id novo às linhas sem id ou com id repetido (pode acontecer ao juntar mudanças de dois PCs no git)."""
    vistos, proximo = set(), max((l['id'] or 0 for l in linhas), default=0) + 1
    for l in linhas:
        if l['id'] is None or l['id'] in vistos:
            l['id'], proximo = proximo, proximo + 1
        vistos.add(l['id'])
    linhas.sort(key=lambda l: l['id'])


def _normalizar(dados):
    """Dados compartilhados (lidos do arquivo ou do banco) num formato só, para comparar, gravar e importar."""
    if not isinstance(dados, dict):
        raise ValueError('o conteúdo não é um objeto JSON')
    if (_inteiro(dados.get('formato')) or 1) > FORMATO_DADOS:
        raise ValueError('foi gravado por uma versão mais nova do programa; atualize com git pull')
    recebidas = dados.get('configuracoes') if isinstance(dados.get('configuracoes'), dict) else {}
    cfg = {k: PADROES[k] for k in COMPARTILHADAS}
    cfg.update(_limpar_config({k: v for k, v in recebidas.items() if k in cfg}))
    valores = []
    for v in _dicts(dados.get('valores')):
        nome, kk = str(v.get('nome') or '').strip(), _numero(v.get('valor_kk'))
        if nome and kk is not None and kk > 0:
            grupo_id = _inteiro(v.get('grupo_id'))
            valores.append({'id': _inteiro(v.get('id')), 'item_id': None if grupo_id else _inteiro(v.get('item_id')),
                            'nome': nome, 'refino_min': min(max(int(_numero(v.get('refino_min')) or 0), 0), 20),
                            'valor_kk': kk, 'criado_em': str(v.get('criado_em') or ''),
                            'atualizado_em': str(v.get('atualizado_em') or ''),
                            **({'grupo_id': grupo_id} if grupo_id else {})})  # só nos de grupo: o arquivo antigo não muda
    buscas = []
    for b in _dicts(dados.get('buscas')):
        nome, filtros = str(b.get('nome') or '').strip(), b.get('filtros')
        if nome:
            buscas.append({'id': _inteiro(b.get('id')), 'nome': nome, 'avisar': bool(b.get('avisar', True)),
                           'lucro_min_rs': _numero(b.get('lucro_min_rs')),
                           'lucro_min_pct': _numero(b.get('lucro_min_pct')),
                           'criado_em': str(b.get('criado_em') or ''), 'atualizado_em': str(b.get('atualizado_em') or ''),
                           'filtros': filtros if isinstance(filtros, dict) else {}})
    grupos = []
    for g in _dicts(dados.get('grupos')):
        if nome := str(g.get('nome') or '').strip():
            grupos.append({'id': _inteiro(g.get('id')), 'nome': nome, 'itens': _itens_do_grupo(g.get('itens')),
                           'criado_em': str(g.get('criado_em') or ''), 'atualizado_em': str(g.get('atualizado_em') or '')})
    favoritas = {}
    for f in _dicts(dados.get('favoritas')):  # o id é o da conta: não se renumera, e repetida fica uma só
        rid, nome = _inteiro(f.get('id')), str(f.get('nome') or '').strip()
        if rid and nome and rid not in favoritas:
            favoritas[rid] = {'id': rid, 'nome': nome, 'criado_em': str(f.get('criado_em') or ''),
                              'atualizado_em': str(f.get('atualizado_em') or '')}
    _numerar(valores)
    _numerar(buscas)
    _numerar(grupos)
    return {'configuracoes': cfg, 'valores': valores, 'buscas': buscas, 'grupos': grupos,
            'favoritas': sorted(favoritas.values(), key=lambda f: f['id'])}


def _itens_do_grupo(lista):
    """Itens de um grupo: só os que têm item_id, sem repetir, na ordem em que foram escolhidos."""
    itens, vistos = [], set()
    for it in _dicts(lista):
        if (item_id := _inteiro(it.get('item_id'))) and item_id not in vistos:
            vistos.add(item_id)
            itens.append({'item_id': item_id, 'nome': str(it.get('nome') or '')})
    return itens


def dados_normalizados(dados):
    """Os dados compartilhados (de um meus-dados.json já lido) no formato em que o banco compara e grava."""
    return _normalizar(dados)


def _hash(dados):
    if not dados.get('favoritas'):  # sem favoritas, o mesmo hash de antes delas: nada conta como mudado
        dados = {k: v for k, v in dados.items() if k != 'favoritas'}
    return hashlib.sha1(json.dumps(dados, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _vazio(dados):
    """Sem nada do usuário: nenhum valor, nenhuma busca, nenhum grupo, nenhuma favorita e as configurações padrão."""
    return (not dados['valores'] and not dados['buscas'] and not dados['grupos'] and not dados['favoritas']
            and dados['configuracoes'] == {k: PADROES[k] for k in COMPARTILHADAS})


def _formatar(dados):
    """Texto do meus-dados.json, com uma linha por valor, busca, grupo e favorita, para o git mostrar e juntar as mudanças.

    As favoritas só aparecem no arquivo quando há alguma (sem elas, o arquivo fica como antes).
    """
    def lista(linhas):
        return '[\n' + ',\n'.join('    ' + json.dumps(l, ensure_ascii=False) for l in linhas) + '\n  ]' if linhas else '[]'
    cfg = ',\n'.join(f'    {json.dumps(k)}: {json.dumps(v)}' for k, v in dados['configuracoes'].items())
    formato = 3 if dados['favoritas'] else 2 if any(v.get('grupo_id') for v in dados['valores']) else 1  # ver FORMATO_DADOS
    favoritas = f',\n  "favoritas": {lista(dados["favoritas"])}' if dados['favoritas'] else ''
    return (f'{{\n  "formato": {formato},\n  "configuracoes": {{\n{cfg}\n  }},\n'
            f'  "valores": {lista(dados["valores"])},\n  "buscas": {lista(dados["buscas"])},\n'
            f'  "grupos": {lista(dados["grupos"])}{favoritas}\n}}\n')


class Banco:
    def __init__(self, caminho, arquivo_dados=None):
        """arquivo_dados: o meus-dados.json compartilhado entre os PCs (None = só o banco, como nos testes)."""
        self.caminho = str(caminho)
        self.arquivo_dados = Path(arquivo_dados) if arquivo_dados else None
        self.erro_dados = None      # aparece na faixa do topo quando o arquivo não pode ser lido
        self._assinatura = None     # (mtime, tamanho) do arquivo na última leitura ou gravação
        self._trava_dados = threading.RLock()
        self._local = threading.local()
        self._escrita = threading.Lock()  # o SQLite aceita um escritor por vez
        with self._escrita:
            self.con.executescript(ESQUEMA)
            # colunas que vieram depois da primeira versão (um banco antigo ganha as colunas, vazias)
            colunas = {r[1] for r in self.con.execute('PRAGMA table_info(anuncios)')}
            for coluna, tipo in (('lances', 'INTEGER'), ('maior_lance', 'INTEGER'), ('lances_em', 'TEXT'),
                                 ('lance_novo_em', 'TEXT')):
                if coluna not in colunas:
                    self.con.execute(f'ALTER TABLE anuncios ADD COLUMN {coluna} {tipo}')
            if 'grupo_id' not in {r[1] for r in self.con.execute('PRAGMA table_info(valores)')}:
                self.con.execute('ALTER TABLE valores ADD COLUMN grupo_id INTEGER')
        self.sincronizar()

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
        limpo = _limpar_config(mudancas)
        compartilhada = any(k not in SO_NESTE_PC for k in limpo)
        with self._mudando_dados() if compartilhada else nullcontext(), self._transacao() as con:
            con.executemany(_GRAVAR_CONFIG, [(k, json.dumps(v)) for k, v in limpo.items()])
        return self.config()

    def meta(self, chave, padrao=None):
        r = self.con.execute('SELECT valor FROM config WHERE chave = ?', ('_' + chave,)).fetchone()
        return json.loads(r['valor']) if r else padrao

    def salvar_meta(self, chave, v):
        with self._transacao() as con:
            con.execute(_GRAVAR_CONFIG, ('_' + chave, json.dumps(v)))

    # -------------------------------------------------------------- meus-dados.json (compartilhado entre os PCs)

    def sincronizar(self):
        """Acerta o banco com o meus-dados.json. Devolve True se trouxe mudanças do arquivo.

        O arquivo guarda a tabela de valores, as buscas e as configurações (menos as de SO_NESTE_PC) e
        vai pelo git para os outros PCs. O programa grava nele a cada mudança, e o que muda nele por fora
        (git pull, edição) vem para o banco. Se os dois mudaram, vale o arquivo, e o que o banco tinha
        fica em meus-dados.anterior.json. É o caso de um PC que já tinha dados na primeira vez com o arquivo.
        """
        if self.arquivo_dados is None:
            return False
        with self._trava_dados:
            try:
                return self._sincronizar()
            except OSError as e:
                self._assinatura = None  # tenta de novo na próxima vez
                log.warning('Não consegui sincronizar o %s: %s', self.arquivo_dados.name, e)
                return False

    def _sincronizar(self):
        assinatura = self._assinatura_do_arquivo()
        if assinatura is not None and assinatura == self._assinatura:
            return False  # o arquivo não mudou desde a última leitura ou gravação
        if assinatura is None:  # sem arquivo: grava o que está no banco (primeira vez, ou ele foi apagado)
            self.erro_dados = None
            self._exportar()
            return False
        texto = self.arquivo_dados.read_text(encoding='utf-8-sig')
        try:
            arquivo = _normalizar(json.loads(texto))
        except ValueError as e:
            self._assinatura = assinatura  # só tenta de novo quando o arquivo mudar
            problema = 'um conflito do git' if '<<<<<<<' in texto else f'um erro ({e})'
            self.erro_dados = (f'O {self.arquivo_dados.name} está com {problema}. Resolva, ou apague o arquivo para '
                               'gravar de novo os dados deste PC. Até lá, mudanças na tabela de valores, nas buscas '
                               'e nas configurações não são salvas.')
            log.warning(self.erro_dados)
            return False
        self.erro_dados = None
        self._assinatura = assinatura
        banco = self._dados_do_banco()
        h_arquivo, h_banco, h_sincronizado = _hash(arquivo), _hash(banco), self.meta('dados_hash')
        if h_arquivo == h_banco:
            if h_sincronizado != h_arquivo:
                self.salvar_meta('dados_hash', h_arquivo)
            return False
        if h_arquivo == h_sincronizado:  # só o banco mudou: a última gravação do arquivo tinha falhado
            self._exportar(banco)
            return False
        if h_banco != h_sincronizado and not _vazio(banco):
            anterior = self.arquivo_dados.with_suffix('.anterior.json')
            anterior.write_text(_formatar(banco), encoding='utf-8')
            log.warning('Os dados deste PC eram diferentes dos do %s e foram trocados por eles. Os anteriores '
                        'ficaram em %s', self.arquivo_dados.name, anterior.name)
        self._importar(arquivo)
        log.info('Tabela de valores, buscas e configurações trazidas do %s', self.arquivo_dados.name)
        return True

    def _assinatura_do_arquivo(self):
        try:
            st = self.arquivo_dados.stat()
        except FileNotFoundError:
            return None
        return st.st_mtime_ns, st.st_size

    def _dados_do_banco(self):
        cfg = self.config()
        return _normalizar({
            'configuracoes': {k: cfg[k] for k in COMPARTILHADAS},
            'valores': [dict(r) for r in self.con.execute(
                'SELECT id, item_id, nome, refino_min, valor_kk, criado_em, atualizado_em, grupo_id FROM valores')],
            'buscas': [{**dict(r), 'filtros': json.loads(r['filtros'])} for r in self.con.execute(
                'SELECT id, nome, avisar, lucro_min_rs, lucro_min_pct, criado_em, atualizado_em, filtros FROM buscas')],
            'grupos': self.grupos(),
            'favoritas': [dict(r) for r in self.con.execute('SELECT id, nome, criado_em, atualizado_em FROM favoritas')],
        })

    def _importar(self, dados):
        with self._transacao() as con:
            antes = {r['id']: r['criado_em'] for r in con.execute('SELECT id, criado_em FROM buscas')}
            con.execute('DELETE FROM valores')
            con.executemany(
                'INSERT INTO valores (id, item_id, nome, nome_norm, refino_min, valor_kk, criado_em, atualizado_em, '
                'grupo_id) VALUES (?,?,?,?,?,?,?,?,?)',
                [(v['id'], v['item_id'], v['nome'], norm(v['nome']), v['refino_min'], v['valor_kk'], v['criado_em'],
                  v['atualizado_em'], v.get('grupo_id')) for v in dados['valores']])
            con.execute('DELETE FROM buscas')
            con.executemany(
                'INSERT INTO buscas (id, nome, filtros, avisar, lucro_min_rs, lucro_min_pct, criado_em, atualizado_em) '
                'VALUES (?,?,?,?,?,?,?,?)',
                [(b['id'], b['nome'], json.dumps(b['filtros'], ensure_ascii=False), int(b['avisar']),
                  b['lucro_min_rs'], b['lucro_min_pct'], b['criado_em'], b['atualizado_em']) for b in dados['buscas']])
            # o histórico de avisos é de cada PC; sai o das buscas que não existem mais ou viraram outra
            con.execute('DELETE FROM grupos')
            con.executemany('INSERT INTO grupos (id, nome, itens, criado_em, atualizado_em) VALUES (?,?,?,?,?)',
                            [(g['id'], g['nome'], json.dumps(g['itens'], ensure_ascii=False), g['criado_em'],
                              g['atualizado_em']) for g in dados['grupos']])
            depois = {b['id']: b['criado_em'] for b in dados['buscas']}
            con.executemany('DELETE FROM avisos WHERE busca_id = ?',
                            [(bid,) for bid, criada in antes.items() if depois.get(bid) != criada])
            con.execute('DELETE FROM favoritas')
            con.executemany('INSERT INTO favoritas (id, nome, criado_em, atualizado_em) VALUES (?,?,?,?)',
                            [(f['id'], f['nome'], f['criado_em'], f['atualizado_em']) for f in dados['favoritas']])
            # a situação é deste PC; sai a das contas que deixaram de ser favoritas (desmarcadas ou vendidas no outro PC)
            con.execute('DELETE FROM situacao_favoritas WHERE id NOT IN (SELECT id FROM favoritas)')
            con.executemany(_GRAVAR_CONFIG, [(k, json.dumps(v)) for k, v in dados['configuracoes'].items()]
                            + [('_dados_hash', json.dumps(_hash(dados)))])
        self.recalcular()

    def _exportar(self, dados=None):
        """Grava o arquivo, sem passar por cima dele se estiver com erro ou tiver mudado sem ser lido."""
        atual = self._assinatura_do_arquivo()
        if self.erro_dados or (atual is not None and atual != self._assinatura):
            return  # o próximo sincronizar() resolve
        dados = self._dados_do_banco() if dados is None else dados
        try:
            self._gravar_arquivo(dados)
        except OSError as e:
            log.warning('Não consegui gravar o %s: %s', self.arquivo_dados.name, e)
            self._assinatura = None  # tenta de novo no próximo sincronizar()
            return
        self.salvar_meta('dados_hash', _hash(dados))

    def _gravar_arquivo(self, dados):
        """Grava os dados no arquivo (de uma vez, pelo .tmp); se o texto já é o mesmo, não mexe nele."""
        texto = _formatar(dados)
        if self._assinatura_do_arquivo() is None or self.arquivo_dados.read_text(encoding='utf-8-sig') != texto:
            temporario = self.arquivo_dados.with_name(self.arquivo_dados.name + '.tmp')
            temporario.write_text(texto, encoding='utf-8')
            os.replace(temporario, self.arquivo_dados)
        self._assinatura = self._assinatura_do_arquivo()

    # usados pela sincronia com o git (mercado/sincronia.py)

    @contextmanager
    def arquivo_em_uso(self):
        """Segura o meus-dados.json: enquanto a sincronia mexe nele pelo git, o programa não lê nem grava."""
        with self._trava_dados:
            yield

    def dados_compartilhados(self):
        """Os dados do meus-dados.json (tabela, buscas, grupos e configurações), já iguais aos do banco."""
        with self._trava_dados:
            self.sincronizar()
            if self.erro_dados:
                raise ValueError(self.erro_dados)
            return self._dados_do_banco()

    def dados_a_enviar(self):
        """Os dados mudaram desde a última sincronia com o GitHub (o botão Sincronizar ganha um ponto)."""
        return self.arquivo_dados is not None and self.meta('dados_hash') != self.meta('enviado_hash')

    def substituir_dados(self, dados):
        """Troca os dados compartilhados (vindos da sincronia) no banco e no arquivo."""
        dados = _normalizar(dados)
        with self._trava_dados:
            self._importar(dados)
            self._gravar_arquivo(dados)
            self.erro_dados = None

    @contextmanager
    def _mudando_dados(self):
        """Mudança na tabela de valores, nas buscas ou numa configuração compartilhada.

        Antes, traz o que mudou no arquivo (para não gravar por cima); depois, grava o arquivo.
        """
        if self.arquivo_dados is None:
            yield
            return
        with self._trava_dados:
            self.sincronizar()
            if self.erro_dados:
                raise ValueError(self.erro_dados)
            yield
            self._exportar()

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
                    con.execute('UPDATE anuncios SET nova=1, primeiro_visto=?, itens_lidos_em=NULL, preco_lido=NULL, '
                                'valor_kk=NULL, destaques=NULL, lances=NULL, maior_lance=NULL, lances_em=NULL, '
                                'lance_novo_em=NULL WHERE id=?', (quando, a.id))
                    reativados.append(a.id)
                elif a.preco < r['preco']:
                    baixaram.append((a.id, r['preco'], a.preco))
            sumiram = [rid for rid, r in antes.items() if r['ativo'] and rid not in anuncios]
            con.executemany('UPDATE anuncios SET ativo=0 WHERE id=?', [(rid,) for rid in sumiram])
        return {'primeira': primeira, 'novos': novos, 'baixaram': baixaram,
                'reativados': reativados, 'removidos': len(sumiram), 'sumiram': sumiram}

    def anuncio(self, anuncio_id):
        r = self.con.execute('SELECT * FROM anuncios WHERE id = ?', (anuncio_id,)).fetchone()
        return dict(r) if r else None

    def contas_para_ler(self):
        """Anúncios ativos sem itens lidos (ou lidos com outro preço), dos mais baratos aos mais caros."""
        return [dict(r) for r in self.con.execute(
            f'SELECT id, preco FROM anuncios a WHERE ativo = 1 AND {_PARA_LER} ORDER BY preco, id')]

    def para_ler_na_busca(self, filtros, ids_do_site=None):
        """Contas que faltam ler e podem bater com os filtros, das mais baratas às mais caras.

        Os filtros do anúncio (classe, preço, nível...) já se sabem. Os de item só lendo a conta, mas a
        busca do site (ids_do_site, como em buscar) responde pelos equipamentos do catálogo: numa condição
        dessas, só contam as contas que ela aponta. Sem filtro nenhum, são todas as que faltam ler.
        """
        f = filtros or {}
        p = {}
        conds = _filtros_do_anuncio(f, p) + [_PARA_LER]
        for cond in self._resolver_grupos(_condicoes(f.get('itens')), todos=True):
            if (ids := ids_do_site(cond) if ids_do_site else None) is not None:
                conds.append(f'a.id IN ({_ids_sql(ids)})')
        algum = self._resolver_grupos(_condicoes(f.get('algum')))
        site = set()
        for cond in algum:  # vale a conta com qualquer um; se um deles o site não responde, pode ser qualquer conta
            if (ids := ids_do_site(cond) if ids_do_site else None) is None:
                break
            site |= set(ids)
        else:
            if algum:
                conds.append(f'a.id IN ({_ids_sql(site)})')
        return [r[0] for r in self.con.execute(
            f'SELECT a.id FROM anuncios a WHERE {" AND ".join(conds)} ORDER BY a.preco, a.id', p)]

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
                conhecidos[it.item_id] = (it.item_id, it.nome, nome_norm, tipo, it.efeito if tipo == 'pedra' else '')
        with self._transacao() as con:
            con.execute('DELETE FROM itens WHERE anuncio_id = ?', (anuncio_id,))
            con.executemany('INSERT INTO itens (anuncio_id, ordem, secao, item_id, nome, nome_norm, refino, qtd, '
                            'efeito, tooltip_id) VALUES (?,?,?,?,?,?,?,?,?,?)', linhas)
            con.executemany('INSERT OR IGNORE INTO tooltips (id, dados) VALUES (?, ?)', tooltips.items())
            con.executemany('INSERT OR IGNORE INTO conhecidos (item_id, nome, nome_norm, tipo, efeito) '
                            'VALUES (?,?,?,?,?)', conhecidos.values())
            pendentes = {r['nome_norm'] for r in con.execute(
                'SELECT nome_norm FROM valores WHERE item_id IS NULL AND grupo_id IS NULL')}
            vinculou = False
            for item_id, _, nome_norm, _, _ in conhecidos.values():
                if nome_norm in pendentes:  # valor cadastrado só pelo nome ganha o item_id
                    con.execute('UPDATE valores SET item_id = ? WHERE item_id IS NULL AND grupo_id IS NULL '
                                'AND nome_norm = ?', (item_id, nome_norm))
                    pendentes.discard(nome_norm)
                    vinculou = True
            con.execute('UPDATE anuncios SET itens_lidos_em = ?, preco_lido = ? WHERE id = ?',
                        (quando, preco, anuncio_id))
        self.recalcular([anuncio_id])
        if vinculou and self.arquivo_dados is not None:
            with self._trava_dados:
                self._exportar()  # o item_id também vai para o meus-dados.json

    # -------------------------------------------------------------- lances

    def gravar_lance(self, anuncio_id, lance, quando=None):
        """Lances pendentes da conta e o maior deles, lidos do botão "Fazer lance" do site.

        Devolve True se chegou lance novo: maior, ou mais lances, do que da última vez que foram vistos.
        Na primeira vez que os lances da conta são vistos, nada conta como novo.
        """
        quando = quando or agora()
        with self._transacao() as con:
            antes = con.execute('SELECT lances, maior_lance, lances_em FROM anuncios WHERE id = ?', (anuncio_id,)).fetchone()
            if antes is None:
                return False
            novo = antes['lances_em'] is not None and (lance['maior'] > (antes['maior_lance'] or 0)
                                                       or lance['pendentes'] > (antes['lances'] or 0))
            con.execute('UPDATE anuncios SET lances = ?, maior_lance = ?, lances_em = ?, '
                        'lance_novo_em = CASE WHEN ? THEN ? ELSE lance_novo_em END WHERE id = ?',
                        (lance['pendentes'], lance['maior'], quando, novo, quando, anuncio_id))
        return novo

    def lance_velho(self, ids, antes_de):
        """A primeira das contas ids (na ordem dada) que está no ar e teve os lances vistos antes de antes_de, ou nunca."""
        if not ids:
            return None
        velhas = {r[0] for r in self.con.execute(
            f'SELECT id FROM anuncios WHERE ativo = 1 AND id IN ({_marcadores(len(ids))}) '
            'AND (lances_em IS NULL OR lances_em < ?)', (*ids, antes_de))}
        return next((i for i in ids if i in velhas), None)

    def lance_mais_velho(self, fora=()):
        """A conta no ar, já lida, cujos lances foram vistos há mais tempo (as nunca vistas primeiro, das mais baratas)."""
        fora = list(fora)
        sem = f'AND id NOT IN ({_marcadores(len(fora))}) ' if fora else ''
        r = self.con.execute(
            f'SELECT id FROM anuncios WHERE ativo = 1 AND itens_lidos_em IS NOT NULL {sem}'
            'ORDER BY lances_em IS NOT NULL, lances_em, preco, id LIMIT 1', fora).fetchone()
        return r[0] if r else None

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
        """item_ids da tabela de valores (inclusive os dos grupos com valor) e das condições das buscas salvas
        ("Tem item" e "Tem pelo menos um", inclusive os itens dos grupos)."""
        ids = {r[0] for r in self.con.execute('SELECT DISTINCT item_id FROM valores WHERE item_id IS NOT NULL')}
        grupos = self._itens_dos_grupos()
        for r in self.con.execute('SELECT DISTINCT grupo_id FROM valores WHERE grupo_id IS NOT NULL'):
            ids.update(grupos.get(r[0], ()))
        for b in self.buscas():
            for c in self._resolver_grupos(_condicoes(b['filtros'].get('itens')) + _condicoes(b['filtros'].get('algum'))):
                ids.update(c.get('itens') or ())
                if c['item_id'] is not None:
                    ids.add(c['item_id'])
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
            'favorita': anuncio_id in self.ids_favoritas(),
            'situacao': self.situacao_favorita(anuncio_id),
            'itens': [{'secao': r['secao'], 'item_id': r['item_id'], 'nome': r['nome'], 'refino': r['refino'],
                       'qtd': r['qtd'], 'efeito': r['efeito'], 'tooltip': r['tooltip_id']} for r in itens],
            'tooltips': tooltips,
            'detalhes': [{**d, 'rs': valor.kk_para_rs(d['kk'], cfg['rs_por_bi'])} for d in detalhes],
        }

    def limpar_antigos(self, dias=7):
        """Apaga os itens de anúncios que saíram do ar há mais de `dias` dias. Os das favoritas ficam."""
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec='seconds')
        with self._transacao() as con:
            velhos = [r[0] for r in con.execute(
                'SELECT id FROM anuncios WHERE ativo = 0 AND ultimo_visto < ? AND itens_lidos_em IS NOT NULL '
                'AND id NOT IN (SELECT id FROM favoritas)', (limite,))]
            _apagar_itens(con, velhos)
            if velhos:
                con.execute('DELETE FROM tooltips WHERE id NOT IN '
                            '(SELECT DISTINCT tooltip_id FROM itens WHERE tooltip_id IS NOT NULL)')
        return len(velhos)

    # -------------------------------------------------------------- valor das contas

    def _tabela(self):
        return valor.Tabela([dict(r) for r in self.con.execute(
            'SELECT id, item_id, nome, nome_norm, refino_min, valor_kk, grupo_id FROM valores')], self._itens_dos_grupos())

    def _itens_dos_grupos(self):
        """{grupo_id: [item_ids]}"""
        return {g['id']: [it['item_id'] for it in g['itens']] for g in self.grupos()}

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
            if item_ids := {*tabela.por_id, *tabela.por_grupo}:
                conds.append(f'item_id IN ({_marcadores(len(item_ids))})')
                params += list(item_ids)
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
                 'lances': r['lances'], 'maior_lance': r['maior_lance'], 'lances_em': r['lances_em'],
                 'lance_novo_em': r['lance_novo_em'],
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
        conds = _filtros_do_anuncio(f, p)
        base = list(conds)

        # "Tem item" (itens): a conta precisa atender a todas as condições, e de um grupo ter todos os itens
        condicoes = self._resolver_grupos(_condicoes(f.get('itens')), todos=True)
        filtros_item = []
        for n, cond in enumerate(condicoes):
            filtro, sub = self._contas_com_item(cond, f'i{n}', p)
            filtros_item.append(filtro)
            conds.append(_lidas_ou_do_site(sub, ids_do_site(cond) if ids_do_site else None))
        # "Tem pelo menos um" (algum): basta atender a uma, como a arma de um rank, que tem um nome em cada classe
        algum = self._resolver_grupos(_condicoes(f.get('algum')))
        if algum:
            subs, site = [], None
            for n, cond in enumerate(algum):
                subs.append(self._contas_com_item(cond, f'a{n}', p)[1])
                if (ids := ids_do_site(cond) if ids_do_site else None) is not None:
                    site = (site or set()) | set(ids)
            conds.append(_lidas_ou_do_site(' UNION '.join(subs), site))
        lucro_sql = 'CASE WHEN a.valor_kk > 0 THEN a.valor_kk / :kk_bi * :bi - a.preco * :tcc END'
        if f.get('so_lucro'):
            conds.append(f'({lucro_sql}) > 0')
        ordem = str(f.get('ordem') or '')
        por_itens = bool(condicoes) and _ordem_por_itens(ordem)
        linhas = self.con.execute(
            f'SELECT a.*, {lucro_sql} AS lucro_rs, '
            f'CASE WHEN a.valor_kk > 0 THEN ({lucro_sql}) / (a.valor_kk / :kk_bi * :bi) END AS lucro_pct '
            f'FROM anuncios a WHERE {" AND ".join(conds)} '
            f'ORDER BY {ORDENS["preco"] if por_itens else ORDENS.get(ordem, ORDENS["lucro_rs"])}', p).fetchall()

        qtds = self._quantidades(filtros_item, p) if condicoes else {}
        favoritas = self.ids_favoritas()
        contas = []
        for r in linhas:
            conta = self._publico(r, cfg)
            conta['favorita'] = r['id'] in favoritas
            conta['a_confirmar'] = bool(condicoes or algum) and not conta['lida']
            # unidades de cada item pesquisado (na ordem das condições); None = itens ainda não lidos
            conta['qtd_busca'] = qtds.get(r['id'], [0] * len(condicoes)) if condicoes and conta['lida'] else None
            contas.append(conta)
        if por_itens:
            _ordenar_por_itens(contas, ordem)
        precos = [c['preco'] for c in contas]
        nao_lidas = 0
        if condicoes or algum or f.get('so_lucro'):
            fora = self.con.execute(f'SELECT COUNT(*) FROM anuncios a WHERE {" AND ".join(base)} '
                                    'AND a.itens_lidos_em IS NULL', p).fetchone()[0]
            nao_lidas = fora - sum(c['a_confirmar'] for c in contas)
        return {'contas': contas, 'batem': len(contas),
                'preco_min': min(precos) if precos else None,
                'preco_mediana': statistics.median(precos) if precos else None,
                'a_confirmar': sum(c['a_confirmar'] for c in contas), 'nao_lidas': max(0, nao_lidas),
                'busca_itens': condicoes, 'busca_algum': algum}

    @staticmethod
    def _filtro_item(cond, chave, p):
        """Itens (tabela i) que atendem à condição: qual item, refino mínimo e onde ele está.

        De um grupo, vale qualquer item dele (itens, que _resolver_grupos preenche); quando ele exige todos,
        quem confere é _contas_com_item. Sem item_id (item
        digitado, ainda não visto), vale qualquer item com esse texto no nome.
        chave distingue os parâmetros de cada condição na consulta.
        """
        if cond['grupo_id'] is not None:
            ids = ','.join(str(int(i)) for i in cond.get('itens') or ())
            alvo = f'i.item_id IN ({ids})' if ids else '0'
        elif cond['item_id'] is not None:
            alvo = f'i.item_id = :{chave}_id'
            p[f'{chave}_id'] = cond['item_id']
        else:
            alvo = f'i.nome_norm LIKE :{chave}_nome'
            p[f'{chave}_nome'] = f'%{norm(cond["nome"])}%'
        secoes = ONDE.get(cond['onde'])
        onde = (f'i.secao IN ({",".join(repr(s) for s in secoes)})' if secoes else f'i.secao NOT IN ({_FORA})')
        p[f'{chave}_ref'] = cond['refino_min']
        return f'{alvo} AND i.refino >= :{chave}_ref AND {onde}'

    def _contas_com_item(self, cond, chave, p):
        """(filtro dos itens, subconsulta das contas) de uma condição: todas as pilhas somadas atingem a quantidade.

        Num grupo que exige todos os itens, cada item dele precisa atingir a quantidade.
        """
        filtro = self._filtro_item(cond, chave, p)
        p[f'{chave}_qtd'] = cond['qtd_min']
        if cond.get('todos'):
            p[f'{chave}_n'] = len(cond.get('itens') or ())
            return filtro, (f'SELECT anuncio_id FROM (SELECT i.anuncio_id FROM itens i WHERE {filtro} '
                            f'GROUP BY i.anuncio_id, i.item_id HAVING SUM(i.qtd) >= :{chave}_qtd) '
                            f'GROUP BY anuncio_id HAVING COUNT(*) = :{chave}_n')
        return filtro, (f'SELECT i.anuncio_id FROM itens i WHERE {filtro} '
                        f'GROUP BY i.anuncio_id HAVING SUM(i.qtd) >= :{chave}_qtd')

    def _quantidades(self, filtros_item, p):
        """{conta: [unidades de cada item pesquisado]}, somando todas as pilhas que atendem a cada condição."""
        somas = ', '.join(f'SUM(CASE WHEN {w} THEN i.qtd ELSE 0 END)' for w in filtros_item)
        alguma = ' OR '.join(f'({w})' for w in filtros_item)
        return {r[0]: list(r[1:]) for r in self.con.execute(
            f'SELECT i.anuncio_id, {somas} FROM itens i WHERE {alguma} GROUP BY i.anuncio_id', p)}

    # -------------------------------------------------------------- tabela de valores

    def valores(self):
        cfg = self.config()
        linhas = self.con.execute(
            'SELECT v.*, c.tipo, c.efeito, c.no_catalogo FROM valores v LEFT JOIN conhecidos c ON c.item_id = v.item_id '
            'ORDER BY v.nome_norm, v.refino_min DESC').fetchall()
        saida = []
        grupos = self._itens_dos_grupos()
        for r in linhas:
            if r['grupo_id'] is not None:
                itens = grupos.get(r['grupo_id'], [])
                contas, unidades = self.con.execute(
                    f'SELECT COUNT(DISTINCT i.anuncio_id), COALESCE(SUM(i.qtd), 0) FROM itens i '
                    f'JOIN anuncios a ON a.id = i.anuncio_id WHERE a.ativo = 1 AND i.secao NOT IN ({_FORA}) '
                    f'AND i.item_id IN ({_ids_sql(itens)}) AND i.refino >= ?', (r['refino_min'],)).fetchone()
                saida.append({'id': r['id'], 'item_id': None, 'grupo_id': r['grupo_id'], 'itens': itens,
                              'grupo_apagado': r['grupo_id'] not in grupos, 'nome': r['nome'],
                              'refino_min': r['refino_min'], 'valor_kk': r['valor_kk'],
                              'valor_rs': valor.kk_para_rs(r['valor_kk'], cfg['rs_por_bi']), 'tipo': 'grupo',
                              'efeito': '', 'no_catalogo': False, 'visto': True, 'contas': contas, 'unidades': unidades})
                continue
            if r['item_id'] is not None:
                contas, unidades = self._contas_com([r['item_id']], r['refino_min']).get(r['item_id'], (0, 0))
            else:
                contas, unidades = self.con.execute(
                    f'SELECT COUNT(DISTINCT i.anuncio_id), COALESCE(SUM(i.qtd), 0) FROM itens i '
                    f'JOIN anuncios a ON a.id = i.anuncio_id '
                    f'WHERE a.ativo = 1 AND i.secao NOT IN ({_FORA}) AND i.nome_norm = ? AND i.refino >= ?',
                    (r['nome_norm'], r['refino_min'])).fetchone()
            saida.append({'id': r['id'], 'item_id': r['item_id'], 'grupo_id': None, 'nome': r['nome'], 'refino_min': r['refino_min'],
                          'valor_kk': r['valor_kk'], 'valor_rs': valor.kk_para_rs(r['valor_kk'], cfg['rs_por_bi']),
                          'tipo': r['tipo'] or 'item', 'efeito': r['efeito'] or '', 'no_catalogo': bool(r['no_catalogo']),
                          'visto': r['item_id'] is not None, 'contas': contas, 'unidades': unidades})
        return saida

    def salvar_valor(self, dados, valor_id=None):
        """Linha da tabela de valores: de um item (item_id, ou só o nome) ou de um grupo de itens (grupo_id)."""
        grupo_id = _inteiro(dados.get('grupo_id'))
        if grupo_id is not None:
            grupo = next((g for g in self.grupos() if g['id'] == grupo_id), None)
            if grupo is None:
                raise ValueError('Esse grupo não existe mais.')
            dados = {**dados, 'nome': grupo['nome'], 'item_id': None}
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
        if item_id is None and grupo_id is None:
            r = self.con.execute('SELECT item_id FROM conhecidos WHERE nome_norm = ? ORDER BY no_catalogo DESC LIMIT 1',
                                 (nome_norm,)).fetchone()
            item_id = r['item_id'] if r else None
        quando = agora()
        with self._mudando_dados(), self._transacao() as con:
            if grupo_id is not None:
                dup = con.execute('SELECT id FROM valores WHERE grupo_id = ? AND refino_min = ? AND id IS NOT ?',
                                  (grupo_id, refino_min, valor_id)).fetchone()
            elif item_id is not None:
                dup = con.execute('SELECT id FROM valores WHERE item_id = ? AND refino_min = ? AND id IS NOT ?',
                                  (item_id, refino_min, valor_id)).fetchone()
            else:
                dup = con.execute('SELECT id FROM valores WHERE item_id IS NULL AND grupo_id IS NULL AND nome_norm = ? '
                                  'AND refino_min = ? AND id IS NOT ?', (nome_norm, refino_min, valor_id)).fetchone()
            if dup:
                raise ValueError(f'Esse {"grupo" if grupo_id is not None else "item"} já tem um valor para essa faixa de refino.')
            if valor_id:
                cur = con.execute('UPDATE valores SET item_id=?, grupo_id=?, nome=?, nome_norm=?, refino_min=?, '
                                  'valor_kk=?, atualizado_em=? WHERE id=?',
                                  (item_id, grupo_id, nome, nome_norm, refino_min, valor_kk, quando, valor_id))
                if cur.rowcount == 0:
                    raise KeyError(valor_id)
            else:
                valor_id = con.execute('INSERT INTO valores (item_id, grupo_id, nome, nome_norm, refino_min, valor_kk, '
                                       'criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?)',
                                       (item_id, grupo_id, nome, nome_norm, refino_min, valor_kk, quando, quando)).lastrowid
        self.recalcular()
        return valor_id

    def apagar_valor(self, valor_id):
        with self._mudando_dados(), self._transacao() as con:
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

    # -------------------------------------------------------------- grupos de itens

    def grupos(self):
        """Grupos de itens (ex.: as armas de um rank, que têm um nome em cada classe), para usar nas buscas."""
        return [{**dict(r), 'itens': json.loads(r['itens'])}
                for r in self.con.execute('SELECT id, nome, itens, criado_em, atualizado_em FROM grupos ORDER BY nome, id')]

    def salvar_grupo(self, dados, grupo_id=None):
        nome = str(dados.get('nome') or '').strip()
        if not nome:
            raise ValueError('Dê um nome para o grupo.')
        itens = json.dumps(_itens_do_grupo(dados.get('itens')), ensure_ascii=False)
        quando = agora()
        with self._mudando_dados(), self._transacao() as con:
            if con.execute('SELECT 1 FROM grupos WHERE nome = ? AND id IS NOT ?', (nome, grupo_id)).fetchone():
                raise ValueError('Já existe um grupo com esse nome.')
            if grupo_id:
                if con.execute('UPDATE grupos SET nome=?, itens=?, atualizado_em=? WHERE id=?',
                               (nome, itens, quando, grupo_id)).rowcount == 0:
                    raise KeyError(grupo_id)
                # os valores do grupo acompanham o nome (a tabela de valores mostra o nome guardado)
                con.execute('UPDATE valores SET nome=?, nome_norm=?, atualizado_em=? WHERE grupo_id=? AND nome != ?',
                            (nome, norm(nome), quando, grupo_id, nome))
            else:
                grupo_id = con.execute('INSERT INTO grupos (nome, itens, criado_em, atualizado_em) VALUES (?,?,?,?)',
                                       (nome, itens, quando, quando)).lastrowid
        if self._grupo_tem_valor(grupo_id):  # os itens do grupo podem ter mudado
            self.recalcular()
        return grupo_id

    def apagar_grupo(self, grupo_id):
        """As buscas que usam o grupo continuam salvas, mas a condição dele não acha mais nenhuma conta.
        Os valores do grupo saem da tabela."""
        tinha_valor = self._grupo_tem_valor(grupo_id)
        with self._mudando_dados(), self._transacao() as con:
            con.execute('DELETE FROM grupos WHERE id = ?', (grupo_id,))
            con.execute('DELETE FROM valores WHERE grupo_id = ?', (grupo_id,))
        if tinha_valor:
            self.recalcular()

    def _grupo_tem_valor(self, grupo_id):
        return self.con.execute('SELECT 1 FROM valores WHERE grupo_id = ? LIMIT 1', (grupo_id,)).fetchone() is not None

    def _resolver_grupos(self, condicoes, todos=False):
        """As condições de grupo ganham os item_ids do grupo (e o nome atual dele); grupo apagado não acha nada.

        todos: a conta precisa ter todos os itens do grupo ("Tem item"), não um só ("Tem pelo menos um").
        """
        if any(c['grupo_id'] is not None for c in condicoes):
            grupos = {g['id']: g for g in self.grupos()}
            for c in condicoes:
                if c['grupo_id'] is not None:
                    g = grupos.get(c['grupo_id'])
                    c['itens'] = [it['item_id'] for it in g['itens']] if g else []
                    c['nome'] = g['nome'] if g else c['nome']
                    c['todos'] = todos
        return condicoes

    # -------------------------------------------------------------- favoritas

    def ids_favoritas(self):
        return {r[0] for r in self.con.execute('SELECT id FROM favoritas')}

    def favoritas(self):
        """As favoritas com a situação neste PC e o anúncio (None se este PC nunca viu a conta).

        Primeiro as que estão confirmando venda; depois as que mudaram de situação por último.
        """
        cfg = self.config()
        saida = []
        for f in self.con.execute('SELECT f.id, f.nome, f.criado_em, s.situacao, s.desde, s.sumiu_em, s.visto_antes, '
                                  's.tentativas, s.proxima_em FROM favoritas f '
                                  'LEFT JOIN situacao_favoritas s ON s.id = f.id').fetchall():
            a = self.anuncio(f['id'])
            situacao = {k: f[k] for k in ('situacao', 'desde', 'sumiu_em', 'visto_antes', 'tentativas', 'proxima_em')}
            saida.append({'id': f['id'], 'nome': a['nome'] if a else f['nome'], 'criado_em': f['criado_em'],
                          'situacao': situacao if f['situacao'] else None,
                          'anuncio': self._publico(a, cfg) if a else None,
                          'ultimo_visto': a['ultimo_visto'] if a else None})
        saida.sort(key=lambda x: x['situacao']['desde'] if x['situacao'] else x['criado_em'], reverse=True)
        saida.sort(key=lambda x: (x['situacao'] or {}).get('situacao') != 'confirmando')
        return saida

    def situacao_favorita(self, anuncio_id):
        r = self.con.execute('SELECT * FROM situacao_favoritas WHERE id = ?', (anuncio_id,)).fetchone()
        return dict(r) if r else None

    def marcar_favorita(self, anuncio_id):
        """Marca a conta como favorita; o nome vem do anúncio. Uma que já saiu do ar começa conferindo se foi vendida."""
        a = self.anuncio(anuncio_id)
        if a is None:
            raise KeyError(anuncio_id)
        quando = agora()
        with self._mudando_dados(), self._transacao() as con:
            if con.execute('SELECT 1 FROM favoritas WHERE id = ?', (anuncio_id,)).fetchone():
                return
            con.execute('INSERT INTO favoritas (id, nome, criado_em, atualizado_em) VALUES (?,?,?,?)',
                        (anuncio_id, a['nome'], quando, quando))
            con.execute('DELETE FROM situacao_favoritas WHERE id = ?', (anuncio_id,))
            if a['ativo']:
                con.execute("INSERT INTO situacao_favoritas (id, situacao, desde) VALUES (?, 'a_venda', ?)",
                            (anuncio_id, quando))
            else:
                con.execute("INSERT INTO situacao_favoritas (id, situacao, desde, sumiu_em, visto_antes, proxima_em) "
                            "VALUES (?, 'confirmando', ?, ?, ?, ?)", (anuncio_id, quando, quando, a['ultimo_visto'], quando))

    def desmarcar_favorita(self, anuncio_id):
        with self._mudando_dados(), self._transacao() as con:
            con.execute('DELETE FROM favoritas WHERE id = ?', (anuncio_id,))
            con.execute('DELETE FROM situacao_favoritas WHERE id = ?', (anuncio_id,))

    def esquecer_vendida(self, anuncio_id):
        """Favorita vendida: deixa de ser favorita (também no meus-dados.json), e a situação e os itens dela são apagados.

        ValueError se o meus-dados.json não aceita mudanças agora (erro ou conflito do git).
        """
        with self._mudando_dados(), self._transacao() as con:
            con.execute('DELETE FROM favoritas WHERE id = ?', (anuncio_id,))
            con.execute('DELETE FROM situacao_favoritas WHERE id = ?', (anuncio_id,))
            _apagar_itens(con, [anuncio_id])

    def definir_situacao(self, anuncio_id, situacao, sumiu_em=None, visto_antes=None, proxima_em=None):
        """Nova situação de uma favorita neste PC. False se ela deixou de ser favorita nesse meio-tempo."""
        with self._transacao() as con:
            if not con.execute('SELECT 1 FROM favoritas WHERE id = ?', (anuncio_id,)).fetchone():
                return False
            con.execute('INSERT OR REPLACE INTO situacao_favoritas (id, situacao, desde, sumiu_em, visto_antes, '
                        'tentativas, proxima_em) VALUES (?,?,?,?,?,0,?)',
                        (anuncio_id, situacao, agora(), sumiu_em, visto_antes, proxima_em))
            return True

    def agendar_busca_de_venda(self, anuncio_id, tentativas, proxima_em):
        with self._transacao() as con:
            con.execute('UPDATE situacao_favoritas SET tentativas = ?, proxima_em = ? WHERE id = ?',
                        (tentativas, proxima_em, anuncio_id))

    def buscas_de_venda(self, ate=None):
        """Favoritas confirmando venda cuja próxima busca no histórico está na hora (até `ate`), as mais atrasadas antes."""
        return [dict(r) for r in self.con.execute(
            "SELECT s.*, COALESCE(a.nome, f.nome) AS nome FROM situacao_favoritas s JOIN favoritas f ON f.id = s.id "
            "LEFT JOIN anuncios a ON a.id = s.id WHERE s.situacao = 'confirmando' AND s.proxima_em <= ? "
            "ORDER BY s.proxima_em", (ate or agora(),))]

    def proxima_busca_de_venda(self):
        """Quando é a próxima busca no histórico (ISO), ou None."""
        return self.con.execute("SELECT MIN(proxima_em) FROM situacao_favoritas WHERE situacao = 'confirmando'").fetchone()[0]

    def registrar_aviso_favorita(self, anuncio_id, nome, evento, texto, preco=None):
        with self._transacao() as con:
            con.execute('INSERT INTO avisos_favoritas (anuncio_id, nome, evento, texto, preco, quando) VALUES (?,?,?,?,?,?)',
                        (anuncio_id, nome, evento, texto, preco, agora()))

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
        with self._mudando_dados(), self._transacao() as con:
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
        with self._mudando_dados(), self._transacao() as con:
            con.execute('DELETE FROM avisos WHERE busca_id = ?', (busca_id,))
            con.execute('DELETE FROM buscas WHERE id = ?', (busca_id,))

    def registrar_aviso(self, busca_id, anuncio_id, preco, lucro_rs, motivo):
        """True se o aviso é inédito (mesma busca + conta + preço só avisa uma vez)."""
        with self._transacao() as con:
            cur = con.execute('INSERT OR IGNORE INTO avisos (busca_id, anuncio_id, preco, lucro_rs, motivo, quando) '
                              'VALUES (?,?,?,?,?,?)', (busca_id, anuncio_id, preco, lucro_rs, motivo, agora()))
            return cur.rowcount == 1

    def avisos(self, limite=100):
        """Os últimos avisos, das buscas e das favoritas juntos, dos mais recentes aos mais antigos."""
        das_buscas = [dict(r) for r in self.con.execute(
            'SELECT v.*, b.nome AS busca, a.nome AS conta, a.classe, a.nivel, a.ativo '
            'FROM avisos v JOIN buscas b ON b.id = v.busca_id LEFT JOIN anuncios a ON a.id = v.anuncio_id '
            'ORDER BY v.id DESC LIMIT ?', (limite,))]
        das_favoritas = [{**dict(r), 'busca_id': None, 'busca': '★ Favorita', 'lucro_rs': None} for r in self.con.execute(
            'SELECT v.id, v.anuncio_id, v.evento, v.texto AS motivo, v.preco, v.quando, v.nome AS conta, a.classe, '
            'a.nivel, a.ativo FROM avisos_favoritas v LEFT JOIN anuncios a ON a.id = v.anuncio_id '
            'ORDER BY v.id DESC LIMIT ?', (limite,))]
        return sorted(das_buscas + das_favoritas, key=lambda v: v['quando'], reverse=True)[:limite]

    def ultimos_avisos_por_busca(self):
        return {r[0]: r[1] for r in self.con.execute('SELECT busca_id, MAX(quando) FROM avisos GROUP BY busca_id')}


def _ha_24h():
    return (datetime.now() - timedelta(hours=24)).isoformat(timespec='seconds')


def _apagar_itens(con, ids):
    """Apaga os itens lidos das contas (os tooltips que ficarem sem uso saem no próximo limpar_antigos)."""
    con.executemany('DELETE FROM itens WHERE anuncio_id = ?', [(i,) for i in ids])
    con.executemany('UPDATE anuncios SET itens_lidos_em = NULL, preco_lido = NULL, valor_kk = NULL, '
                    'destaques = NULL WHERE id = ?', [(i,) for i in ids])
