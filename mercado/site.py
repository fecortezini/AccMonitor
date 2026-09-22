"""Leitura do Marketplace The Classic (PW 1.8.7).

Tudo o que depende do HTML ou do JSON do site fica aqui: a lista de anúncios, a
página de cada conta, o catálogo de equipamentos e a busca avançada do próprio site.
"""
import gzip
import html
import http.client
import json
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

SITE = 'https://marketplace.theclassic.games'
URL_LISTA = f'{SITE}/pw187'
URL_CONTA = SITE + '/pw187/details/{}'
URL_CATALOGO = f'{SITE}/pw187/advanced_item_list'
URL_BUSCA = f'{SITE}/pw187/advanced_filter'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
COSMOS_ID = 72573

# Abas da página da conta -> seção guardada no banco
SECOES = {
    'bag': 'inventario', 'quest': 'missoes', 'bank': 'banco', 'cards': 'cartas',
    'warehouse': 'guarda-roupa', 'material': 'materiais', 'runes': 'runas',
    'celestial': 'infante celestial', 'pangu': 'pangu', 'pets': 'mascotes',
    'codex': 'codice', 'fashion': 'codice', 'petinv': 'codice', 'flight': 'codice',
    'ornamental': 'codice', 'extra': 'recompra', 'lottery': 'recompra',
    'transmute': 'transmutacao',
}
# Títulos das seções do topo da aba Inventário. "Cartas equipadas" repete as
# cartas que já aparecem em "Equipamento", por isso é ignorada (None).
TITULOS = {'equipamento': 'equipado', 'cartas equipadas': None, 'repositorio': None}

# Início do efeito de uma pedra engastada ("Pedra do Demônio Nível de Ataque +3")
_EFEITO = re.compile(
    r'\s(?=(?:Nível|Ataque|Atq|Defesa|Def|HP|MP|Precisão|Esquiva|Crítico|Chance|Força|'
    r'Destreza|Inteligência|Constituição|Espírito|Canalização|Velocidade|Alcance|Redução|'
    r'Resistência|Dano|Vitalidade|Energia|Taxa|Magia|Recuperação)\b)')


