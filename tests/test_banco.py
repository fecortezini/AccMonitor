import dataclasses
import itertools
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mercado import site, valor
from mercado.banco import Banco
from tests import paginas

COSMOS, DEMONIO = site.COSMOS_ID, 38154
PERFEITA, IMORTAL = 5639, 11208  # Pedra Perfeita e Pedra Imortal: as duas contas salvas têm
AMULETO = 47234  # Amuleto da Alma Perdida: 45520 tem 255 e 231216 tem 9.289


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
                                 'reativados': [], 'removidos': 1, 'sumiram': [231216]})
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

    def test_pelo_menos_um_item(self):
        # "Tem pelo menos um": basta um dos itens, como a arma de um rank, que tem um nome em cada classe
        cosmos = {'item_id': COSMOS, 'nome': 'Cosmos', 'refino_min': 12}  # só a 231216 (Bárbaro) tem
        perfeita = {'nome': 'pedra perfeita', 'qtd_min': 48004}          # só a 45520 (Arqueiro) tem tantas
        self.assertEqual(self.ids({'algum': [cosmos]}), [231216])
        self.assertEqual(sorted(self.ids({'algum': [cosmos, perfeita]})), [45520, 231216])
        # as condições voltam para a aba Pesquisados dos detalhes, que mostra qual delas a conta tem
        self.assertEqual([(c['item_id'], c['refino_min'], c['qtd_min'])
                          for c in self.banco.buscar({'algum': [cosmos, perfeita]})['busca_algum']],
                         [(COSMOS, 12, 1), (None, 0, 48004)])
        self.assertEqual(self.ids({'algum': [{**cosmos, 'refino_min': 13}, {**perfeita, 'qtd_min': 48005}]}), [])
        # vale junto com os outros filtros, e o "Tem item" continua exigindo tudo o que pede
        self.assertEqual(self.ids({'algum': [cosmos, perfeita], 'classes': ['Arqueiro']}), [45520])
        self.assertEqual(self.ids({'algum': [cosmos, perfeita], 'itens': [{'item_id': DEMONIO, 'onde': 'engastada'}]}),
                         [231216])

    def test_pelo_menos_um_com_contas_nao_lidas(self):
        algum = [{'item_id': COSMOS, 'refino_min': 12}, {'nome': 'pedra perfeita', 'qtd_min': 48004}]
        r = self.banco.buscar({'algum': algum}, lambda cond: {231216, 3152} if cond.get('item_id') == COSMOS else None)
        por_id = {c['id']: c for c in r['contas']}
        self.assertEqual(sorted(por_id), [3152, 45520, 231216])
        self.assertEqual([rid for rid, c in por_id.items() if c['a_confirmar']], [3152])  # a busca do site diz que tem
        # sem "Tem item" não há itens pesquisados: nem colunas, nem quantidades
        self.assertEqual((r['a_confirmar'], r['busca_itens'], por_id[45520]['qtd_busca']), (1, [], None))

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

    def qtds(self, filtros, site_ids=None):
        return [(c['id'], c['qtd_busca']) for c in self.banco.buscar(filtros, site_ids)['contas']]

    def test_quantidade_dos_itens_pesquisados(self):
        # 45520: Pedra Perfeita 39.996 no banco + 8.008 na mochila, Pedra Imortal 6.856 no banco;
        # 231216: 2.310 e 14.719, as duas na mochila
        itens = [{'item_id': PERFEITA, 'nome': 'Pedra Perfeita'}, {'item_id': IMORTAL, 'nome': 'Pedra Imortal'}]
        r = self.banco.buscar({'itens': itens, 'ordem': 'itens'})
        self.assertEqual([(c['id'], c['qtd_busca']) for c in r['contas']], [(45520, [48004, 6856]), (231216, [2310, 14719])])
        self.assertEqual([(b['item_id'], b['nome'], b['qtd_min'], b['onde']) for b in r['busca_itens']],
                         [(PERFEITA, 'Pedra Perfeita', 1, ''), (IMORTAL, 'Pedra Imortal', 1, '')])
        # "onde" e o nome valem para a contagem do mesmo jeito que valem para o filtro
        self.assertEqual(self.qtds({'itens': [{'nome': 'pedra perfeita', 'onde': 'banco'}]}), [(45520, [39996])])
        self.assertEqual(self.qtds({'itens': [{'item_id': DEMONIO, 'onde': 'engastada'}]}), [(231216, [24])])
        self.assertEqual(self.qtds({'itens': [{'nome': 'PEDRA DO DEM'}]}), [(231216, [24])])  # parte do nome
        self.assertEqual(self.qtds({'itens': [{'item_id': COSMOS, 'refino_min': 12}]}), [(231216, [1])])
        self.assertEqual(self.qtds({'itens': [{'item_id': COSMOS, 'refino_min': 13}]}), [])
        self.assertIsNone(self.banco.buscar({'nome': 'memoryzito'})['contas'][0]['qtd_busca'])

    def test_ordem_pelos_itens_pesquisados(self):
        itens = [{'item_id': PERFEITA}, {'item_id': IMORTAL}]
        self.assertEqual(self.ids({'itens': itens, 'ordem': 'itens'}), [45520, 231216])  # 54.860 x 17.029 unidades
        self.assertEqual(self.ids({'itens': itens, 'ordem': 'item:1'}), [231216, 45520])  # mais Pedra Imortal
        self.assertEqual(self.ids({'itens': itens, 'ordem': 'item:9'}), [45520, 231216])  # condição que não existe: soma
        # Pedra Imortal: 231216 tem mais (14.719 x 6.856), mas 45520 sai mais barata por unidade (2.400 TCC x 15.000)
        imortal = [{'item_id': IMORTAL}]
        self.assertEqual(self.ids({'itens': imortal, 'ordem': 'itens'}), [231216, 45520])
        self.assertEqual(self.ids({'itens': imortal, 'ordem': 'preco_item'}), [45520, 231216])
        # sem condição de item essas ordens não se aplicam e vale a ordem padrão
        self.assertEqual(len(self.ids({'ordem': 'itens'})), len(self.lista))

    def test_ordem_das_condicoes_nao_importa(self):
        # Em qualquer ordem dos itens, a lista e as unidades de cada item são as mesmas, e o preço por unidade
        # usa a soma de todos: 45520 sai a 2.400 ÷ 55.115 e 231216 a 15.000 ÷ 26.318 TCC. Se valesse só o
        # primeiro item, com o Amuleto na frente 231216 viria antes (15.000 ÷ 9.289 contra 2.400 ÷ 255).
        nomes = {PERFEITA: 'Pedra Perfeita', IMORTAL: 'Pedra Imortal', AMULETO: 'Amuleto da Alma Perdida'}
        esperado = [(45520, {PERFEITA: 48004, IMORTAL: 6856, AMULETO: 255}),
                    (231216, {PERFEITA: 2310, IMORTAL: 14719, AMULETO: 9289})]
        for ordem_itens in itertools.permutations(nomes):
            itens = [{'item_id': i, 'nome': nomes[i]} for i in ordem_itens]
            for ordem in ('preco_item', 'itens'):
                contas = self.banco.buscar({'itens': itens, 'ordem': ordem})['contas']
                self.assertEqual([(c['id'], dict(zip(ordem_itens, c['qtd_busca']))) for c in contas], esperado,
                                 (ordem_itens, ordem))
            # "Mais <item>" segue o item, em qualquer posição
            self.assertEqual(self.ids({'itens': itens, 'ordem': f'item:{ordem_itens.index(AMULETO)}'}), [231216, 45520])

    def test_contas_a_confirmar_vao_para_o_fim(self):
        # 3152 (20.000 TCC) e 1856 (15.000 TCC) ainda não foram lidas: não se sabe quanto têm
        filtro = {'itens': [{'item_id': COSMOS, 'refino_min': 12}], 'ordem': 'itens'}
        self.assertEqual(self.qtds(filtro, lambda cond: {231216, 3152, 1856}),
                         [(231216, [1]), (1856, None), (3152, None)])


