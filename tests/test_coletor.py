import dataclasses
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock
from datetime import datetime, timedelta
from pathlib import Path

from mercado import site
from mercado.banco import Banco
from mercado.coletor import ALTA, BAIXA, MEDIA, Coletor, Estado, Fila
from tests import paginas

COSMOS = site.COSMOS_ID


class SiteFalso:
    """Imita mercado.site sem rede: a lista e as contas vêm das páginas salvas."""
    URL_LISTA = 'lista'
    URL_CONTA = 'conta/{}'
    COSMOS_ID = COSMOS

    def __init__(self):
        self.anuncios = dict(site.ler_lista(paginas.lista()))
        self.contas = {45520: site.ler_conta(paginas.conta(45520)), 231216: site.ler_conta(paginas.conta(231216))}
        self.fora_do_ar = False
        self.lidas = []
        self.buscas = []
        self.site_ids = {231216, 3152}
        self.recusar = set()        # urls que o site responde com HTTP 429
        self.lances = {}            # rid -> {'pendentes', 'maior'}; sem a conta, nenhum lance
        self.demora = 0             # segundos de cada download
        self.baixando = self.max_baixando = 0
        self._trava = threading.Lock()

    def baixar(self, url):
        if self.fora_do_ar:
            raise OSError('sem rede')
        if url in self.recusar:
            raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)
        with self._trava:
            self.baixando += 1
            self.max_baixando = max(self.max_baixando, self.baixando)
        time.sleep(self.demora)
        with self._trava:
            self.baixando -= 1
        return url

    def ler_lista(self, _):
        return dict(self.anuncios)

    def ler_conta(self, url):
        rid = int(url.split('/')[1])
        self.lidas.append(rid)
        return self.contas.get(rid, [site.Item(secao='equipado', item_id=1, nome='Arma Comum')])

    def ler_lance(self, url):
        return dict(self.lances.get(int(url.split('/')[1]), {'pendentes': 0, 'maior': 0}))

    def catalogo(self):
        return [{'item_id': COSMOS, 'nome': 'Cosmos', 'grupo': 'livros'}]

    def busca_site(self, item_ids, cosmos_min=None):
        self.buscas.append((tuple(item_ids), cosmos_min))
        return set(self.site_ids)


