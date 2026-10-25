import unittest

from mercado import valor

COSMOS = 72573


def linha(id_, item_id, nome, refino_min, kk):
    return {'id': id_, 'item_id': item_id, 'nome': nome, 'nome_norm': nome.lower(), 'refino_min': refino_min,
            'valor_kk': kk}


def item(item_id, nome, refino=0, qtd=1, secao='inventario'):
    return {'item_id': item_id, 'nome': nome, 'nome_norm': nome.lower(), 'refino': refino, 'qtd': qtd, 'secao': secao}


class Faixas(unittest.TestCase):
    def setUp(self):
        self.tabela = valor.Tabela([linha(1, COSMOS, 'Cosmos', 10, 3000), linha(2, COSMOS, 'Cosmos', 12, 6000)])

    def test_vale_a_maior_faixa_atingida(self):
        self.assertEqual(self.tabela.linha_para(COSMOS, 'cosmos', 12)['id'], 2)
        self.assertEqual(self.tabela.linha_para(COSMOS, 'cosmos', 15)['id'], 2)
        self.assertEqual(self.tabela.linha_para(COSMOS, 'cosmos', 11)['id'], 1)
        self.assertIsNone(self.tabela.linha_para(COSMOS, 'cosmos', 9))

    def test_cosmos_12_nao_soma_as_duas_faixas(self):
        kk, detalhes = valor.avaliar([item(COSMOS, 'Cosmos', refino=12, secao='equipado')], self.tabela)
        self.assertEqual(kk, 6000)
        self.assertEqual([d['valor_id'] for d in detalhes], [2])


class Grupos(unittest.TestCase):
    def setUp(self):
        grupo = lambda id_, gid, refino_min, kk: {**linha(id_, None, f'Grupo {gid}', refino_min, kk), 'grupo_id': gid}
        self.tabela = valor.Tabela([grupo(1, 10, 0, 100), grupo(2, 10, 12, 400), grupo(3, 20, 0, 150),
                                    linha(4, 501, 'Arma Própria', 12, 900), grupo(5, 99, 0, 999)],
                                   {10: [500, 501, 502], 20: [502]})

    def test_vale_para_cada_item_do_grupo_com_as_faixas(self):
        self.assertEqual(self.tabela.linha_para(500, 'x', 0)['id'], 1)
        self.assertEqual(self.tabela.linha_para(500, 'x', 12)['id'], 2)
        self.assertIsNone(self.tabela.linha_para(503, 'x', 12))

    def test_valor_do_item_vem_antes_do_grupo(self):
        self.assertEqual(self.tabela.linha_para(501, 'arma própria', 12)['id'], 4)
        self.assertEqual(self.tabela.linha_para(501, 'arma própria', 8)['id'], 1)  # sem faixa própria que sirva

    def test_item_em_dois_grupos_vale_o_que_da_mais(self):
        self.assertEqual(self.tabela.linha_para(502, 'x', 0)['id'], 3)
        self.assertEqual(self.tabela.linha_para(502, 'x', 12)['id'], 2)

    def test_grupo_que_nao_existe_nao_vale(self):
        self.assertFalse(any(l['id'] == 5 for g in self.tabela.por_grupo.values() for f in g.values() for l in f))


class Avaliar(unittest.TestCase):
    def test_quantidade_vezes_valor(self):
        tabela = valor.Tabela([linha(1, 47498, 'Pérola Astral - Nv 4', 0, 5)])
        kk, detalhes = valor.avaliar([item(47498, 'Pérola Astral - Nv 4', qtd=40),
                                      item(47498, 'Pérola Astral - Nv 4', qtd=10, secao='banco')], tabela)
        self.assertEqual(kk, 250)
        self.assertEqual((detalhes[0]['qtd'], detalhes[0]['secoes']), (50, ['inventario', 'banco']))

    def test_codice_e_recompra_ficam_de_fora(self):
        tabela = valor.Tabela([linha(1, 7, 'Cosmos Vermelho', 0, 100)])
        kk, _ = valor.avaliar([item(7, 'Cosmos Vermelho', secao='codice'),
                               item(7, 'Cosmos Vermelho', secao='recompra'),
                               item(7, 'Cosmos Vermelho', secao='mascotes')], tabela)
        self.assertEqual(kk, 100)

    def test_linha_so_pelo_nome(self):
        tabela = valor.Tabela([{**linha(1, None, 'Item Futuro', 0, 2), 'nome_norm': 'item futuro'}])
        kk, _ = valor.avaliar([item(999, 'Item Futuro', qtd=3)], tabela)
        self.assertEqual(kk, 6)

    def test_ordem_dos_detalhes_e_destaques(self):
        tabela = valor.Tabela([linha(1, COSMOS, 'Cosmos', 10, 3000), linha(2, 38154, 'Pedra do Demônio', 0, 20)])
        _, detalhes = valor.avaliar([item(38154, 'Pedra do Demônio', qtd=24, secao='engastada'),
                                     item(COSMOS, 'Cosmos', refino=12, secao='equipado')], tabela)
        self.assertEqual(valor.destaques(detalhes), [
            {'nome': 'Cosmos', 'refino': 12, 'qtd': 1, 'item_id': COSMOS},
            {'nome': 'Pedra do Demônio', 'refino': 0, 'qtd': 24, 'item_id': 38154}])

    def test_tabela_vazia(self):
        self.assertEqual(valor.avaliar([item(1, 'x')], valor.Tabela([])), (0.0, []))


class Lucro(unittest.TestCase):
    def test_conversao(self):
        valor_rs, preco_rs, lucro_rs, pct = valor.lucro(3240, 900, rs_por_bi=500, rs_por_tcc=1)
        self.assertEqual((valor_rs, preco_rs, lucro_rs), (1620, 900, 720))
        self.assertAlmostEqual(pct, 0.4444, places=3)

    def test_tcc_com_desconto(self):
        self.assertEqual(valor.lucro(0, 1000, 500, 0.8)[1], 800)

    def test_sem_valor(self):
        self.assertEqual(valor.lucro(0, 100, 500, 1)[3], 0.0)


if __name__ == '__main__':
    unittest.main()