class Grupos(BaseBanco):
    """Grupos de itens, como as armas de um rank, que têm um nome em cada classe."""

    def setUp(self):
        super().setUp()
        # um item que só a 45520 tem, para o grupo achar as duas contas
        ids = {rid: {it.item_id for it in itens if it.item_id} for rid, itens in self.itens.items()}
        self.so_45520 = min(ids[45520] - ids[231216])
        self.gid = self.banco.salvar_grupo({'nome': 'Armas do rank', 'itens': [
            {'item_id': COSMOS, 'nome': 'Cosmos'}, {'item_id': self.so_45520, 'nome': 'Outra'},
            {'item_id': COSMOS, 'nome': 'Cosmos repetido'}, {'nome': 'sem id'}]})

    def ids(self, filtros):
        return sorted(c['id'] for c in self.banco.buscar(filtros)['contas'])

    def test_criar_editar_e_apagar(self):
        self.assertEqual([(g['nome'], [it['item_id'] for it in g['itens']]) for g in self.banco.grupos()],
                         [('Armas do rank', [COSMOS, self.so_45520])])  # sem repetir e só itens com id
        with self.assertRaises(ValueError):
            self.banco.salvar_grupo({'nome': 'Armas do rank', 'itens': []})  # nome repetido
        with self.assertRaises(ValueError):
            self.banco.salvar_grupo({'nome': ' ', 'itens': []})
        self.banco.salvar_grupo({'nome': 'Armas UP4', 'itens': [{'item_id': COSMOS}]}, self.gid)
        self.assertEqual([g['nome'] for g in self.banco.grupos()], ['Armas UP4'])
        with self.assertRaises(KeyError):
            self.banco.salvar_grupo({'nome': 'Outro'}, 999)
        self.banco.apagar_grupo(self.gid)
        self.assertEqual(self.banco.grupos(), [])

    def test_no_tem_pelo_menos_um_vale_qualquer_item_do_grupo(self):
        grupo = {'grupo_id': self.gid, 'nome': 'Armas do rank'}
        self.assertEqual(self.ids({'algum': [grupo]}), [45520, 231216])
        self.assertEqual(self.ids({'algum': [{**grupo, 'refino_min': 12}]}), [231216])  # só o Cosmos +12
        self.assertEqual(self.ids({'algum': [grupo], 'classes': ['Arqueiro']}), [45520])
        r = self.banco.buscar({'algum': [grupo]})
        self.assertEqual((r['busca_algum'][0]['itens'], r['busca_algum'][0]['nome'], r['busca_algum'][0]['todos']),
                         ([COSMOS, self.so_45520], 'Armas do rank', False))

    def test_no_tem_item_o_grupo_precisa_de_todos(self):
        """Como as cartas de um combo: a conta precisa ter cada item do grupo, e cada um na quantidade pedida."""
        unidades = {}  # rid -> {item_id: unidades}, só das seções que a busca olha
        for rid, itens in self.itens.items():
            for it in itens:
                if it.item_id and it.secao not in valor.SECOES_FORA:
                    unidades.setdefault(rid, {}).setdefault(it.item_id, 0)
                    unidades[rid][it.item_id] += it.qtd
        so_45520 = sorted(set(unidades[45520]) - set(unidades[231216]))
        so_231216 = min(set(unidades[231216]) - set(unidades[45520]))
        combo = self.banco.salvar_grupo({'nome': 'Combo', 'itens': [{'item_id': i} for i in so_45520[:2]]})
        metade = self.banco.salvar_grupo({'nome': 'Metade', 'itens': [{'item_id': so_45520[0]}, {'item_id': so_231216}]})
        cond = {'grupo_id': combo, 'nome': 'Combo'}
        self.assertEqual(self.ids({'itens': [cond]}), [45520])
        self.assertEqual(self.ids({'itens': [{'grupo_id': metade, 'nome': 'Metade'}]}), [])  # nenhuma tem os dois
        self.assertEqual(self.ids({'algum': [{'grupo_id': metade, 'nome': 'Metade'}]}), [45520, 231216])
        r = self.banco.buscar({'itens': [cond]})
        self.assertEqual((r['busca_itens'][0]['itens'], r['busca_itens'][0]['todos']), (so_45520[:2], True))
        menor = min(unidades[45520][i] for i in so_45520[:2])
        self.assertEqual(r['contas'][0]['qtd_busca'], [sum(unidades[45520][i] for i in so_45520[:2])])
        self.assertEqual(self.ids({'itens': [{**cond, 'qtd_min': menor}]}), [45520])
        self.assertEqual(self.ids({'itens': [{**cond, 'qtd_min': menor + 1}]}), [])

    def test_grupo_apagado_nao_acha_nada(self):
        self.banco.apagar_grupo(self.gid)
        self.assertEqual(self.ids({'algum': [{'grupo_id': self.gid, 'nome': 'Armas do rank'}]}), [])

    def test_valor_do_grupo(self):
        self.banco.salvar_valor({'grupo_id': self.gid, 'valor_kk': 100})
        self.banco.salvar_valor({'grupo_id': self.gid, 'refino_min': 12, 'valor_kk': 500})
        self.assertEqual(self.banco.anuncio(231216)['valor_kk'], 500)  # o Cosmos +12, pela faixa de +12
        so_45520 = sum(it.qtd for it in self.itens[45520] if it.item_id == self.so_45520 and it.secao not in ('codice', 'recompra'))
        self.assertEqual(self.banco.anuncio(45520)['valor_kk'], 100 * so_45520)
        linha = next(v for v in self.banco.valores() if v['refino_min'] == 0)
        self.assertEqual((linha['nome'], linha['tipo'], linha['itens'], linha['contas']),
                         ('Armas do rank', 'grupo', [COSMOS, self.so_45520], 2))
        with self.assertRaises(ValueError):
            self.banco.salvar_valor({'grupo_id': self.gid, 'valor_kk': 50})  # faixa repetida
        self.assertEqual(self.banco.ids_valorizados(), {COSMOS, self.so_45520})
        # o valor do próprio item vem antes do grupo
        self.banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        self.assertEqual(self.banco.anuncio(231216)['valor_kk'], 3000)
        detalhe = self.banco.conta(45520)['detalhes'][0]
        self.assertEqual((detalhe['nome'], detalhe['grupo_id']), ('Armas do rank', self.gid))
        # renomear o grupo muda o nome do valor; apagar o grupo apaga o valor
        self.banco.salvar_grupo({'nome': 'Armas UP4', 'itens': [{'item_id': self.so_45520}]}, self.gid)
        self.assertEqual({v['nome'] for v in self.banco.valores() if v['grupo_id']}, {'Armas UP4'})
        self.banco.apagar_grupo(self.gid)
        self.assertEqual([v['nome'] for v in self.banco.valores()], ['Cosmos'])
        self.assertEqual(self.banco.anuncio(45520)['valor_kk'], 0)
        with self.assertRaises(ValueError):
            self.banco.salvar_valor({'grupo_id': self.gid, 'valor_kk': 100})  # grupo que não existe

    def test_itens_do_grupo_sao_lidos_antes(self):
        self.banco.salvar_busca({'nome': 'Rank', 'filtros': {'algum': [{'grupo_id': self.gid, 'nome': 'Armas do rank'}]}})
        self.assertEqual(self.banco.ids_valorizados(), {COSMOS, self.so_45520})


