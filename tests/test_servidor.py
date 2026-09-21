import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from mercado import site
from mercado.banco import Banco
from mercado.coletor import Estado
from mercado.servidor import App, iniciar
from tests import paginas

COSMOS = site.COSMOS_ID


class ColetorFalso:
    def __init__(self):
        self.consultas = 0
        self.pedidos = []

    def ids_do_site(self, cond):
        return {231216, 3152} if cond.get('item_id') == COSMOS else None

    def consultar_agora(self):
        self.consultas += 1

    def ler_agora(self, rid):
        self.pedidos.append(rid)

    def posicao_na_fila(self, rid):
        return rid in self.pedidos

    def repriorizar(self):
        pass


class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.mkdtemp()
        cls.banco = Banco(Path(cls.pasta) / 'teste.db')
        lista = site.ler_lista(paginas.lista())
        cls.banco.atualizar_lista(lista)
        for rid in (45520, 231216):
            cls.banco.gravar_itens(rid, site.ler_conta(paginas.conta(rid)), lista[rid].preco)
        cls.coletor = ColetorFalso()
        cls.avisos = []
        cls.app = App(cls.banco, cls.coletor, Estado(),
                      notificar=lambda cfg, *args, esperar=False: cls.avisos.append(args) or [])
        cls.servidor, cls.porta = iniciar(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.banco.fechar()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def chamar(self, metodo, caminho, corpo=None, token=True, host=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.porta}{caminho}', method=metodo,
                                     data=json.dumps(corpo).encode() if corpo is not None else None)
        if token:
            req.add_header('X-Token', self.app.token)
        if host:
            req.add_header('Host', host)
        if corpo is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_sem_token_ou_com_outro_host(self):
        self.assertEqual(self.chamar('GET', '/api/estado', token=False)[0], 403)
        self.assertEqual(self.chamar('GET', '/api/estado', host='mal.intencionado.com')[0], 403)

    def test_estado(self):
        status, dados = self.chamar('GET', '/api/estado')
        self.assertEqual(status, 200)
        self.assertEqual(dados['lidas'], 2)
        self.assertGreater(dados['ativas'], 1000)
        self.assertIn('Arqueiro', [c['classe'] for c in dados['classes']])

    def test_buscar_com_contas_a_confirmar(self):
        status, dados = self.chamar('POST', '/api/buscar', {'itens': [{'item_id': COSMOS, 'refino_min': 12}]})
        self.assertEqual(status, 200)
        self.assertEqual({c['id']: c['a_confirmar'] for c in dados['contas']}, {231216: False, 3152: True})

    def test_conta(self):
        status, dados = self.chamar('GET', '/api/conta/45520')
        self.assertEqual(status, 200)
        self.assertEqual(dados['anuncio']['nome'], 'memoryzito')
        self.assertTrue(dados['url'].endswith('/pw187/details/45520'))
        self.assertEqual(self.chamar('GET', '/api/conta/1')[0], 404)

    def test_sugestoes(self):
        _, dados = self.chamar('GET', '/api/sugestoes?q=pedra%20do%20dem')
        self.assertEqual(dados['itens'][0]['nome'], 'Pedra do Demônio')

    def test_valores(self):
        status, dados = self.chamar('POST', '/api/valores', {'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3000})
        self.assertEqual(status, 200)
        vid = dados['id']
        self.assertEqual(self.chamar('POST', '/api/valores', {'nome': 'Cosmos', 'item_id': COSMOS,
                                                               'valor_kk': 1})[0], 400)
        self.assertEqual(self.chamar('PUT', f'/api/valores/{vid}', {'nome': 'Cosmos', 'item_id': COSMOS,
                                                                     'valor_kk': 4000})[0], 200)
        _, lista = self.chamar('GET', '/api/valores')
        self.assertEqual([(v['nome'], v['valor_kk'], v['contas']) for v in lista['valores']], [('Cosmos', 4000, 1)])
        self.assertEqual(lista['resumo']['melhor']['id'], 231216)
        self.assertEqual(self.chamar('DELETE', f'/api/valores/{vid}')[0], 200)
        self.assertEqual(self.chamar('PUT', '/api/valores/999999', {'nome': 'x', 'valor_kk': 1})[0], 404)

    def test_buscas(self):
        _, dados = self.chamar('POST', '/api/buscas', {'nome': 'Cosmos', 'filtros': {
            'itens': [{'item_id': COSMOS, 'refino_min': 12}]}})
        _, lista = self.chamar('GET', '/api/buscas')
        busca = next(b for b in lista['buscas'] if b['id'] == dados['id'])
        self.assertEqual((busca['batem'], busca['avisar'], busca['ultimo_aviso']), (2, True, None))
        self.assertEqual(self.chamar('POST', '/api/buscas', {'filtros': {}})[0], 400)
        self.assertEqual(self.chamar('DELETE', f"/api/buscas/{dados['id']}")[0], 200)

    def test_config(self):
        _, cfg = self.chamar('PUT', '/api/config', {'intervalo_s': 45, 'rs_por_bi': 480})
        self.assertEqual((cfg['intervalo_s'], cfg['rs_por_bi']), (45, 480))
        self.assertEqual(self.coletor.consultas, 1)
        self.chamar('PUT', '/api/config', {'intervalo_s': 60, 'rs_por_bi': 500})

    def test_ler_agora(self):
        self.assertEqual(self.chamar('POST', '/api/ler/3152', {})[0], 200)
        self.assertEqual(self.coletor.pedidos, [3152])

    def test_testar_aviso(self):
        status, dados = self.chamar('POST', '/api/testar-aviso', {})
        self.assertEqual((status, dados), (200, {'erros': []}))
        self.assertEqual(self.avisos[-1][0], 'Teste do Mercado PW')

    def test_rota_inexistente_e_json_invalido(self):
        self.assertEqual(self.chamar('GET', '/api/nada')[0], 404)
        req = urllib.request.Request(f'http://127.0.0.1:{self.porta}/api/buscar', method='POST', data=b'{x')
        req.add_header('X-Token', self.app.token)
        with self.assertRaises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(erro.exception.code, 400)

    def test_pagina_com_token(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.porta}/', timeout=10) as resp:
            pagina = resp.read().decode()
        self.assertIn(self.app.token, pagina)
        self.assertNotIn('{{TOKEN}}', pagina)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f'http://127.0.0.1:{self.porta}/../banco.py', timeout=10)


if __name__ == '__main__':
    unittest.main()
