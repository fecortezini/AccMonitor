import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path

from mercado import site
from mercado.banco import Banco
from tests import paginas

COSMOS, DEMONIO = site.COSMOS_ID, 38154


class BaseBanco(unittest.TestCase):
    """Banco temporário com a lista real e as duas contas salvas já lidas."""

    @classmethod
    def setUpClass(cls):
        cls.lista = site.ler_lista(paginas.lista())
        cls.itens = {rid: site.ler_conta(paginas.conta(rid)) for rid in (45520, 231216)}

    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.banco = Banco(Path(self.pasta) / 'teste.db')
        self.banco.atualizar_lista(self.lista)
        for rid, itens in self.itens.items():
            self.banco.gravar_itens(rid, itens, self.lista[rid].preco)

    def tearDown(self):
        self.banco.fechar()
        shutil.rmtree(self.pasta, ignore_errors=True)


class Lista(BaseBanco):
    def test_primeira_lista_e_a_base(self):
        a = self.banco.anuncio(45520)
        self.assertEqual((a['nome'], a['preco'], a['nova'], a['ativo']), ('memoryzito', 2400, 0, 1))

    def test_novos_baixaram_removidos_e_reativados(self):
        lista = dict(self.lista)
        removido = lista.pop(231216)
        lista[45520] = dataclasses.replace(lista[45520], preco=2000)
        lista[1] = site.Anuncio(id=1, preco=50, nivel=105, ocupacao=6, nome='Novata', classe='Arqueiro', ceu='Real I')
        mudou = self.banco.atualizar_lista(lista)
        self.assertEqual(mudou, {'primeira': False, 'novos': [1], 'baixaram': [(45520, 2400, 2000)],
                                 'reativados': [], 'removidos': 1})
        self.assertTrue(self.banco.anuncio(1)['nova'])
        self.assertFalse(self.banco.anuncio(231216)['ativo'])

        lista[231216] = removido
        mudou = self.banco.atualizar_lista(lista)
        self.assertEqual(mudou['reativados'], [231216])
        self.assertIsNone(self.banco.anuncio(231216)['itens_lidos_em'])  # será lida de novo

    def test_contas_para_ler(self):
        ids = [c['id'] for c in self.banco.contas_para_ler()]
        self.assertEqual(len(ids), len(self.lista) - 2)
        self.assertNotIn(45520, ids)
        precos = [c['preco'] for c in self.banco.contas_para_ler()]
        self.assertEqual(precos, sorted(precos))

    def test_preco_mudou_pede_releitura(self):
        lista = dict(self.lista)
        lista[45520] = dataclasses.replace(lista[45520], preco=3000)
        self.banco.atualizar_lista(lista)
        self.assertIn(45520, [c['id'] for c in self.banco.contas_para_ler()])


class Valores(BaseBanco):
    def setUp(self):
        super().setUp()
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3000})
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        self.banco.salvar_valor({'nome': 'Pedra do Demônio', 'valor_kk': 20})  # id vem dos itens já vistos

    def test_valor_das_contas(self):
        self.assertEqual(self.banco.anuncio(231216)['valor_kk'], 6000 + 24 * 20)
        self.assertEqual(self.banco.anuncio(45520)['valor_kk'], 0)
        self.assertIsNone(self.banco.anuncio(3152)['valor_kk'])  # ainda não lida

    def test_item_vinculado_pelo_nome(self):
        demonio = next(v for v in self.banco.valores() if v['nome'] == 'Pedra do Demônio')
        self.assertEqual((demonio['item_id'], demonio['contas'], demonio['tipo']), (DEMONIO, 1, 'pedra'))

    def test_item_ainda_nao_visto(self):
        lista = dict(self.lista)
        lista[1] = site.Anuncio(id=1, preco=50, nivel=105, ocupacao=6, nome='Futura', classe='Arqueiro', ceu='')
        self.banco.atualizar_lista(lista)
        self.banco.salvar_valor({'nome': 'Item Futuro', 'valor_kk': 2})
        self.assertIsNone(next(v for v in self.banco.valores() if v['nome'] == 'Item Futuro')['item_id'])
        self.banco.gravar_itens(1, [site.Item(secao='inventario', item_id=4242, nome='Item Futuro', qtd=3)], 50)
        self.assertEqual(self.banco.anuncio(1)['valor_kk'], 6)
        self.assertEqual(next(v for v in self.banco.valores() if v['nome'] == 'Item Futuro')['item_id'], 4242)

    def test_faixa_repetida(self):
        with self.assertRaises(ValueError):
            self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 1})

    def test_apagar_recalcula(self):
        for v in self.banco.valores():
            self.banco.apagar_valor(v['id'])
        self.assertEqual(self.banco.anuncio(231216)['valor_kk'], 0)

    def test_detalhes_da_conta(self):
        conta = self.banco.conta(231216)
        self.assertEqual([d['nome'] for d in conta['detalhes']], ['Cosmos', 'Pedra do Demônio'])
        self.assertEqual(conta['detalhes'][0]['rs'], 3000.0)
        arma = next(i for i in conta['itens'] if i['secao'] == 'equipado')
        self.assertIn(arma['tooltip'], conta['tooltips'])

    def test_resumo(self):
        r = self.banco.resumo_valores()
        self.assertEqual((r['valores'], r['itens'], r['contas_com_item']), (3, 2, 1))
        self.assertEqual(r['melhor']['id'], 231216)