class Lances(BaseBanco):
    def test_gravar_e_lance_novo(self):
        self.assertFalse(self.banco.gravar_lance(45520, {'pendentes': 1, 'maior': 1700}))  # a primeira vez é a base
        conta = self.banco.buscar({'nome': 'memoryzito'})['contas'][0]
        self.assertEqual((conta['lances'], conta['maior_lance'], conta['lance_novo_em']), (1, 1700, None))
        self.assertFalse(self.banco.gravar_lance(45520, {'pendentes': 1, 'maior': 1700}))  # igual: nada novo
        self.assertTrue(self.banco.gravar_lance(45520, {'pendentes': 2, 'maior': 1800}))
        self.assertIsNotNone(self.banco.anuncio(45520)['lance_novo_em'])
        self.assertFalse(self.banco.gravar_lance(1, {'pendentes': 1, 'maior': 1}))  # conta que não existe

    def test_qual_conta_reler(self):
        self.banco.gravar_lance(231216, {'pendentes': 0, 'maior': 0}, quando='2026-01-01T10:00:00')
        self.assertEqual(self.banco.lance_velho([231216, 45520], '2026-01-01T09:00:00'), 45520)  # nunca vista
        self.assertEqual(self.banco.lance_velho([231216, 45520], '2026-01-01T11:00:00'), 231216)  # na ordem dada
        self.assertIsNone(self.banco.lance_velho([], '2026-01-01T11:00:00'))
        # das outras: as nunca vistas primeiro, das mais baratas; só as já lidas
        self.assertEqual(self.banco.lance_mais_velho(), 45520)
        self.assertEqual(self.banco.lance_mais_velho(fora={45520}), 231216)

    def test_banco_antigo_ganha_as_colunas(self):
        caminho = Path(self.pasta) / 'antigo.db'
        con = sqlite3.connect(caminho)
        con.execute("CREATE TABLE anuncios (id INTEGER PRIMARY KEY, nome TEXT NOT NULL DEFAULT '', "
                    "nome_norm TEXT NOT NULL DEFAULT '', classe TEXT NOT NULL DEFAULT '', ocupacao INTEGER NOT NULL DEFAULT 0, "
                    "nivel INTEGER NOT NULL DEFAULT 0, ceu TEXT NOT NULL DEFAULT '', ceu_norm TEXT NOT NULL DEFAULT '', "
                    "preco INTEGER NOT NULL, primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL, "
                    "nova INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1, itens_lidos_em TEXT, "
                    "preco_lido INTEGER, valor_kk REAL, destaques TEXT)")
        con.close()
        antigo = Banco(caminho)
        self.assertLessEqual({'lances', 'maior_lance', 'lances_em', 'lance_novo_em'},
                             {r[1] for r in antigo.con.execute('PRAGMA table_info(anuncios)')})
        antigo.fechar()


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
        self.assertEqual(self.banco.config()['leituras_simultaneas'], 1)
        cfg = self.banco.salvar_config({'intervalo_s': 5, 'rs_por_tcc': '0,85', 'aviso_bipes': False, 'x': 1,
                                        'leituras_simultaneas': 50})
        self.assertEqual((cfg['intervalo_s'], cfg['rs_por_tcc'], cfg['aviso_bipes'], cfg['leituras_simultaneas']),
                         (30, 0.85, False, 8))
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

    def test_itens_das_buscas_sao_lidos_antes(self):
        # os itens das buscas salvas, dos dois tipos de condição, fazem as contas que os têm subirem na fila
        self.banco.salvar_busca({'nome': 'Arma do rank', 'filtros': {
            'itens': [{'item_id': COSMOS, 'nome': 'Cosmos'}],
            'algum': [{'item_id': DEMONIO, 'nome': 'Pedra do Demônio'}, {'item_id': None, 'nome': 'relíquia'}]}})
        self.assertEqual(self.banco.ids_valorizados(), {COSMOS, DEMONIO})

    def test_limpar_antigos(self):
        lista = dict(self.lista)
        del lista[231216]
        self.banco.atualizar_lista(lista)
        self.banco.con.execute("UPDATE anuncios SET ultimo_visto = '2000-01-01T00:00:00' WHERE id = 231216")
        self.assertEqual(self.banco.limpar_antigos(), 1)
        self.assertEqual(self.banco.conta(231216)['itens'], [])


