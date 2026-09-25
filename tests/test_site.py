import gzip
import re
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

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


class LerLance(unittest.TestCase):
    def test_conta_sem_lance(self):
        self.assertEqual(site.ler_lance(paginas.conta(45520)), {'pendentes': 0, 'maior': 0})

    def test_conta_com_lance(self):
        # como na conta Viper: "1 lance · maior: 75 TCC"
        botao = ('<a href="#fazer-lance" class="btn mkt-bid-btn" data-open-bid-modal\n\tdata-bid-game="pw187"\n'
                 '\tdata-bid-roleid="77872" data-bid-price="100" data-bid-min="70" data-bid-character="Viper"\n'
                 '\tdata-bid-pending="1"\n\tdata-bid-highest="75"\n\tdata-bid-mine="0">')
        self.assertEqual(site.ler_lance(f'<html>{botao}Fazer lance</a></html>'), {'pendentes': 1, 'maior': 75})

    def test_pagina_sem_botao_de_lance(self):
        self.assertIsNone(site.ler_lance('<html><a href="#comprar">Comprar</a></html>'))


class _SiteLocal(BaseHTTPRequestHandler):
    """Imita o site: responde em gzip, mantém a conexão aberta e fecha a que fica parada."""
    protocol_version = 'HTTP/1.1'
    timeout = 0.3  # o site real fecha a conexão parada depois de alguns segundos

    def setup(self):
        super().setup()
        self.server.conexoes += 1

    def log_message(self, formato, *args):
        pass

    def do_GET(self):
        if self.path == '/volta':
            self.responder(302, b'', {'Location': '/pagina'})
        elif self.path == '/nada':
            self.responder(404, b'nada aqui')
        elif self.path == '/fecha':
            self.close_connection = True
            self.responder(200, gzip.compress('<p>até logo</p>'.encode()), {'Content-Encoding': 'gzip', 'Connection': 'close'})
        else:
            self.responder(200, gzip.compress('<p>olá</p>'.encode()), {'Content-Encoding': 'gzip'})

    def responder(self, status, corpo, extras=None):
        self.send_response(status)
        for k, v in {'Content-Length': str(len(corpo)), **(extras or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)


class Baixar(unittest.TestCase):
    def setUp(self):
        self.servidor = ThreadingHTTPServer(('127.0.0.1', 0), _SiteLocal)
        self.servidor.daemon_threads = True
        self.servidor.conexoes = 0
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.servidor.server_address[1]}'
        mock.patch.object(site, '_PROXY', None).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.fechar)

    def fechar(self):
        if getattr(site._conexao, 'con', None) is not None:
            site._conexao.con.close()
            site._conexao.con = None
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_reaproveita_a_conexao(self):
        self.assertEqual([site.baixar(self.url + '/pagina') for _ in range(3)], ['<p>olá</p>'] * 3)
        self.assertEqual(self.servidor.conexoes, 1)

    def test_redirecionamento_e_erro(self):
        self.assertEqual(site.baixar(self.url + '/volta'), '<p>olá</p>')
        with self.assertRaises(urllib.error.HTTPError) as erro:
            site.baixar(self.url + '/nada')
        self.assertEqual(erro.exception.code, 404)
        self.assertEqual(site.baixar(self.url + '/pagina'), '<p>olá</p>')
        self.assertEqual(self.servidor.conexoes, 1)

    def test_conexao_fechada_pelo_site(self):
        site.baixar(self.url + '/pagina')
        time.sleep(0.8)  # parada: o site fecha a conexão
        self.assertEqual(site.baixar(self.url + '/pagina'), '<p>olá</p>')
        self.assertEqual(site.baixar(self.url + '/fecha'), '<p>até logo</p>')  # "Connection: close"
        self.assertEqual(site.baixar(self.url + '/pagina'), '<p>olá</p>')
        self.assertEqual(self.servidor.conexoes, 3)


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
