import re
import unittest

from mercado import site
from tests import paginas


def total(itens, **filtro):
    return sum(i.qtd for i in itens if all(getattr(i, k) == v for k, v in filtro.items()))


class LerLista(unittest.TestCase):
    def test_le_todos_os_cards(self):
        anuncios = site.ler_lista(paginas.lista())
        self.assertGreater(len(anuncios), 1000)
        self.assertEqual(anuncios[45520], site.Anuncio(
            id=45520, preco=2400, nivel=105, ocupacao=6, nome='memoryzito',
            classe='Arqueiro', ceu='Majestoso VIII'))

    def test_pagina_sem_cards(self):
        self.assertEqual(site.ler_lista('<html><body>manutenção</body></html>'), {})


class LerConta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.minha = site.ler_conta(paginas.conta(45520))
        cls.cosmos = site.ler_conta(paginas.conta(231216))

    def test_equipamento(self):
        equipado = [i for i in self.minha if i.secao == 'equipado']
        self.assertEqual(len(equipado), 30)
        arma = equipado[0]
        self.assertEqual((arma.item_id, arma.nome, arma.refino), (50171, '★★★Caçador Penado', 12))

    def test_cartas_equipadas_nao_se_repetem(self):
        secoes = {i.secao for i in self.minha}
        self.assertNotIn('cartas equipadas', secoes)
        self.assertEqual(sum(1 for i in self.minha if i.nome == 'Tensa' and i.secao == 'equipado'), 1)

    def test_boneco_do_topo_ignorado(self):
        self.assertNotIn(None, {i.secao for i in self.minha})
        self.assertNotIn('outros', {i.secao for i in self.minha})

    def test_secoes(self):
        secoes = {i.secao for i in self.minha}
        self.assertTrue({'equipado', 'inventario', 'banco', 'cartas', 'runas', 'mascotes',
                         'codice', 'engastada'} <= secoes)

    def test_quantidades_somam_pilhas(self):
        self.assertEqual(total(self.minha, nome='Pedra Perfeita'), 8008 + 39996)

    def test_cosmos(self):
        cosmos = [i for i in self.cosmos if i.item_id == site.COSMOS_ID]
        self.assertEqual([(c.secao, c.nome, c.refino) for c in cosmos], [('equipado', 'Cosmos', 12)])

    def test_pedras_engastadas(self):
        self.assertEqual(total(self.cosmos, secao='engastada', item_id=38154), 24)
        demonio = next(i for i in self.cosmos if i.item_id == 38154)
        self.assertEqual((demonio.nome, demonio.efeito), ('Pedra do Demônio', 'Nível de Ataque +3'))
        self.assertEqual(total(self.minha, secao='engastada', item_id=38153), 24)

    def test_tooltip_so_texto_e_cor(self):
        arma = next(i for i in self.minha if i.secao == 'equipado')
        self.assertEqual(arma.tooltip[0], [['★★★Caçador Penado +12', '#ffffff']])
        pedra = arma.tooltip[2]
        self.assertEqual(pedra[0], {'i': 58680})
        self.assertEqual(pedra[1], ['Pedra do Brilho Flamejante Ataque +130', '#5fbab9'])
        textos = [seg[0] for i in self.minha for linha in i.tooltip for seg in linha if isinstance(seg, list)]
        self.assertFalse([t for t in textos if re.search(r'<[a-zA-Z/]', t)])

    def test_pagina_sem_itens(self):
        self.assertEqual(site.ler_conta('<html><body>anúncio removido</body></html>'), [])


class Auxiliares(unittest.TestCase):
    def test_separar_pedra(self):
        self.assertEqual(site.separar_pedra(' Pedra do Demônio Nível de Ataque +3'),
                         ('Pedra do Demônio', 'Nível de Ataque +3'))
        self.assertEqual(site.separar_pedra('Pedra do Brilho Flamejante Ataque +130'),
                         ('Pedra do Brilho Flamejante', 'Ataque +130'))
        self.assertEqual(site.separar_pedra('Espírito Sagrado: Nível 1'), ('Espírito Sagrado', 'Nível 1'))
        self.assertEqual(site.separar_pedra('Joia Misteriosa'), ('Joia Misteriosa', ''))

    def test_cor(self):
        self.assertEqual(site._cor('color: rgb(95, 186, 185);'), '#5fbab9')
        self.assertEqual(site._cor('color:#FFF'), '#ffffff')
        self.assertIsNone(site._cor('background-color:#000'))

    def test_norm(self):
        self.assertEqual(site.norm('  ★★★Caçador   Penado '), '★★★cacador penado')


if __name__ == '__main__':
    unittest.main()