class Favoritas(BaseBanco):
    def tirar_do_ar(self, rid):
        lista = dict(self.lista)
        del lista[rid]
        self.banco.atualizar_lista(lista)

    def test_marcar_e_desmarcar(self):
        self.banco.marcar_favorita(231216)
        self.banco.marcar_favorita(231216)  # de novo: nada muda
        favoritas = self.banco.favoritas()
        self.assertEqual([(f['id'], f['nome'], f['situacao']['situacao']) for f in favoritas],
                         [(231216, 'TooSadToDie', 'a_venda')])
        self.assertEqual(favoritas[0]['anuncio']['preco'], 15000)
        self.assertTrue(next(c for c in self.banco.buscar({})['contas'] if c['id'] == 231216)['favorita'])
        self.assertFalse(next(c for c in self.banco.buscar({})['contas'] if c['id'] == 45520)['favorita'])
        conta = self.banco.conta(231216)
        self.assertEqual((conta['favorita'], conta['situacao']['situacao']), (True, 'a_venda'))
        self.banco.desmarcar_favorita(231216)
        self.assertEqual(self.banco.favoritas(), [])
        self.assertEqual((self.banco.conta(231216)['favorita'], self.banco.conta(231216)['situacao']), (False, None))

    def test_conta_que_nao_existe(self):
        with self.assertRaises(KeyError):
            self.banco.marcar_favorita(999)

    def test_marcar_conta_que_ja_saiu_do_ar_comeca_conferindo(self):
        self.tirar_do_ar(231216)
        self.banco.marcar_favorita(231216)
        s = self.banco.situacao_favorita(231216)
        self.assertEqual(s['situacao'], 'confirmando')
        self.assertEqual(s['visto_antes'], self.banco.anuncio(231216)['ultimo_visto'])
        self.assertEqual([f['id'] for f in self.banco.buscas_de_venda()], [231216])  # a busca é já

    def test_agenda_das_buscas_de_venda(self):
        self.banco.marcar_favorita(231216)
        self.banco.definir_situacao(231216, 'confirmando', sumiu_em='2026-10-28T13:00:00',
                                    visto_antes='2026-10-28T12:59:30', proxima_em='2026-10-28T13:01:00')
        self.assertEqual(self.banco.proxima_busca_de_venda(), '2026-10-28T13:01:00')
        self.assertEqual(self.banco.buscas_de_venda('2026-10-28T13:00:59'), [])
        self.assertEqual([(f['id'], f['nome'], f['tentativas']) for f in self.banco.buscas_de_venda('2026-10-28T13:01:00')],
                         [(231216, 'TooSadToDie', 0)])
        self.banco.agendar_busca_de_venda(231216, 1, '2026-10-28T13:03:00')
        self.assertEqual(self.banco.proxima_busca_de_venda(), '2026-10-28T13:03:00')
        self.banco.definir_situacao(231216, 'retirada')
        self.assertIsNone(self.banco.proxima_busca_de_venda())

    def test_situacao_de_quem_nao_e_favorita(self):
        self.assertFalse(self.banco.definir_situacao(231216, 'a_venda'))  # desmarcada nesse meio-tempo
        self.assertIsNone(self.banco.situacao_favorita(231216))

    def test_ordem_confirmando_primeiro(self):
        for rid in (45520, 231216, 3152):
            self.banco.marcar_favorita(rid)
        self.banco.con.execute("UPDATE situacao_favoritas SET desde = '2026-10-01T00:00:00' WHERE id = 45520")
        self.banco.definir_situacao(45520, 'confirmando', proxima_em='2099-01-01T00:00:00')
        self.banco.con.execute("UPDATE situacao_favoritas SET desde = '2026-10-02T00:00:00' WHERE id = 3152")
        self.assertEqual([f['id'] for f in self.banco.favoritas()], [45520, 231216, 3152])

    def test_itens_das_favoritas_nao_sao_limpos(self):
        self.banco.marcar_favorita(231216)
        self.tirar_do_ar(231216)
        self.banco.con.execute("UPDATE anuncios SET ultimo_visto = '2000-01-01T00:00:00' WHERE id = 231216")
        self.assertEqual(self.banco.limpar_antigos(), 0)
        self.assertTrue(self.banco.conta(231216)['itens'])

    def test_vendida_e_esquecida(self):
        self.banco.marcar_favorita(231216)
        self.tirar_do_ar(231216)
        self.banco.esquecer_vendida(231216)
        self.assertEqual(self.banco.favoritas(), [])
        self.assertIsNone(self.banco.situacao_favorita(231216))
        conta = self.banco.conta(231216)
        self.assertEqual((conta['itens'], conta['anuncio']['lida'], conta['favorita']), ([], False, False))

    def test_avisos_das_favoritas_junto_com_os_das_buscas(self):
        busca = self.banco.salvar_busca({'nome': 'Tudo', 'filtros': {}})
        self.banco.registrar_aviso(busca, 45520, 2400, None, 'anúncio novo')
        self.banco.marcar_favorita(231216)
        self.banco.registrar_aviso_favorita(231216, 'TooSadToDie', 'saiu', 'saiu do mercado', 15000)
        self.banco.con.execute("UPDATE avisos SET quando = '2026-10-28T10:00:00'")
        self.banco.con.execute("UPDATE avisos_favoritas SET quando = '2026-10-28T11:00:00'")
        avisos = self.banco.avisos()
        self.assertEqual([(a['busca'], a['conta'], a['motivo']) for a in avisos],
                         [('★ Favorita', 'TooSadToDie', 'saiu do mercado'), ('Tudo', 'memoryzito', 'anúncio novo')])
        self.assertEqual((avisos[0]['classe'], avisos[0]['nivel'], avisos[0]['evento']), ('Bárbaro', 105, 'saiu'))