class Buscar(BaseBanco):
    def ids(self, filtros, site_ids=None):
        return [c['id'] for c in self.banco.buscar(filtros, site_ids)['contas']]

    def test_filtros_basicos(self):
        self.assertIn(45520, self.ids({'classes': ['Arqueiro'], 'preco_max': 2400, 'nivel_min': 105}))
        self.assertNotIn(45520, self.ids({'preco_max': 2399}))
        self.assertEqual(self.ids({'nome': 'MEMORY'}), [45520])
        self.assertIn(45520, self.ids({'ceu': 'majestoso'}))

    def test_condicao_de_item(self):
        filtro = {'itens': [{'item_id': COSMOS, 'nome': 'Cosmos', 'refino_min': 12}]}
        self.assertEqual(self.ids(filtro), [231216])
        self.assertEqual(self.ids({'itens': [{'nome': 'pedra perfeita', 'qtd_min': 48004}]}), [45520])
        self.assertEqual(self.ids({'itens': [{'nome': 'pedra perfeita', 'qtd_min': 48005}]}), [])
        self.assertEqual(self.ids({'itens': [{'item_id': DEMONIO, 'onde': 'engastada', 'qtd_min': 24}]}), [231216])

    def test_contas_nao_lidas_pela_busca_do_site(self):
        resultado = self.banco.buscar({'itens': [{'item_id': COSMOS, 'refino_min': 12}]},
                                      lambda cond: {231216, 3152, 1856})
        por_id = {c['id']: c for c in resultado['contas']}
        self.assertEqual(set(por_id), {231216, 3152, 1856})
        self.assertFalse(por_id[231216]['a_confirmar'])
        self.assertTrue(por_id[3152]['a_confirmar'])
        self.assertEqual(resultado['a_confirmar'], 2)

    def test_lucro_e_ordem(self):
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        self.assertEqual(self.ids({'so_lucro': True}), [])
        self.banco.salvar_config({'rs_por_bi': 10000})
        contas = self.banco.buscar({'so_lucro': True})['contas']
        self.assertEqual([c['id'] for c in contas], [231216])
        self.assertEqual(contas[0]['lucro_rs'], 30000 - 15000)
        todas = self.banco.buscar({'ordem': 'lucro_rs'})['contas']
        self.assertEqual(todas[0]['id'], 231216)  # quem tem lucro vem antes de quem não foi lida

    def test_conta_sem_itens_da_tabela_nao_tem_lucro(self):
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        conta = self.banco.buscar({'nome': 'memoryzito'})['contas'][0]
        self.assertEqual((conta['valor_rs'], conta['lucro_rs'], conta['lucro_pct']), (0, None, None))

    def test_resumo_da_busca(self):
        r = self.banco.buscar({'classes': ['Arqueiro'], 'nome': 'memoryzito'})
        self.assertEqual((r['batem'], r['preco_min'], r['preco_mediana']), (1, 2400, 2400))


class Outros(BaseBanco):
    def test_sugestoes(self):
        sug = self.banco.sugestoes('pedra do dem')
        self.assertEqual((sug[0]['item_id'], sug[0]['contas'], sug[0]['tipo']), (DEMONIO, 1, 'pedra'))
        self.assertEqual(self.banco.sugestoes('p'), [])

    def test_catalogo(self):
        self.banco.gravar_catalogo([{'item_id': COSMOS, 'nome': 'Cosmos', 'grupo': 'livros'}])
        sug = self.banco.sugestoes('cosmos')
        self.assertEqual((sug[0]['nome'], sug[0]['tipo'], sug[0]['no_catalogo'], sug[0]['contas']),
                         ('Cosmos', 'livros', True, 1))
        self.assertIn(COSMOS, self.banco.ids_no_catalogo())

    def test_config_com_limites(self):
        cfg = self.banco.salvar_config({'intervalo_s': 5, 'rs_por_tcc': '0,85', 'aviso_bipes': False, 'x': 1})
        self.assertEqual((cfg['intervalo_s'], cfg['rs_por_tcc'], cfg['aviso_bipes']), (30, 0.85, False))
        self.assertNotIn('x', cfg)

    def test_buscas_e_avisos(self):
        bid = self.banco.salvar_busca({'nome': 'Cosmos barato', 'filtros': {'preco_max': 3000}, 'lucro_min_rs': 100})
        self.assertEqual(self.banco.busca(bid)['filtros'], {'preco_max': 3000})
        self.assertTrue(self.banco.registrar_aviso(bid, 45520, 2400, 10.0, 'anúncio novo'))
        self.assertFalse(self.banco.registrar_aviso(bid, 45520, 2400, 10.0, 'anúncio novo'))
        self.assertTrue(self.banco.registrar_aviso(bid, 45520, 2000, 10.0, 'baixou'))
        self.assertEqual([a['conta'] for a in self.banco.avisos()], ['memoryzito', 'memoryzito'])
        self.banco.apagar_busca(bid)
        self.assertEqual(self.banco.avisos(), [])

    def test_limpar_antigos(self):
        lista = dict(self.lista)
        del lista[231216]
        self.banco.atualizar_lista(lista)
        self.banco.con.execute("UPDATE anuncios SET ultimo_visto = '2000-01-01T00:00:00' WHERE id = 231216")
        self.assertEqual(self.banco.limpar_antigos(), 1)
        self.assertEqual(self.banco.conta(231216)['itens'], [])


if __name__ == '__main__':
    unittest.main()
