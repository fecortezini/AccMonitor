"""Coletor: consulta a lista periodicamente, lê as contas numa fila e dispara os avisos.

Ordem da fila (docs/superpowers/specs/2026-09-21-mercado-pw-design.md, seção 4):
  ALTA  contas novas, anunciadas de novo ou que baixaram de preço;
  MEDIA contas que a busca do site diz terem algum item da tabela de valores ou das buscas salvas;
  BAIXA as demais ainda não lidas, das mais baratas para as mais caras.
"""
import heapq
import itertools
import logging
import threading
import time
from datetime import datetime, timedelta

from . import avisos, site as site_padrao

log = logging.getLogger('mercado')

ALTA, MEDIA, BAIXA = 0, 1, 2
TENTATIVAS = 3              # leituras que falham antes de desistir da conta (até o preço mudar)
CACHE_SITE_S = 120          # validade das respostas da busca do site
CATALOGO_H = 24             # o catálogo do site é baixado de novo depois disso


class Fila:
    """Fila de contas a ler, sem repetição; uma conta que já está na fila só sobe de prioridade."""

    def __init__(self):
        self._heap, self._prio, self._seq = [], {}, itertools.count()

    def colocar(self, rid, prioridade):
        if prioridade < self._prio.get(rid, 99):
            self._prio[rid] = prioridade
            heapq.heappush(self._heap, (prioridade, next(self._seq), rid))

    def tirar(self):
        while self._heap:
            prioridade, _, rid = heapq.heappop(self._heap)
            if self._prio.get(rid) == prioridade:
                del self._prio[rid]
                return rid
        return None

    def __len__(self):
        return len(self._prio)

    def __contains__(self, rid):
        return rid in self._prio


class Estado:
    """O que a interface mostra sobre o coletor (barra do topo)."""

    def __init__(self):
        self._trava = threading.Lock()
        self.versao = 0
        self.ultima_consulta = None
        self.erro = None
        self.sem_conexao_desde = None
        self.lendo = None
        self.fila = 0

    def mudou(self):
        with self._trava:
            self.versao += 1

    def como_dict(self):
        return {'versao': self.versao, 'ultima_consulta': self.ultima_consulta, 'erro': self.erro,
                'sem_conexao_desde': self.sem_conexao_desde, 'lendo': self.lendo, 'fila': self.fila}


