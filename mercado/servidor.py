"""Servidor local da interface: API JSON e arquivos de mercado/ui, só em 127.0.0.1.

Toda chamada à API precisa do cabeçalho X-Token (gerado a cada execução e embutido
na página), e o cabeçalho Host precisa ser o do próprio servidor. Assim, outra
página aberta no navegador não consegue mexer no programa.
"""
import json
import logging
import mimetypes
import re
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import avisos, sincronia, site

log = logging.getLogger('mercado')
PASTA_UI = Path(__file__).resolve().parent / 'ui'


class Erro(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


class App:
    """Liga o servidor ao banco, ao coletor e ao estado."""

    def __init__(self, banco, coletor, estado, notificar=avisos.notificar):
        self.banco, self.coletor, self.estado, self.notificar = banco, coletor, estado, notificar
        self.token = secrets.token_urlsafe(24)
        self.ultimo_sinal = None
        self.rotas = [
            ('GET', r'/api/estado', self.estado_api),
            ('POST', r'/api/buscar', self.buscar),
            ('GET', r'/api/conta/(\d+)', self.conta),
            ('GET', r'/api/sugestoes', self.sugestoes),
            ('GET', r'/api/valores', self.valores),
            ('POST', r'/api/valores', self.criar_valor),
            ('PUT', r'/api/valores/(\d+)', self.editar_valor),
            ('DELETE', r'/api/valores/(\d+)', self.apagar_valor),
            ('GET', r'/api/buscas', self.buscas),
            ('POST', r'/api/buscas', self.criar_busca),
            ('PUT', r'/api/buscas/(\d+)', self.editar_busca),
            ('DELETE', r'/api/buscas/(\d+)', self.apagar_busca),
            ('GET', r'/api/grupos', self.grupos),
            ('POST', r'/api/grupos', self.criar_grupo),
            ('PUT', r'/api/grupos/(\d+)', self.editar_grupo),
            ('DELETE', r'/api/grupos/(\d+)', self.apagar_grupo),
            ('GET', r'/api/avisos', self.avisos),
            ('GET', r'/api/config', self.config),
            ('PUT', r'/api/config', self.salvar_config),
            ('POST', r'/api/testar-aviso', self.testar_aviso),
            ('POST', r'/api/consultar-agora', self.consultar_agora),
            ('POST', r'/api/ler/(\d+)', self.ler_agora),
            ('POST', r'/api/sinal', self.sinal),
            ('POST', r'/api/sincronizar', self.sincronizar),
        ]

    # -------------------------------------------------------------- rotas

    def estado_api(self, q, corpo):
        if self.banco.sincronizar():  # o meus-dados.json mudou por fora (git pull, edição)
            self.estado.mudou()
            self.coletor.repriorizar()
        cfg = self.banco.config()
        return {**self.estado.como_dict(), **self.banco.contagem(), 'erro': self.banco.erro_dados or self.estado.erro,
                'agora': datetime.now().isoformat(timespec='seconds'),
                'rs_por_bi': cfg['rs_por_bi'], 'rs_por_tcc': cfg['rs_por_tcc'], 'intervalo_s': cfg['intervalo_s'],
                'dados_a_enviar': self.banco.dados_a_enviar()}

    def buscar(self, q, corpo):
        corpo = corpo or {}
        resultado = self.banco.buscar(corpo, self.coletor.ids_do_site)
        self.coletor.acompanhar([c['id'] for c in resultado['contas']])  # os lances das primeiras, de perto
        # "Ler primeiro as destes filtros": a interface só pede com algum filtro; sem o pedido, desfaz o anterior
        para_ler = self.banco.para_ler_na_busca(corpo, self.coletor.ids_do_site)
        self.coletor.ler_primeiro(para_ler if corpo.get('ler_primeiro') else [])
        resultado['para_ler'] = len(para_ler)
        return resultado

    def conta(self, q, corpo, rid):
        dados = self.banco.conta(int(rid))
        if dados is None:
            raise Erro(404, 'Conta não encontrada.')
        self.coletor.acompanhar_conta(int(rid))
        dados['url'] = site.URL_CONTA.format(rid)
        dados['na_fila'] = self.coletor.posicao_na_fila(int(rid))
        return dados

    def sugestoes(self, q, corpo):
        return {'itens': self.banco.sugestoes(q.get('q', [''])[0])}

    def valores(self, q, corpo):
        return {'valores': self.banco.valores(), 'resumo': self.banco.resumo_valores()}

    def criar_valor(self, q, corpo):
        vid = self.banco.salvar_valor(corpo or {})
        self.estado.mudou()
        self.coletor.repriorizar()
        return {'id': vid}

    def editar_valor(self, q, corpo, vid):
        self.banco.salvar_valor(corpo or {}, int(vid))
        self.estado.mudou()
        self.coletor.repriorizar()
        return {'id': int(vid)}

    def apagar_valor(self, q, corpo, vid):
        self.banco.apagar_valor(int(vid))
        self.estado.mudou()
        return {}

    def buscas(self, q, corpo):
        ultimos = self.banco.ultimos_avisos_por_busca()
        saida = []
        for b in self.banco.buscas():
            batem = self.banco.buscar(b['filtros'], self.coletor.ids_do_site)['batem']
            saida.append({**b, 'batem': batem, 'ultimo_aviso': ultimos.get(b['id'])})
        return {'buscas': saida}

    def criar_busca(self, q, corpo):
        bid = self.banco.salvar_busca(corpo or {})
        self.coletor.repriorizar()
        return {'id': bid}

    def editar_busca(self, q, corpo, bid):
        self.banco.salvar_busca(corpo or {}, int(bid))
        self.coletor.repriorizar()
        return {'id': int(bid)}

    def apagar_busca(self, q, corpo, bid):
        self.banco.apagar_busca(int(bid))
        return {}

    def grupos(self, q, corpo):
        return {'grupos': self.banco.grupos()}

    def criar_grupo(self, q, corpo):
        gid = self.banco.salvar_grupo(corpo or {})
        self._grupo_mudou()
        return {'id': gid}

    def editar_grupo(self, q, corpo, gid):
        self.banco.salvar_grupo(corpo or {}, int(gid))
        self._grupo_mudou()
        return {'id': int(gid)}

    def apagar_grupo(self, q, corpo, gid):
        self.banco.apagar_grupo(int(gid))
        self._grupo_mudou()
        return {}

    def _grupo_mudou(self):
        """As buscas que usam o grupo mudam: a lista recarrega, e as contas com os itens dele sobem na fila."""
        self.estado.mudou()
        self.coletor.repriorizar()

    def avisos(self, q, corpo):
        return {'avisos': self.banco.avisos()}

    def config(self, q, corpo):
        return self.banco.config()

    def salvar_config(self, q, corpo):
        antes = self.banco.config()
        cfg = self.banco.salvar_config(corpo or {})
        if (cfg['rs_por_bi'], cfg['rs_por_tcc']) != (antes['rs_por_bi'], antes['rs_por_tcc']):
            self.estado.mudou()
        if cfg['intervalo_s'] != antes['intervalo_s']:
            self.coletor.consultar_agora()
        return cfg

    def testar_aviso(self, q, corpo):
        cfg = {**self.banco.config(), **(corpo or {})}
        erros = self.notificar(cfg, 'Teste do Mercado PW', 'Se você está vendo isto, os avisos funcionam.',
                               'Clique para abrir o Marketplace.', '🔔 Teste do Mercado PW\n' + site.URL_LISTA,
                               site.URL_LISTA, esperar=True)
        return {'erros': erros}

    def consultar_agora(self, q, corpo):
        self.coletor.consultar_agora()
        return {}

    def ler_agora(self, q, corpo, rid):
        self.coletor.ler_agora(int(rid))
        return {}

    def sincronizar(self, q, corpo):
        """Botão "Sincronizar": manda para o GitHub o que mudou aqui e traz o que mudou no outro PC."""
        if self.banco.arquivo_dados is None:
            raise Erro(400, 'Este programa não usa o meus-dados.json.')
        try:
            resultado = sincronia.sincronizar(self.banco.arquivo_dados.parent, self.banco)
        except sincronia.ErroSincronia as e:
            raise Erro(409, str(e))
        self.estado.mudou()
        self.coletor.repriorizar()
        return resultado

    def sinal(self, q, corpo):
        self.ultimo_sinal = time.monotonic()
        return {}

    # -------------------------------------------------------------- servidor

    def criar_servidor(self, porta=0):
        app = self

        class Manipulador(_Manipulador):
            pass

        Manipulador.app = app
        servidor = ThreadingHTTPServer(('127.0.0.1', porta), Manipulador)
        servidor.daemon_threads = True
        return servidor


class _Manipulador(BaseHTTPRequestHandler):
    app = None
    server_version = 'MercadoPW'
    protocol_version = 'HTTP/1.1'

    def log_message(self, formato, *args):
        log.debug('%s - %s', self.address_string(), formato % args)

    def do_GET(self):
        self._atender('GET')

    def do_POST(self):
        self._atender('POST')

    def do_PUT(self):
        self._atender('PUT')

    def do_DELETE(self):
        self._atender('DELETE')

    def _atender(self, metodo):
        try:
            porta = self.server.server_address[1]
            if self.headers.get('Host') not in (f'127.0.0.1:{porta}', f'localhost:{porta}'):
                raise Erro(403, 'Acesso negado.')
            partes = urlsplit(self.path)
            if partes.path.startswith('/api/'):
                self._api(metodo, partes)
            elif metodo == 'GET':
                self._arquivo(partes.path)
            else:
                raise Erro(405, 'Método não permitido.')
        except Erro as e:
            self._json({'erro': str(e)}, e.status)
        except (ValueError, KeyError) as e:
            self._json({'erro': str(e) if isinstance(e, ValueError) else 'Não encontrado.'},
                       400 if isinstance(e, ValueError) else 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception('Erro ao atender %s %s', metodo, self.path)
            self._json({'erro': 'Erro interno. Veja o mercado.log.'}, 500)
        finally:
            self.app.banco.fechar()  # cada pedido roda numa thread nova; não deixa conexão aberta

    def _api(self, metodo, partes):
        if not secrets.compare_digest(self.headers.get('X-Token', ''), self.app.token):
            raise Erro(403, 'Acesso negado.')
        corpo = None
        tamanho = int(self.headers.get('Content-Length') or 0)
        if tamanho:
            try:
                corpo = json.loads(self.rfile.read(tamanho).decode('utf-8'))
            except ValueError:
                raise Erro(400, 'JSON inválido.')
        for m, padrao, funcao in self.app.rotas:
            achou = re.fullmatch(padrao, partes.path)
            if m == metodo and achou:
                self._json(funcao(parse_qs(partes.query), corpo, *achou.groups()))
                return
        raise Erro(404, 'Rota não encontrada.')

    def _arquivo(self, caminho):
        nome = 'index.html' if caminho in ('', '/') else caminho.lstrip('/')
        arquivo = (PASTA_UI / nome).resolve()
        if PASTA_UI.resolve() not in arquivo.parents or not arquivo.is_file():
            raise Erro(404, 'Arquivo não encontrado.')
        dados = arquivo.read_bytes()
        if arquivo.name == 'index.html':
            dados = dados.replace(b'{{TOKEN}}', self.app.token.encode())
        tipo = mimetypes.guess_type(arquivo.name)[0] or 'application/octet-stream'
        if tipo.startswith('text/') or tipo in ('application/javascript', 'application/json'):
            tipo += '; charset=utf-8'
        self._responder(dados, tipo, 200, {'Cache-Control': 'no-store'})

    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False, default=str).encode('utf-8')
        self._responder(corpo, 'application/json; charset=utf-8', status)

    def _responder(self, corpo, tipo, status, extras=None):
        self.send_response(status)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)


def iniciar(app, porta=0):
    """Sobe o servidor numa thread e devolve (servidor, porta)."""
    servidor = app.criar_servidor(porta)
    threading.Thread(target=servidor.serve_forever, daemon=True, name='servidor').start()
    return servidor, servidor.server_address[1]
