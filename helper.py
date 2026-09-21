#!/usr/bin/env python3
"""Helper do Marketplace The Classic (PW 1.8.7).

Vigia https://marketplace.theclassic.games/pw187 e avisa quando aparece um
personagem (anúncio novo ou com preço reduzido) que bate com os filtros de filtros.toml.

    py helper.py                  vigia sem parar (Ctrl+C para sair)
    py helper.py --uma-vez        faz uma verificação e sai
    py helper.py --varrer         confere também os anúncios que já estão no ar
    py helper.py --testar 45520   mostra quais filtros batem com um anúncio
    py helper.py --itens 45520    lista os itens de um anúncio (para montar filtros)
    py helper.py --testar-aviso   dispara um aviso de teste

Só usa a biblioteca padrão do Python (3.11+).
"""
import argparse
import base64
import gzip
import html
import json
import random
import re
import subprocess
import sys
import time
import tomllib
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape

SITE = 'https://marketplace.theclassic.games'
URL_LISTA = f'{SITE}/pw187'
URL_ANUNCIO = SITE + '/pw187/details/{}'
PASTA = Path(__file__).resolve().parent
ARQ_FILTROS = PASTA / 'filtros.toml'
ARQ_ESTADO = PASTA / 'estado.json'
ARQ_ALERTAS = PASTA / 'alertas.log'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')

# Abas da página do anúncio -> nome usado no campo "onde" dos filtros
SECOES = {
    'bag': 'inventario', 'quest': 'missoes', 'bank': 'banco', 'cards': 'cartas',
    'warehouse': 'guarda-roupa', 'material': 'materiais', 'runes': 'runas',
    'celestial': 'infante celestial', 'pangu': 'pangu', 'pets': 'mascotes',
    'codex': 'codice', 'fashion': 'codice', 'petinv': 'codice', 'flight': 'codice',
    'ornamental': 'codice', 'extra': 'extra', 'lottery': 'recompra',
    'transmute': 'transmutacao',
}
TITULOS = {'equipamento': 'equipado'}


def log(msg):
    print(f'[{datetime.now():%H:%M:%S}] {msg}', flush=True)