class Coletor(threading.Thread):
    def __init__(self, banco, estado, site=site_padrao, notificar=avisos.notificar):
        super().__init__(daemon=True, name='coletor')
        self.banco, self.estado, self.site, self.notificar = banco, estado, site, notificar
        self.fila = Fila()
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._proxima_lista = 0.0
        self._ultimo_detalhe = 0.0
        self._proximo_catalogo = 0.0
        self._motivos = {}          # contas lidas por causa de um evento -> motivo do aviso
        self._falhas = {}           # rid -> (preço, tentativas)
        self._vazias_seguidas = 0
        self._cache_site = {}
        self._trava_site = threading.Lock()
        self._catalogo = None

    # -------------------------------------------------------------- controle

    def parar(self):
        self._parar.set()
        self._acordar.set()

    def consultar_agora(self):
        self._proxima_lista = 0.0
        self._acordar.set()

    def run(self):
        while not self._parar.is_set():
            try:
                self.passo()
            except Exception:  # nunca deixa o coletor morrer; tenta de novo em seguida
                log.exception('Erro inesperado no coletor')
                self._acordar.wait(10)
            self._acordar.clear()

    def passo(self):
        """Faz a próxima tarefa que estiver na hora, ou dorme até ela."""
        cfg = self.banco.config()
        agora = time.monotonic()
        if agora >= self._proximo_catalogo:
            self.atualizar_catalogo()
        if agora >= self._proxima_lista:
            self.consultar_lista()
            self._proxima_lista = time.monotonic() + cfg['intervalo_s']
        if not self.fila:
            self.preencher_fila()
        pronto = self._ultimo_detalhe + cfg['pausa_s']
        if self.fila and time.monotonic() >= pronto:
            self.ler_proxima()
            return
        proxima = min(self._proxima_lista, pronto) if self.fila else self._proxima_lista
        self._acordar.wait(max(0.05, proxima - time.monotonic()))

    # -------------------------------------------------------------- lista e catálogo

    def atualizar_catalogo(self):
        feito = self.banco.meta('catalogo_em')
        velho = not feito or datetime.fromisoformat(feito) < datetime.now() - timedelta(hours=CATALOGO_H)
        if velho:
            try:
                self.banco.gravar_catalogo(self.site.catalogo())
                log.info('Catálogo do site atualizado')
            except Exception as e:
                log.warning('Não consegui baixar o catálogo do site: %s', e)
                self._proximo_catalogo = time.monotonic() + 600
                return
        self._catalogo = self.banco.ids_no_catalogo()
        self._proximo_catalogo = time.monotonic() + 3600

    def consultar_lista(self):
        try:
            anuncios = self.site.ler_lista(self.site.baixar(self.site.URL_LISTA))
        except Exception as e:
            log.warning('Falha ao consultar a lista: %s', e)
            self._falha('Sem conexão com o site.', conexao=True)
            return
        ativas = self.banco.contagem()['ativas']
        if not anuncios:
            self._falha('Não consegui ler a lista de anúncios. O site pode ter mudado.')
            return
        if len(anuncios) < ativas // 2:
            self._falha(f'A lista veio incompleta ({len(anuncios)} de {ativas} anúncios); consulta ignorada.')
            return
        mudou = self.banco.atualizar_lista(anuncios)
        self.estado.ultima_consulta = datetime.now().isoformat(timespec='seconds')
        self.estado.sem_conexao_desde = None
        if self.estado.erro and self._vazias_seguidas < 5:
            self.estado.erro = None
        eventos = ([(rid, 'anúncio novo') for rid in mudou['novos']]
                   + [(rid, 'anunciada de novo') for rid in mudou['reativados']]
                   + [(rid, f'baixou de {avisos.tcc(antes)} para {avisos.tcc(depois)}')
                      for rid, antes, depois in mudou['baixaram']])
        for rid, motivo in eventos:
            self._motivos[rid] = motivo
            self._falhas.pop(rid, None)
            self.fila.colocar(rid, ALTA)
        if eventos or mudou['removidos']:
            log.info('Lista: %d novos, %d reanunciados, %d mais baratos, %d removidos', len(mudou['novos']),
                     len(mudou['reativados']), len(mudou['baixaram']), mudou['removidos'])
        self.estado.fila = len(self.fila)
        self.estado.mudou()

    def _falha(self, mensagem, conexao=False):
        self.estado.erro = mensagem
        if conexao and not self.estado.sem_conexao_desde:
            self.estado.sem_conexao_desde = datetime.now().isoformat(timespec='seconds')
        self.estado.mudou()

    # -------------------------------------------------------------- fila de contas

    def _desistiu(self, conta):
        preco, tentativas = self._falhas.get(conta['id'], (None, 0))
        return preco == conta['preco'] and tentativas >= TENTATIVAS

    def preencher_fila(self):
        pendentes = [c for c in self.banco.contas_para_ler() if not self._desistiu(c)]
        if not pendentes:
            return
        prioritarios = self._ids_prioritarios()
        for c in pendentes:
            self.fila.colocar(c['id'], MEDIA if c['id'] in prioritarios else BAIXA)
        self.estado.fila = len(self.fila)

    def _ids_prioritarios(self):
        catalogo = self._ids_catalogo()
        itens = sorted(self.banco.ids_valorizados() & catalogo)
        if not itens:
            return set()
        return self._busca_site(('itens', tuple(itens)), lambda: self.site.busca_site(itens)) or set()

    def ler_proxima(self):
        rid = self.fila.tirar()
        self.estado.fila = len(self.fila)
        anuncio = self.banco.anuncio(rid) if rid is not None else None
        if not anuncio or not anuncio['ativo']:
            self._motivos.pop(rid, None)
            return
        self.estado.lendo = rid
        try:
            itens = self.site.ler_conta(self.site.baixar(self.site.URL_CONTA.format(rid)))
        except Exception as e:
            log.warning('Falha ao ler a conta %s: %s', rid, e)
            itens = None
            self._falha('Sem conexão com o site.', conexao=True)
        finally:
            self._ultimo_detalhe = time.monotonic()
            self.estado.lendo = None
        if not itens:
            self._conta_falhou(rid, anuncio['preco'], vazia=itens is not None)
            return
        self._vazias_seguidas = 0
        self._falhas.pop(rid, None)
        self.banco.gravar_itens(rid, itens, anuncio['preco'])
        self.estado.mudou()
        motivo = self._motivos.pop(rid, None)
        if motivo:
            self.conferir_buscas(rid, motivo)

    def _conta_falhou(self, rid, preco, vazia):
        anteriores = self._falhas.get(rid, (preco, 0))
        tentativas = (anteriores[1] if anteriores[0] == preco else 0) + 1
        self._falhas[rid] = (preco, tentativas)
        if vazia:
            self._vazias_seguidas += 1
            if self._vazias_seguidas >= 5:
                self._falha('Não consegui ler os itens das contas. O site pode ter mudado.')
        if tentativas < TENTATIVAS:
            self.fila.colocar(rid, ALTA if rid in self._motivos else BAIXA)
        else:
            self._motivos.pop(rid, None)
        self.estado.fila = len(self.fila)

    # -------------------------------------------------------------- avisos

    def conferir_buscas(self, rid, motivo):
        """Confere a conta recém-lida contra as buscas salvas com aviso ligado."""
        cfg = self.banco.config()
        for busca in self.banco.buscas():
            if not busca['avisar']:
                continue
            resultado = self.banco.buscar({**busca['filtros'], 'ids': [rid]})
            conta = resultado['contas'][0] if resultado['contas'] else None
            if conta is None:
                continue
            if busca['lucro_min_rs'] is not None and (conta['lucro_rs'] is None
                                                       or conta['lucro_rs'] < busca['lucro_min_rs']):
                continue
            if busca['lucro_min_pct'] is not None and (conta['lucro_pct'] is None
                                                        or conta['lucro_pct'] * 100 < busca['lucro_min_pct']):
                continue
            if self.banco.registrar_aviso(busca['id'], rid, conta['preco'], conta['lucro_rs'], motivo):
                self._avisar(cfg, busca, conta, motivo)

    def _avisar(self, cfg, busca, conta, motivo):
        url = self.site.URL_CONTA.format(conta['id'])
        lucro = (f"lucro {avisos.reais(conta['lucro_rs'], sinal=True)} ({conta['lucro_pct'] * 100:.0f}%)"
                 if conta['lucro_rs'] is not None and conta['lucro_pct'] is not None else '')
        titulo = f"{avisos.tcc(conta['preco'])} · {busca['nome']}"
        linha1 = f"{conta['nome']} · {conta['classe']} {conta['nivel']}"
        linha2 = ' · '.join(p for p in (lucro, motivo) if p)
        itens = ', '.join(d['nome'] + (f" +{d['refino']}" if d['refino'] else '') + (f" x{d['qtd']}" if d['qtd'] > 1 else '')
                          for d in conta['destaques'])
        texto = '\n'.join(p for p in (f"🔔 {busca['nome']}", linha1, f"{avisos.tcc(conta['preco'])} · {motivo}",
                                      lucro.capitalize(), itens and f'Itens: {itens}', url) if p)
        log.info('Aviso: %s', texto.replace('\n', ' | '))
        self.notificar(cfg, titulo, linha1, linha2, texto, url)
        self.estado.mudou()

    # -------------------------------------------------------------- busca do site

    def _ids_catalogo(self):
        if self._catalogo is None:
            self._catalogo = self.banco.ids_no_catalogo()
        return self._catalogo

    def ids_do_site(self, cond):
        """ids de contas que a busca do site encontra para uma condição de item, ou None.

        Só vale para equipamentos do catálogo. O refino só é filtrado no caso do Cosmos.
        """
        item_id = cond.get('item_id')
        if not str(item_id or '').isdigit() or int(item_id) not in self._ids_catalogo():
            return None
        item_id = int(item_id)
        refino = int(cond.get('refino_min') or 0) if item_id == self.site.COSMOS_ID else 0
        return self._busca_site(('item', item_id, refino),
                                lambda: self.site.busca_site([item_id], cosmos_min=refino or None))

    def _busca_site(self, chave, consulta):
        with self._trava_site:
            quando, ids = self._cache_site.get(chave, (0, None))
            if time.monotonic() - quando < CACHE_SITE_S:
                return ids
        try:
            ids = consulta()
        except Exception as e:
            log.warning('Busca do site indisponível: %s', e)
            ids = None
        with self._trava_site:
            self._cache_site[chave] = (time.monotonic(), ids)
        return ids