class ContasDeOutroPC(BaseBanco):
    """O banco da BaseBanco é o PC que leu as contas; o outro só tem a lista."""

    def setUp(self):
        super().setUp()
        self.banco.salvar_config({'telegram_token': 'segredo'})
        self.banco.gravar_lance(231216, {'pendentes': 2, 'maior': 1800})
        self.arquivo = Path(self.pasta) / 'contas.db'
        self.outro = Banco(Path(self.pasta) / 'outro.db')
        self.outro.atualizar_lista(self.lista)
        self.outro.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})

    def tearDown(self):
        self.outro.fechar()
        super().tearDown()

    def test_exporta_so_as_lidas_no_ar(self):
        lista = dict(self.lista)
        del lista[45520]
        self.banco.atualizar_lista(lista)
        self.assertEqual(self.banco.exportar_contas(self.arquivo), 1)
        con = sqlite3.connect(self.arquivo)
        try:
            self.assertEqual([r[0] for r in con.execute('SELECT id FROM anuncios')], [231216])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM itens').fetchone()[0], len(self.itens[231216]))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM config').fetchone()[0], 0)  # o Telegram fica aqui
        finally:
            con.close()

    def test_junta_as_que_faltam_ler(self):
        self.banco.exportar_contas(self.arquivo)
        self.assertEqual(self.outro.juntar_contas(self.arquivo), 2)
        self.assertEqual([c['id'] for c in self.outro.contas_para_ler()],
                         [c['id'] for c in self.banco.contas_para_ler()])  # as duas não são lidas de novo
        conta, original = self.outro.conta(231216), self.banco.conta(231216)
        self.assertEqual((conta['itens'], conta['tooltips']), (original['itens'], original['tooltips']))
        a = self.outro.anuncio(231216)
        self.assertEqual((a['valor_kk'], a['maior_lance']), (6000, 1800))  # o valor é pela tabela deste PC
        tipo = self.outro.con.execute('SELECT tipo FROM conhecidos WHERE item_id = ?', (DEMONIO,)).fetchone()
        self.assertEqual(tipo[0], 'pedra')

    def test_nao_mexe_no_que_este_pc_ja_tem(self):
        lista = dict(self.lista)
        lista[1] = site.Anuncio(id=1, preco=50, nivel=105, ocupacao=6, nome='Novata', classe='Arqueiro', ceu='')
        self.banco.atualizar_lista(lista)
        self.banco.gravar_itens(1, self.itens[45520], 50)
        self.banco.exportar_contas(self.arquivo)
        lista = dict(self.lista)
        lista[231216] = dataclasses.replace(lista[231216], preco=lista[231216].preco - 100)
        self.outro.atualizar_lista(lista)
        self.outro.gravar_itens(45520, self.itens[45520][:3], lista[45520].preco, quando='2026-01-01T10:00:00')
        self.assertEqual(self.outro.juntar_contas(self.arquivo), 0)
        a = self.outro.anuncio(45520)  # já lida aqui: fica como estava
        self.assertEqual((a['itens_lidos_em'], len(self.outro.conta(45520)['itens'])), ('2026-01-01T10:00:00', 3))
        self.assertIn(231216, [c['id'] for c in self.outro.contas_para_ler()])  # lá foi lida por outro preço
        self.assertIsNone(self.outro.anuncio(1))  # quem diz que contas estão no ar é a lista deste PC

    def test_lances_das_favoritas_ficam(self):
        self.banco.exportar_contas(self.arquivo)
        self.outro.marcar_favorita(231216)
        self.outro.juntar_contas(self.arquivo)
        a = self.outro.anuncio(231216)
        self.assertIsNotNone(a['itens_lidos_em'])
        self.assertIsNone(a['lances_em'])  # os lances das favoritas cada PC lê de perto

    def test_arquivo_sem_contas(self):
        sqlite3.connect(self.arquivo).close()
        with self.assertRaises(ValueError):
            self.outro.juntar_contas(self.arquivo)
        self.banco.exportar_contas(self.arquivo)  # o banco continua bom para juntar depois
        self.assertEqual(self.outro.juntar_contas(self.arquivo), 2)


if __name__ == '__main__':
    unittest.main()