def norm(texto):
    """Minúsculas, sem acentos e com espaços normalizados, para comparar nomes."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().lower()


def tcc(valor):
    return f'{valor:,}'.replace(',', '.') + ' TCC'


def como_lista(valor):
    if valor is None or valor == '':
        return []
    return valor if isinstance(valor, list) else [valor]


def baixar(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(req, timeout=40) as resp:
        dados = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            dados = gzip.decompress(dados)
    return dados.decode('utf-8', 'replace')


# ------------------------------------------------------------------ lista de anúncios

def ler_anuncios(pagina):
    """{id: anúncio} com todos os cards da página do PW 1.8.7 (inclusive os ocultos)."""
    anuncios = {}
    for bloco in pagina.split('<li class="character-card')[1:]:
        attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', bloco[:bloco.find('>')]))
        if 'roleid' not in attrs or 'price' not in attrs:
            continue

        def campo(padrao):
            m = re.search(padrao, bloco, re.S)
            return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''

        anuncios[attrs['roleid']] = {
            'id': attrs['roleid'],
            'preco': int(attrs['price']),
            'nivel': int(attrs.get('level') or 0),
            'nome': campo(r'class="item-name">(.*?)</dd>'),
            'classe': campo(r'class="item-type">(.*?)</dd>'),
            'ceu': campo(r'class="display-score">.*?<dd>(.*?)</dd>'),
        }
    return anuncios


# ------------------------------------------------------------------ página do anúncio

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


def _secao(no):
    """Em qual aba/seção da página o item está (None = boneco do topo, que é repetido)."""
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


def _texto_tooltip(tooltip):
    texto = re.sub(r'<br\s*/?>', '\n', tooltip or '', flags=re.I)
    texto = html.unescape(re.sub(r'<[^>]+>', '', texto))
    return '\n'.join(linha.strip() for linha in texto.splitlines() if linha.strip())


def ler_itens(pagina):
    """Itens do personagem: nome, refino, qtd, seção e o texto completo do tooltip."""
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
        texto = _texto_tooltip(ia.get('data-pw187-tooltip'))
        primeira = texto.split('\n', 1)[0]
        refino = dados.get('refine_level')
        if refino is None:
            m = re.search(r'\s\+(\d+)$', primeira)
            refino = int(m.group(1)) if m else 0
        itens.append({
            'nome': dados.get('name') or ia.get('data-item-name') or ia.get('alt') or primeira,
            'refino': int(refino or 0),
            'qtd': int(dados.get('count') or 1),
            'secao': secao,
            'texto': texto,
        })
    return itens


# ------------------------------------------------------------------ filtros

def falha_basica(filtro, an):
    """Confere o que dá para saber só pela lista. Devolve o motivo da recusa, ou None."""
    if an['preco'] > filtro.get('preco_max', float('inf')):
        return f"preço {tcc(an['preco'])} acima de {tcc(filtro['preco_max'])}"
    if an['preco'] < filtro.get('preco_min', 0):
        return f"preço {tcc(an['preco'])} abaixo de {tcc(filtro['preco_min'])}"
    if an['nivel'] < filtro.get('nivel_min', 0):
        return f"nível {an['nivel']} abaixo de {filtro['nivel_min']}"
    classes = [norm(c) for c in como_lista(filtro.get('classes'))]
    if classes and norm(an['classe']) not in classes:
        return f"classe {an['classe']}"
    if filtro.get('ceu') and norm(filtro['ceu']) not in norm(an['ceu']):
        return f"céu {an['ceu']}"
    return None


def itens_que_batem(req, itens):
    nome, texto = norm(req.get('nome')), norm(req.get('texto'))
    onde = [norm(o) for o in como_lista(req.get('onde'))]
    achados = [it for it in itens
               if nome in norm(it['nome'])
               and it['refino'] >= req.get('refino_min', 0)
               and (not onde or any(o in norm(it['secao']) for o in onde))
               and (not texto or texto in norm(it['texto']))]
    return achados if sum(it['qtd'] for it in achados) >= req.get('qtd_min', 1) else []


def conferir(filtro, an, itens_do_anuncio):
    """(True, [(req, itens)]) se o anúncio bate com o filtro; senão (False, motivo).

    itens_do_anuncio só é chamada (baixando a página) se o filtro exigir itens.
    """
    motivo = falha_basica(filtro, an)
    if motivo:
        return False, motivo
    reqs = filtro.get('itens') or []
    if not reqs:
        return True, []
    itens = itens_do_anuncio()
    resultado = [(req, itens_que_batem(req, itens)) for req in reqs]
    achados = [(req, its) for req, its in resultado if its]
    faltam = [req.get('nome') or req.get('texto') or '?' for req, its in resultado if not its]
    if filtro.get('modo', 'todos') == 'qualquer':
        return (True, achados) if achados else (False, 'não tem nenhum dos itens')
    return (True, achados) if not faltam else (False, 'não tem: ' + ', '.join(faltam))


def descrever(req, its):
    if req.get('qtd_min', 1) > 1:
        return f"{its[0]['nome']}: {sum(i['qtd'] for i in its):,} no total".replace(',', '.')
    partes = []
    for it in its[:3]:
        nome = it['nome'] + (f" +{it['refino']}" if it['refino'] else '') + (f" x{it['qtd']}" if it['qtd'] > 1 else '')
        partes.append(f"{nome} ({it['secao']})")
    if len(its) > 3:
        partes.append(f'e mais {len(its) - 3}')
    return ', '.join(partes)


# ------------------------------------------------------------------ avisos

def aviso_windows(titulo, linha1, linha2, url):
    """Notificação do Windows que fica na tela até ser fechada; clicar abre o anúncio."""
    def x(s):
        return escape(s, {'"': '&quot;'})
    xml = (f'<toast activationType="protocol" launch="{x(url)}" scenario="reminder">'
           f'<visual><binding template="ToastGeneric"><text>{x(titulo)}</text>'
           f'<text>{x(linha1)}</text><text>{x(linha2)}</text></binding></visual>'
           f'<actions><action content="Abrir anúncio" activationType="protocol" arguments="{x(url)}"/>'
           '<action content="Fechar" activationType="system" arguments="dismiss"/></actions></toast>')
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$xml.LoadXml('{xml.replace(chr(39), chr(39) * 2)}')\n"
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($xml))\n")
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                        base64.b64encode(script.encode('utf-16-le')).decode()],
                       capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace').strip()[:300])


def aviso_som():
    """Bipes que tocam mesmo com o 'Não perturbe' do Windows ligado (ex.: jogando)."""
    import winsound
    for _ in range(3):
        winsound.Beep(1200, 250)
        time.sleep(0.1)


def aviso_telegram(token, chat_id, texto):
    dados = urllib.parse.urlencode({'chat_id': chat_id, 'text': texto,
                                    'disable_web_page_preview': 'true'}).encode()
    urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', data=dados, timeout=20).close()


def aviso_discord(webhook, texto):
    req = urllib.request.Request(webhook, data=json.dumps({'content': texto}).encode(),
                                 headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    urllib.request.urlopen(req, timeout=20).close()


def enviar(cfg, titulo, linha1, linha2, texto, url):
    av = cfg.get('aviso', {})
    canais = []
    if av.get('windows', True):
        canais.append(('Windows', lambda: aviso_windows(titulo, linha1, linha2, url)))
    if av.get('som', True):
        canais.append(('som', aviso_som))
    if av.get('telegram_token') and av.get('telegram_chat_id'):
        canais.append(('Telegram', lambda: aviso_telegram(av['telegram_token'], str(av['telegram_chat_id']), texto)))
    if av.get('discord_webhook'):
        canais.append(('Discord', lambda: aviso_discord(av['discord_webhook'], texto)))
    if av.get('abrir_navegador'):
        canais.append(('navegador', lambda: webbrowser.open(url)))
    for nome, fn in canais:
        try:
            fn()
        except Exception as e:
            log(f'Não consegui avisar pelo {nome}: {e}')


def avisar(cfg, an, filtro, motivo, achados):
    url = URL_ANUNCIO.format(an['id'])
    personagem = f"{an['nome']} · {an['classe']} nv {an['nivel']}" + (f" · Céu {an['ceu']}" if an['ceu'] else '')
    itens = [descrever(req, its) for req, its in achados]
    texto = '\n'.join([f"🔔 {filtro.get('nome', 'Filtro')}", personagem,
                       f"{tcc(an['preco'])} ({motivo})", *(f'✔ {i}' for i in itens), url])
    print('\n' + texto + '\n', flush=True)
    with open(ARQ_ALERTAS, 'a', encoding='utf-8') as arq:
        arq.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] ' + texto.replace('\n', ' | ') + '\n')
    enviar(cfg, f"{tcc(an['preco'])} · {filtro.get('nome', 'Filtro')}", personagem,
           '; '.join(itens) or motivo, texto, url)


# ------------------------------------------------------------------ vigia

def carregar_filtros():
    with open(ARQ_FILTROS, 'rb') as arq:
        return tomllib.load(arq)


def filtros_ativos(cfg):
    return [f for f in cfg.get('filtro', []) if f.get('ativo', True)]


def carregar_estado():
    try:
        return json.loads(ARQ_ESTADO.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}


def salvar_estado(estado):
    tmp = ARQ_ESTADO.with_suffix('.tmp')
    tmp.write_text(json.dumps(estado, ensure_ascii=False), encoding='utf-8')
    tmp.replace(ARQ_ESTADO)


_ultimo_detalhe = 0.0


def itens_do_anuncio(rid, pausa):
    """Baixa a página do anúncio, respeitando uma pausa entre páginas para não sobrecarregar o site."""
    global _ultimo_detalhe
    espera = _ultimo_detalhe + pausa - time.monotonic()
    if espera > 0:
        time.sleep(espera)
    try:
        return ler_itens(baixar(URL_ANUNCIO.format(rid)))
    finally:
        _ultimo_detalhe = time.monotonic()


def verificar(cfg, estado, varrer=False):
    anuncios = ler_anuncios(baixar(URL_LISTA))
    vistos = estado.get('anuncios', {})
    if not anuncios or len(anuncios) < len(vistos) // 2:
        log(f'A lista veio com {len(anuncios)} anúncios (antes eram {len(vistos)}); ignorando esta verificação.')
        return

    candidatos = []
    for rid, an in anuncios.items():
        antes = vistos.get(rid)
        if antes is not None and an['preco'] < antes:
            candidatos.append((an, f'baixou de {tcc(antes)}'))
        elif antes is None and vistos:
            candidatos.append((an, 'anúncio novo'))
        elif varrer:
            candidatos.append((an, 'já estava no ar'))

    filtros = filtros_ativos(cfg)
    pausa = max(1, cfg.get('pausa_entre_paginas', 2))
    if varrer:
        abrir = sum(1 for an, _ in candidatos if any(f.get('itens') and not falha_basica(f, an) for f in filtros))
        log(f'Varredura: {len(candidatos)} anúncios no ar, {abrir} precisam ser abertos '
            f'(~{abrir * (pausa + 1.5) / 60:.0f} min).')

    avisados = estado.get('avisados', {})
    falhas, n_avisos = set(), 0
    for an, motivo in candidatos:
        if motivo != 'já estava no ar':
            log(f"{motivo}: {an['nome']} · {an['classe']} nv {an['nivel']} · {tcc(an['preco'])}")
        cache = []

        def carregar(an=an):  # só baixa a página do anúncio se algum filtro precisar dos itens
            if not cache:
                cache.append(itens_do_anuncio(an['id'], pausa))
            return cache[0]

        for filtro in filtros:
            chave = f"{an['id']}:{an['preco']}:{filtro.get('nome')}"
            if chave in avisados:
                continue
            try:
                ok, achados = conferir(filtro, an, carregar)
            except Exception as e:
                log(f"Erro ao abrir o anúncio {an['id']} (tento de novo na próxima): {e}")
                falhas.add(an['id'])
                break
            if ok:
                avisar(cfg, an, filtro, motivo, achados)
                avisados[chave] = datetime.now().isoformat(timespec='seconds')
                n_avisos += 1

    # Anúncios que deram erro ficam de fora (ou com o preço antigo) para serem conferidos de novo.
    estado['anuncios'] = {rid: an['preco'] for rid, an in anuncios.items() if rid not in falhas}
    estado['anuncios'].update({rid: vistos[rid] for rid in falhas if rid in vistos})
    estado['avisados'] = {k: v for k, v in avisados.items() if k.split(':', 1)[0] in anuncios}
    salvar_estado(estado)
    if not vistos and not varrer:
        log(f'Primeira execução: {len(anuncios)} anúncios registrados. A partir de agora aviso dos novos '
            'e dos que baixarem de preço (use --varrer para conferir os que já estão no ar).')
    else:
        log(f'{len(anuncios)} anúncios no ar · {len(candidatos)} conferidos · {n_avisos} aviso(s).')


def vigiar(cfg, args):
    estado = carregar_estado()
    varrer = args.varrer
    if not args.uma_vez:
        log(f'Vigiando {URL_LISTA} com {len(filtros_ativos(cfg))} filtro(s) ativo(s). Ctrl+C para sair.')
    while True:
        intervalo = max(30, int(cfg.get('intervalo_segundos', 60)))
        try:
            verificar(cfg, estado, varrer)
            varrer = False
        except Exception as e:  # site fora do ar, internet caiu etc.: tenta de novo na próxima
            log(f'Erro nesta verificação: {e}')
        if args.uma_vez:
            return
        time.sleep(intervalo + random.uniform(0, intervalo * 0.2))
        try:
            cfg = carregar_filtros()  # relê a cada volta: dá para editar os filtros com o helper rodando
        except Exception as e:
            log(f'Não consegui reler {ARQ_FILTROS.name} ({e}); mantendo os filtros anteriores.')


def mostrar_itens(rid):
    itens = ler_itens(baixar(URL_ANUNCIO.format(rid)))
    if not itens:
        sys.exit('Não encontrei itens nesse anúncio (ele existe?).')
    por_secao = {}
    for it in itens:
        por_secao.setdefault(it['secao'], []).append(it)
    for secao, lista in por_secao.items():
        print(f'\n== {secao} ({len(lista)})')
        for it in lista:
            print('  ' + it['nome'] + (f" +{it['refino']}" if it['refino'] else '')
                  + (f" x{it['qtd']}" if it['qtd'] > 1 else ''))


def testar(cfg, rid):
    an = ler_anuncios(baixar(URL_LISTA)).get(str(rid))
    if an is None:
        sys.exit(f'O anúncio {rid} não está na lista (vendido ou removido?).')
    print(f"{an['nome']} · {an['classe']} nv {an['nivel']} · Céu {an['ceu']} · {tcc(an['preco'])}")
    print(URL_ANUNCIO.format(rid))
    cache = []

    def carregar():
        if not cache:
            cache.append(ler_itens(baixar(URL_ANUNCIO.format(rid))))
        return cache[0]

    for filtro in filtros_ativos(cfg):
        ok, det = conferir(filtro, an, carregar)
        if ok:
            itens = '; '.join(descrever(req, its) for req, its in det)
            print(f"  [BATE]      {filtro.get('nome')}" + (f' -> {itens}' if itens else ''))
        else:
            print(f"  [não bate]  {filtro.get('nome')} ({det})")


def main():
    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description='Vigia o Marketplace The Classic (PW 1.8.7) e avisa '
                                             'quando um anúncio bate com os filtros de filtros.toml.')
    ap.add_argument('--uma-vez', action='store_true', help='faz uma verificação e sai')
    ap.add_argument('--varrer', action='store_true', help='confere também os anúncios que já estão no ar')
    ap.add_argument('--testar', metavar='ID', help='mostra quais filtros batem com um anúncio')
    ap.add_argument('--itens', metavar='ID', help='lista os itens de um anúncio')
    ap.add_argument('--testar-aviso', action='store_true', help='dispara um aviso de teste')
    args = ap.parse_args()

    try:
        cfg = carregar_filtros()
    except FileNotFoundError:
        sys.exit(f'Não achei o arquivo {ARQ_FILTROS}.')
    except tomllib.TOMLDecodeError as e:
        sys.exit(f'Erro no {ARQ_FILTROS.name}: {e}')

    if args.itens:
        mostrar_itens(args.itens)
    elif args.testar:
        testar(cfg, args.testar)
    elif args.testar_aviso:
        enviar(cfg, 'Teste do helper do Marketplace', 'Se você está vendo isto, os avisos funcionam.',
               'Clique para abrir o Marketplace.', f'🔔 Teste do helper do Marketplace\n{URL_LISTA}', URL_LISTA)
        log('Aviso de teste enviado.')
    else:
        vigiar(cfg, args)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nEncerrado.')