class BaseColetor(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.banco = Banco(Path(self.pasta) / 'teste.db')
        self.site = SiteFalso()
        self.avisos = []
        self.coletor = Coletor(self.banco, Estado(), site=self.site,
                               notificar=lambda cfg, *args: self.avisos.append(args))
        self.coletor.atualizar_catalogo()
        self.coletor.consultar_lista()  # base: nada é novo

    def tearDown(self):
        self.banco.fechar()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def ler_tudo_da_fila(self, limite=10):
        for _ in range(limite):
            if not self.coletor.fila:
                break
            self.coletor.ler_proxima()


class TestFila(unittest.TestCase):
    def test_prioridade_e_sem_repeticao(self):
        f = Fila()
        f.colocar(1, BAIXA)
        f.colocar(2, BAIXA)
        f.colocar(3, MEDIA)
        f.colocar(2, ALTA)
        f.colocar(3, BAIXA)  # não desce de prioridade
        self.assertEqual(len(f), 3)
        self.assertEqual([f.tirar(), f.tirar(), f.tirar(), f.tirar()], [2, 3, 1, None])


class Consulta(BaseColetor):
    def test_base_nao_gera_eventos(self):
        self.assertEqual(len(self.coletor.fila), 0)
        self.assertIsNotNone(self.coletor.estado.ultima_consulta)

    def test_preencher_fila_prioriza_itens_valorizados(self):
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        self.coletor.preencher_fila()
        self.assertEqual(len(self.coletor.fila), len(self.site.anuncios))
        self.assertEqual(self.site.buscas, [((COSMOS,), None)])
        self.assertIn(self.coletor.fila.tirar(), {231216, 3152})

    def test_novo_valor_sobe_contas_na_fila(self):
        self.coletor.preencher_fila()  # tudo em prioridade baixa: ainda não há valores
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        self.coletor.repriorizar()
        self.coletor.passo()  # processa o pedido e lê a primeira da fila
        self.assertIn(self.site.lidas[0], {231216, 3152})

    def test_site_fora_do_ar(self):
        self.site.fora_do_ar = True
        self.coletor.consultar_lista()
        self.assertEqual(self.coletor.estado.erro, 'Sem conexão com o site.')
        self.assertIsNotNone(self.coletor.estado.sem_conexao_desde)
        self.site.fora_do_ar = False
        self.coletor.consultar_lista()
        self.assertIsNone(self.coletor.estado.erro)
        self.assertIsNone(self.coletor.estado.sem_conexao_desde)

    def test_lista_incompleta_e_ignorada(self):
        self.site.anuncios = dict(list(self.site.anuncios.items())[:100])
        self.coletor.consultar_lista()
        self.assertIn('incompleta', self.coletor.estado.erro)
        self.assertTrue(self.banco.anuncio(45520)['ativo'])

    def test_conta_que_falha_e_retentada_e_depois_abandonada(self):
        self.site.contas[45520] = []
        self.coletor.fila.colocar(45520, ALTA)
        self.ler_tudo_da_fila()
        self.assertEqual(self.site.lidas.count(45520), 3)
        self.coletor.preencher_fila()
        self.assertNotIn(45520, self.coletor.fila)


class LerPrimeiroOsDosFiltros(BaseColetor):
    def test_contas_que_podem_bater(self):
        classe = self.site.anuncios[45520].classe
        ids = self.banco.para_ler_na_busca({'classes': [classe]})
        self.assertIn(45520, ids)
        self.assertEqual({self.banco.anuncio(i)['classe'] for i in ids}, {classe})
        precos = [self.banco.anuncio(i)['preco'] for i in ids]
        self.assertEqual(precos, sorted(precos))
        # equipamento do catálogo: só as que a busca do site aponta
        cosmos = {'itens': [{'item_id': COSMOS, 'nome': 'Cosmos'}]}
        self.assertEqual(set(self.banco.para_ler_na_busca(cosmos, self.coletor.ids_do_site)), {231216, 3152})
        # item fora do catálogo: não dá para saber sem ler, valem todas as que faltam ler
        reliquia = {'itens': [{'item_id': 50410, 'nome': 'Relíquia Maravilha: Arma'}]}
        self.assertEqual(len(self.banco.para_ler_na_busca(reliquia, self.coletor.ids_do_site)), len(self.site.anuncios))
        # lida, sai da lista
        self.banco.gravar_itens(231216, self.site.contas[231216], self.site.anuncios[231216].preco)
        self.assertEqual(self.banco.para_ler_na_busca(cosmos, self.coletor.ids_do_site), [3152])

    def test_passam_na_frente_e_depois_vem_o_resto(self):
        self.coletor.preencher_fila()
        self.coletor.ler_primeiro([3152, 45520])
        self.coletor.passo()  # processa o pedido e lê a primeira
        self.coletor.ler_proxima()
        self.assertEqual(self.site.lidas, [3152, 45520])
        self.assertEqual(len(self.coletor.fila), len(self.site.anuncios) - 2)  # o resto continua na fila

    def test_filtros_novos_desfazem_os_anteriores(self):
        self.coletor.preencher_fila()
        self.coletor.ler_primeiro([3152])
        self.coletor.ler_primeiro([45520])
        self.coletor.passo()
        self.assertEqual(self.site.lidas, [45520])
        self.assertEqual(self.coletor.fila.prioridade(3152), BAIXA)
        self.coletor.ler_primeiro([])
        self.assertEqual(self.coletor._pedidos.qsize(), 1)  # ainda havia contas da busca para desfazer


class LeiturasSimultaneas(BaseColetor):
    def enfileirar(self, *ids):
        for rid in ids:
            self.coletor.fila.colocar(rid, ALTA)

    def test_uma_por_vez_por_padrao(self):
        self.enfileirar(45520, 231216)
        self.coletor.ler_proxima()
        self.assertEqual(self.site.lidas, [45520])

    def test_duas_ao_mesmo_tempo(self):
        self.banco.salvar_config({'leituras_simultaneas': 2})
        self.site.demora = 0.3
        self.enfileirar(45520, 231216, 3152)
        self.coletor.ler_proxima()
        self.assertEqual(sorted(self.site.lidas), [45520, 231216])
        self.assertEqual(self.site.max_baixando, 2)  # os dois downloads ao mesmo tempo
        self.assertEqual(len(self.coletor.estado._leituras), 2)  # as duas contam no ritmo da leitura
        self.assertTrue(all(self.banco.anuncio(rid)['itens_lidos_em'] for rid in (45520, 231216)))
        self.assertEqual((len(self.coletor.fila), self.coletor.estado.fila), (1, 1))
        self.assertFalse(self.coletor.posicao_na_fila(45520))

    def test_varias_ao_mesmo_tempo(self):
        ids = list(self.site.anuncios)[:6]
        self.banco.salvar_config({'leituras_simultaneas': 5})
        self.site.demora = 0.3
        self.enfileirar(*ids)
        self.coletor.ler_proxima()
        self.assertEqual(len(self.site.lidas), 5)
        self.assertEqual(self.site.max_baixando, 5)  # os cinco downloads ao mesmo tempo
        self.assertEqual(len(self.coletor.fila), 1)

    def test_site_recusou_volta_para_uma_por_vez(self):
        self.banco.salvar_config({'leituras_simultaneas': 2})
        self.site.recusar = {'conta/45520'}
        self.enfileirar(45520, 231216)
        self.coletor.ler_proxima()
        self.assertEqual(self.banco.config()['leituras_simultaneas'], 1)
        self.assertIn('recusou', self.coletor.estado.erro)
        self.assertIn('com 2 contas', self.coletor.estado.erro)
        self.assertTrue(self.banco.anuncio(231216)['itens_lidos_em'])  # a outra conta do par foi lida
        self.assertIn(45520, self.coletor.fila)  # a recusada volta para a fila


class Ritmo(unittest.TestCase):
    """Contas lidas por minuto, para a estimativa do tempo que falta na barra do topo."""

    def setUp(self):
        self.estado, self.agora = Estado(), [1000.0]
        relogio = mock.patch('mercado.coletor.time.monotonic', lambda: self.agora[0])
        relogio.start()
        self.addCleanup(relogio.stop)

    def ler(self, vezes, contas, a_cada):
        for _ in range(vezes):
            self.estado.leu(contas)
            self.agora[0] += a_cada

    def test_contas_por_minuto(self):
        self.ler(10, 2, 6)  # duas contas a cada 6 s
        self.assertEqual(self.estado.por_minuto(), 20.0)
        self.assertEqual(self.estado.como_dict()['por_minuto'], 20.0)

    def test_calculando_no_comeco(self):
        self.assertIsNone(self.estado.por_minuto())
        self.ler(3, 2, 6)  # menos de 1 min de leitura
        self.assertIsNone(self.estado.por_minuto())

    def test_so_os_ultimos_minutos(self):
        self.ler(10, 2, 6)
        self.agora[0] += 400  # parou de ler: as leituras antigas saem da conta
        self.assertIsNone(self.estado.por_minuto())


class Lances(BaseColetor):
    """Lances: vêm junto com os itens e, sem contas para ler, são relidos (as contas da tela de perto)."""

    def ha(self, segundos):
        return (datetime.now() - timedelta(seconds=segundos)).isoformat(timespec='seconds')

    def test_vem_junto_com_os_itens(self):
        self.site.lances[45520] = {'pendentes': 1, 'maior': 1700}
        self.coletor.fila.colocar(45520, ALTA)
        self.coletor.ler_proxima()
        a = self.banco.anuncio(45520)
        self.assertEqual((a['lances'], a['maior_lance'], a['lance_novo_em']), (1, 1700, None))  # primeira vez: a base

    def test_contas_da_tela_primeiro(self):
        self.coletor.acompanhar([231216, 45520])
        self.coletor.acompanhar_conta(3152)
        self.assertEqual(self.coletor._lance_a_ler(), (3152, False))  # a aberta nos detalhes vem antes
        self.coletor.ler_lance(3152)
        self.assertEqual(self.coletor._lance_a_ler(), (231216, False))
        self.coletor.ler_lance(231216)
        self.coletor.ler_lance(45520)
        # todas as da tela em dia: vem uma das outras, das já lidas (a 45520, ao ler os itens, já tem lances)
        self.banco.gravar_itens(1856, [site.Item(secao='equipado', item_id=1, nome='Arma')], 15000)
        self.assertEqual(self.coletor._lance_a_ler(), (1856, True))
        self.coletor.ler_lance(1856, geral=True)
        self.assertIsNone(self.coletor._lance_a_ler())  # a próxima das outras só daqui a 30 s

    def test_com_muitas_contas_na_tela_o_intervalo_cresce(self):
        tela = [a.id for a in list(self.site.anuncios.values())[:30]]
        self.coletor.acompanhar(tela)
        for rid in tela:
            self.banco.gravar_lance(rid, {'pendentes': 0, 'maior': 0}, quando=self.ha(90))
        self.coletor._proximo_lance_geral = time.monotonic() + 999
        self.assertIsNone(self.coletor._lance_a_ler())  # 30 contas: cada uma a cada 3 min
        self.coletor.acompanhar(tela[:1])
        self.assertEqual(self.coletor._lance_a_ler(), (tela[0], False))  # uma só: a cada 1 min

    def test_lance_novo(self):
        self.coletor.acompanhar([45520])
        self.coletor.ler_lance(45520)
        self.banco.con.execute("UPDATE anuncios SET lances_em = '2000-01-01T00:00:00' WHERE id = 45520")
        self.site.lances[45520] = {'pendentes': 2, 'maior': 1900}
        versao = self.coletor.estado.versao
        with self.assertLogs('mercado', 'INFO') as registro:
            self.coletor.ler_lance(45520)
        self.assertIn('Lance novo na conta 45520', registro.output[0])
        a = self.banco.anuncio(45520)
        self.assertEqual((a['lances'], a['maior_lance']), (2, 1900))
        self.assertIsNotNone(a['lance_novo_em'])
        self.assertGreater(self.coletor.estado.versao, versao)  # a lista mostra o lance novo

    def test_pagina_que_falha_espera_para_tentar_de_novo(self):
        self.coletor.acompanhar([45520, 231216])
        self.site.recusar = {'conta/45520'}
        with self.assertLogs('mercado', 'WARNING'):
            self.coletor.ler_lance(45520)
        self.assertEqual(self.coletor._lance_a_ler(), (231216, False))


class Avisos(BaseColetor):
    def setUp(self):
        super().setUp()
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3000})
        self.banco.salvar_config({'rs_por_bi': 10000})
        self.busca = self.banco.salvar_busca({'nome': 'Cosmos +10', 'filtros': {
            'itens': [{'item_id': COSMOS, 'nome': 'Cosmos', 'refino_min': 10}]}})

    def reanunciar(self, rid, preco=None):
        """Tira o anúncio do ar e põe de volta (opcionalmente com outro preço)."""
        anuncio = self.site.anuncios.pop(rid)
        self.coletor.consultar_lista()
        self.site.anuncios[rid] = dataclasses.replace(anuncio, preco=preco or anuncio.preco)
        self.coletor.consultar_lista()

    def test_conta_reanunciada_que_bate_avisa_uma_vez(self):
        self.reanunciar(231216)
        self.assertEqual(self.coletor.fila.tirar(), 231216)
        self.coletor.fila.colocar(231216, ALTA)
        self.ler_tudo_da_fila()
        self.assertEqual(len(self.avisos), 1)
        titulo, linha1, linha2, texto, url = self.avisos[0]
        self.assertEqual(titulo, '15.000 TCC · Cosmos +10')
        self.assertEqual(linha1, 'TooSadToDie · Bárbaro 105')
        self.assertIn('lucro +R$ 15.000 (50%)', linha2)
        self.assertIn('Cosmos +12', texto)
        self.assertEqual(url, 'conta/231216')
        self.coletor.conferir_buscas(231216, 'de novo')
        self.assertEqual(len(self.avisos), 1)
        self.assertEqual(len(self.banco.avisos()), 1)

    def test_baixa_de_preco_avisa_de_novo(self):
        self.coletor.fila.colocar(231216, ALTA)
        self.ler_tudo_da_fila()
        self.assertEqual(self.avisos, [])  # leitura comum, sem evento
        self.site.anuncios[231216] = dataclasses.replace(self.site.anuncios[231216], preco=12000)
        self.coletor.consultar_lista()
        self.ler_tudo_da_fila()
        self.assertEqual(len(self.avisos), 1)
        self.assertIn('baixou de 15.000 TCC para 12.000 TCC', self.avisos[0][2])

    def test_lucro_minimo(self):
        self.banco.salvar_busca({'nome': 'Cosmos +10', 'avisar': True, 'lucro_min_rs': 20000,
                                 'filtros': {'itens': [{'item_id': COSMOS, 'refino_min': 10}]}}, self.busca)
        self.reanunciar(231216)
        self.ler_tudo_da_fila()
        self.assertEqual(self.avisos, [])

    def test_preco_maximo(self):
        """O preço máximo da busca vale para o aviso: acima dele não avisa, e avisa quando a conta baixa até ele."""
        self.banco.salvar_busca({'nome': 'Cosmos +10', 'avisar': True, 'filtros': {
            'itens': [{'item_id': COSMOS, 'refino_min': 10}], 'preco_max': 12000}}, self.busca)
        self.reanunciar(231216)  # 15.000 TCC
        self.ler_tudo_da_fila()
        self.assertEqual(self.avisos, [])
        self.site.anuncios[231216] = dataclasses.replace(self.site.anuncios[231216], preco=12000)
        self.coletor.consultar_lista()
        self.ler_tudo_da_fila()
        self.assertEqual(len(self.avisos), 1)
        self.assertIn('baixou de 15.000 TCC para 12.000 TCC', self.avisos[0][2])

    def test_busca_com_pelo_menos_um_item(self):
        self.banco.salvar_busca({'nome': 'Arma do rank', 'avisar': True, 'filtros': {'algum': [
            {'item_id': 999, 'nome': 'Arma de outra classe'}, {'item_id': COSMOS, 'nome': 'Cosmos', 'refino_min': 10}]}},
            self.busca)
        self.reanunciar(231216)
        self.ler_tudo_da_fila()
        self.assertEqual([a[0] for a in self.avisos], ['15.000 TCC · Arma do rank'])

    def test_busca_sem_aviso(self):
        self.banco.salvar_busca({'nome': 'Cosmos +10', 'avisar': False, 'filtros': {}}, self.busca)
        self.reanunciar(231216)
        self.ler_tudo_da_fila()
        self.assertEqual(self.avisos, [])

    def test_ids_do_site(self):
        self.assertEqual(self.coletor.ids_do_site({'item_id': COSMOS, 'refino_min': 12}), {231216, 3152})
        self.assertEqual(self.site.buscas, [((COSMOS,), 12)])
        self.coletor.ids_do_site({'item_id': COSMOS, 'refino_min': 12})
        self.assertEqual(len(self.site.buscas), 1)  # veio do cache
        self.assertIsNone(self.coletor.ids_do_site({'item_id': 38154}))  # fora do catálogo
        self.assertIsNone(self.coletor.ids_do_site({'nome': 'Pedra Perfeita'}))
        # grupo: uma busca só, com os equipamentos do catálogo que estão nele
        self.assertEqual(self.coletor.ids_do_site({'grupo_id': 1, 'itens': [38154, COSMOS]}), {231216, 3152})
        self.assertEqual(self.site.buscas[-1], ((COSMOS,), None))
        self.assertIsNone(self.coletor.ids_do_site({'grupo_id': 2, 'itens': [38154]}))

    def test_ids_do_site_de_grupo_que_precisa_de_todos(self):
        """No "Tem item", o grupo exige todos os itens: uma busca por item, e valem as contas que aparecem em todas."""
        self.coletor._catalogo = {COSMOS, 777}
        por_item = {COSMOS: {231216, 3152}, 777: {3152, 45520}}
        self.site.busca_site = lambda ids, cosmos_min=None: set().union(*(por_item[i] for i in ids))  # o site junta com OU
        self.assertEqual(self.coletor.ids_do_site({'grupo_id': 1, 'itens': [COSMOS, 777, 38154], 'todos': True}), {3152})
        self.assertEqual(self.coletor.ids_do_site({'grupo_id': 1, 'itens': [COSMOS, 777], 'todos': False}), {231216, 3152, 45520})


if __name__ == '__main__':
    unittest.main()
