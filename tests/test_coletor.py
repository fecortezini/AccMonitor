import dataclasses
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
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
        self.assertTrue(all(self.banco.anuncio(rid)['itens_lidos_em'] for rid in (45520, 231216)))
        self.assertEqual((len(self.coletor.fila), self.coletor.estado.fila), (1, 1))
        self.assertFalse(self.coletor.posicao_na_fila(45520))

    def test_site_recusou_volta_para_uma_por_vez(self):
        self.banco.salvar_config({'leituras_simultaneas': 2})
        self.site.recusar = {'conta/45520'}
        self.enfileirar(45520, 231216)
        self.coletor.ler_proxima()
        self.assertEqual(self.banco.config()['leituras_simultaneas'], 1)
        self.assertIn('recusou', self.coletor.estado.erro)
        self.assertTrue(self.banco.anuncio(231216)['itens_lidos_em'])  # a outra conta do par foi lida
        self.assertIn(45520, self.coletor.fila)  # a recusada volta para a fila


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


if __name__ == '__main__':
    unittest.main()