def norm(texto):
    """Minúsculas, sem acentos e com espaços normalizados, para comparar nomes."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().lower()


_PROXY = urllib.request.getproxies().get('https')  # com proxy configurado no Windows, baixa pelo urllib
_conexao = threading.local()                        # conexão de cada thread com o site, reaproveitada


def baixar(url, timeout=40):
    """Texto da página.

    Reaproveita a conexão da página anterior: abrir uma conexão segura com o site leva
    ~0,6 s, quase o tempo que o servidor leva para montar a página de uma conta.
    """
    if _PROXY:
        return _baixar_urllib(url, timeout)
    for _ in range(5):  # segue até 5 redirecionamentos, como o urllib
        resp, dados = _pedir(url, timeout)
        destino = resp.getheader('Location')
        if resp.status in (301, 302, 303, 307, 308) and destino:
            url = urllib.parse.urljoin(url, destino)
            continue
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)
        if resp.getheader('Content-Encoding') == 'gzip':
            dados = gzip.decompress(dados)
        return dados.decode('utf-8', 'replace')
    raise urllib.error.URLError(f'redirecionamentos demais: {url}')


def _pedir(url, timeout):
    """(resposta, corpo) de um GET na conexão guardada desta thread, ou numa nova."""
    partes = urllib.parse.urlsplit(url)
    caminho = (partes.path or '/') + (f'?{partes.query}' if partes.query else '')
    chave = (partes.scheme, partes.netloc)
    for tentativa in (1, 2):
        con = getattr(_conexao, 'con', None)
        reaproveitada = con is not None and _conexao.chave == chave
        if not reaproveitada:
            if con is not None:
                con.close()
            classe = http.client.HTTPSConnection if partes.scheme == 'https' else http.client.HTTPConnection
            con = _conexao.con = classe(partes.netloc, timeout=timeout)
            _conexao.chave = chave
        elif con.sock is not None:
            con.sock.settimeout(timeout)
        try:
            con.request('GET', caminho, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
            resp = con.getresponse()
            dados = resp.read()
        except Exception as e:
            con.close()
            _conexao.con = None
            # o site fecha a conexão que fica parada; nesse caso tenta de novo uma vez, numa conexão nova
            if reaproveitada and tentativa == 1 and isinstance(e, ConnectionError):
                continue
            raise
        if resp.will_close:
            con.close()
            _conexao.con = None
        return resp, dados


def _baixar_urllib(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dados = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            dados = gzip.decompress(dados)
    return dados.decode('utf-8', 'replace')


def baixar_json(url, timeout=40):
    return json.loads(baixar(url, timeout))


# ------------------------------------------------------------------ lista de anúncios

@dataclass
class Anuncio:
    id: int
    preco: int
    nivel: int
    ocupacao: int
    nome: str
    classe: str
    ceu: str


def ler_lista(pagina):
    """{id: Anuncio} com todos os cards da página do PW 1.8.7, inclusive os ocultos."""
    anuncios = {}
    for bloco in pagina.split('<li class="character-card')[1:]:
        attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', bloco[:bloco.find('>')]))
        if not attrs.get('roleid', '').isdigit() or not attrs.get('price', '').isdigit():
            continue

        def campo(padrao):
            m = re.search(padrao, bloco, re.S)
            return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''

        rid = int(attrs['roleid'])
        anuncios[rid] = Anuncio(
            id=rid,
            preco=int(attrs['price']),
            nivel=int(attrs.get('level') or 0),
            ocupacao=int(attrs.get('occupation') or 0),
            nome=campo(r'class="item-name">(.*?)</dd>'),
            classe=campo(r'class="item-type">(.*?)</dd>'),
            ceu=campo(r'class="display-score">.*?<dd>(.*?)</dd>'),
        )
    return anuncios


# ------------------------------------------------------------------ página da conta

@dataclass
class Item:
    secao: str
    item_id: int | None
    nome: str
    refino: int = 0
    qtd: int = 1
    efeito: str = ''                              # só pedras engastadas
    tooltip: list = field(default_factory=list)   # linhas de segmentos, ver _Tooltip


class _No:
    __slots__ = ('tag', 'attrs', 'pai', 'filhos', 'texto')

    def __init__(self, tag, attrs, pai, texto=''):
        self.tag, self.attrs, self.pai, self.texto, self.filhos = tag, attrs, pai, texto, []

    def nos(self):
        pilha = [self]
        while pilha:
            no = pilha.pop()
            yield no
            pilha.extend(reversed(no.filhos))

    def conteudo(self):
        return ''.join(no.texto for no in self.nos())


class _Arvore(HTMLParser):
    VAZIAS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
              'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = self.atual = _No('#raiz', {}, None)

    def handle_starttag(self, tag, attrs):
        no = _No(tag, dict(attrs), self.atual)
        self.atual.filhos.append(no)
        if tag not in self.VAZIAS:
            self.atual = no

    def handle_endtag(self, tag):
        no = self.atual
        while no is not None and no.tag != tag:
            no = no.pai
        if no is not None and no.pai is not None:
            self.atual = no.pai

    def handle_data(self, data):
        self.atual.filhos.append(_No(None, {}, self.atual, data))


def _cor(style):
    m = re.search(r'(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b|rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\))',
                  style or '')
    if not m:
        return None
    if m.group(1).startswith('#'):
        cor = m.group(1).lower()
        return cor if len(cor) == 7 else '#' + ''.join(c * 2 for c in cor[1:])
    return '#{:02x}{:02x}{:02x}'.format(*(min(255, int(m.group(i))) for i in (2, 3, 4)))


class _Tooltip(HTMLParser):
    """Converte o HTML do tooltip em linhas de segmentos: [texto, cor] ou {"i": id do ícone}.

    Guarda só texto e cor, nada de HTML. As imagens dentro do tooltip são as pedras
    engastadas: ficam em self.pedras como (id do ícone, texto da linha).
    """
    FECHAVEIS = {'span', 'strong', 'b', 'font', 'em', 'i', 'u', 'div', 'p', 'a'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.linhas = [[]]
        self.pilha = []      # (tag, cor)
        self.pedras = []
        self._pedra = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'br':
            self._fecha_pedra()
            self.linhas.append([])
        elif tag == 'img':
            m = re.search(r'/(\d+)\.png', a.get('src') or '')
            if m:
                self._fecha_pedra()
                self.linhas[-1].append({'i': int(m.group(1))})
                self._pedra = [int(m.group(1)), '']
        elif tag in self.FECHAVEIS:
            self.pilha.append((tag, _cor(a.get('style'))))

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                break
        if tag == 'span':
            self._fecha_pedra()

    def handle_data(self, data):
        texto = data.replace('\r', '').replace('\n', '')
        if not texto:
            return
        cor = next((c for _, c in reversed(self.pilha) if c), None)
        linha = self.linhas[-1]
        if linha and isinstance(linha[-1], list) and linha[-1][1] == cor:
            linha[-1][0] += texto
        else:
            linha.append([texto, cor])
        if self._pedra is not None:
            self._pedra[1] += texto

    def _fecha_pedra(self):
        if self._pedra is not None:
            self.pedras.append((self._pedra[0], ' '.join(self._pedra[1].split())))
            self._pedra = None

    def resultado(self):
        self._fecha_pedra()
        linhas = []
        for linha in self.linhas:
            limpa = []
            for seg in linha:
                if isinstance(seg, list):
                    if not limpa or isinstance(limpa[-1], dict):  # começo da linha ou logo após um ícone
                        seg = [seg[0].lstrip(), seg[1]]
                    if not seg[0]:
                        continue
                limpa.append(seg)
            if limpa and not all(isinstance(s, list) and not s[0].strip() for s in limpa):
                linhas.append(limpa)
        return linhas


def ler_tooltip(tooltip_html):
    """(linhas, pedras) de um tooltip do site. Ver _Tooltip."""
    leitor = _Tooltip()
    leitor.feed(tooltip_html or '')
    leitor.close()
    return leitor.resultado(), leitor.pedras


def separar_pedra(texto):
    """("Pedra do Demônio", "Nível de Ataque +3") a partir da linha da pedra no tooltip."""
    texto = ' '.join(texto.split())
    m = _EFEITO.search(texto)
    nome, efeito = (texto[:m.start()], texto[m.start() + 1:]) if m else (texto, '')
    return nome.rstrip(' :'), efeito


def _secao(no):
    """Seção do item na página, ou None para o que deve ser ignorado (boneco do topo, repetidos)."""
    while no is not None:
        a = no.attrs
        if 'character-equip__wrapper' in (a.get('class') or '').split():
            return None
        chave = a.get('data-pw187-subpanel') or a.get('data-pw187-panel')
        if chave:
            return SECOES.get(chave, chave)
        if no.tag == 'section':
            for filho in no.filhos:
                if filho.tag == 'h4':
                    titulo = norm(filho.conteudo())
                    return TITULOS.get(titulo, titulo)
        no = no.pai
    return 'outros'


def ler_conta(pagina):
    """Itens da conta, inclusive as pedras engastadas (seção "engastada")."""
    arvore = _Arvore()
    arvore.feed(pagina)
    arvore.close()
    itens, usados = [], set()
    for no in arvore.raiz.nos():
        a = no.attrs
        if 'data-item' in a:
            try:
                dados = json.loads(a['data-item'])
            except ValueError:
                dados = {}
            img = next((n for n in no.nos() if 'data-pw187-tooltip' in n.attrs), None)
            if img is not None:
                usados.add(id(img))
        elif 'data-pw187-tooltip' in a and id(no) not in usados:
            dados, img = {}, no
        else:
            continue
        secao = _secao(no)
        if secao is None:
            continue
        ia = img.attrs if img is not None else {}
        linhas, pedras = ler_tooltip(ia.get('data-pw187-tooltip'))
        primeira = ''.join(s[0] for s in linhas[0] if isinstance(s, list)) if linhas else ''
        refino = dados.get('refine_level')
        if refino is None:
            m = re.search(r'\s\+(\d+)$', primeira)
            refino = int(m.group(1)) if m else 0
        item_id = dados.get('id')
        if item_id is None:
            m = re.search(r'/(\d+)\.png', ia.get('src') or '')
            item_id = int(m.group(1)) if m else None
        nome = dados.get('name') or ia.get('data-item-name') or ia.get('alt') or primeira
        itens.append(Item(secao=secao, item_id=int(item_id) if item_id is not None else None,
                          nome=html.unescape(nome).strip(), refino=int(refino or 0),
                          qtd=max(1, int(dados.get('count') or 1)), tooltip=linhas))
        for (pedra_id, texto), qtd in Counter(pedras).items():
            nome_pedra, efeito = separar_pedra(texto)
            if efeito:  # imagem sem efeito não é pedra
                itens.append(Item(secao='engastada', item_id=pedra_id, nome=nome_pedra,
                                  qtd=qtd, efeito=efeito))
    return itens


# ------------------------------------------------------------------ catálogo e busca do site

def catalogo():
    """Equipamentos que a busca do site conhece: [{item_id, nome, grupo}]."""
    dados = baixar_json(URL_CATALOGO)
    return [{'item_id': int(it['item_id']), 'nome': str(it.get('item_name') or '').strip(),
             'grupo': (it.get('mask_groups') or [''])[0]}
            for it in dados.get('items', []) if str(it.get('item_id', '')).isdigit()]


def busca_site(item_ids=(), cosmos_min=None):
    """IDs das contas que a busca do site devolve.

    Vários item_ids são combinados com OU. cosmos_min filtra o refino do Cosmos.
    """
    params = {}
    if item_ids:
        params['item_ids'] = ','.join(str(i) for i in sorted(set(item_ids)))
    if cosmos_min is not None:
        params['g17_book_min'] = str(int(cosmos_min))
    dados = baixar_json(URL_BUSCA + '?' + urllib.parse.urlencode(params))
    return {int(r) for r in dados.get('roleids', []) if str(r).isdigit()}
