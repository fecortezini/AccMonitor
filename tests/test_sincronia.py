import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mercado import sincronia
from mercado.banco import Banco, dados_normalizados

COSMOS = 72573


def dados(valores=(), buscas=(), grupos=(), **cfg):
    return dados_normalizados({'configuracoes': cfg, 'valores': list(valores), 'buscas': list(buscas),
                               'grupos': list(grupos)})


def valor(vid, nome, kk, quando='2026-09-01T10:00:00'):
    return {'id': vid, 'item_id': None, 'nome': nome, 'refino_min': 0, 'valor_kk': kk,
            'criado_em': quando, 'atualizado_em': quando}


class Juntar(unittest.TestCase):
    """Quando os dois PCs mudaram desde a última sincronia, os dados se juntam item a item."""

    def nomes(self, juntos):
        return {v['id']: (v['nome'], v['valor_kk']) for v in juntos['valores']}

    def test_so_um_lado_mudou(self):
        base = dados([valor(1, 'Cosmos', 3000), valor(2, 'Pedra', 20)])
        local = dados([valor(1, 'Cosmos', 3500), valor(2, 'Pedra', 20), valor(3, 'Nova daqui', 5)])
        remoto = dados([valor(1, 'Cosmos', 3000)])  # o outro PC apagou a Pedra
        self.assertEqual(self.nomes(sincronia.juntar(base, local, remoto)),
                         {1: ('Cosmos', 3500.0), 3: ('Nova daqui', 5.0)})

    def test_os_dois_criaram_com_o_mesmo_id(self):
        juntos = sincronia.juntar(dados(), dados([valor(1, 'Daqui', 1)]), dados([valor(1, 'De lá', 2)]))
        self.assertEqual(self.nomes(juntos), {1: ('De lá', 2.0), 2: ('Daqui', 1.0)})

    def test_os_dois_mudaram_fica_o_mais_recente(self):
        base = dados([valor(1, 'Cosmos', 3000)])
        local = dados([valor(1, 'Cosmos', 3500, '2026-09-02T10:00:00')])
        remoto = dados([valor(1, 'Cosmos', 4000, '2026-09-03T10:00:00')])
        self.assertEqual(self.nomes(sincronia.juntar(base, local, remoto)), {1: ('Cosmos', 4000.0)})
        self.assertEqual(self.nomes(sincronia.juntar(base, remoto, local)), {1: ('Cosmos', 4000.0)})

    def test_um_apagou_e_o_outro_mudou(self):
        base = dados([valor(1, 'Cosmos', 3000)])
        self.assertEqual(self.nomes(sincronia.juntar(base, dados(), dados([valor(1, 'Cosmos', 3500)]))),
                         {1: ('Cosmos', 3500.0)})

    def test_configuracoes(self):
        base = dados(rs_por_bi=500, pausa_s=2)
        juntos = sincronia.juntar(base, dados(rs_por_bi=500, pausa_s=1), dados(rs_por_bi=480, pausa_s=3))
        self.assertEqual((juntos['configuracoes']['rs_por_bi'], juntos['configuracoes']['pausa_s']), (480.0, 1))

    def test_grupo_com_o_mesmo_id_nos_dois(self):
        grupo = lambda nome: {'id': 1, 'nome': nome, 'itens': [], 'criado_em': '', 'atualizado_em': ''}
        busca = lambda bid, nome: {'id': bid, 'nome': nome, 'filtros': {'algum': [{'grupo_id': 1, 'nome': 'x'}]}}
        local = dados(buscas=[busca(1, 'Daqui')], grupos=[grupo('UP4')])
        remoto = dados(buscas=[busca(1, 'De lá')], grupos=[grupo('UP3')])
        juntos = sincronia.juntar(dados(), local, remoto)
        self.assertEqual([(g['id'], g['nome']) for g in juntos['grupos']], [(1, 'UP3'), (2, 'UP4')])
        # a busca deste PC segue o grupo dela, que mudou de id; a do outro PC continua no 1
        self.assertEqual([(b['nome'], b['filtros']['algum'][0]['grupo_id']) for b in juntos['buscas']],
                         [('De lá', 1), ('Daqui', 2)])

    def test_valor_de_grupo_segue_o_grupo_que_mudou_de_id(self):
        grupo = lambda nome: {'id': 1, 'nome': nome, 'itens': [], 'criado_em': '', 'atualizado_em': ''}
        local = dados([{**valor(1, 'UP4', 100), 'grupo_id': 1}], grupos=[grupo('UP4')])
        remoto = dados([{**valor(1, 'UP3', 50), 'grupo_id': 1}], grupos=[grupo('UP3')])
        juntos = sincronia.juntar(dados(), local, remoto)
        self.assertEqual([(v['nome'], v['grupo_id']) for v in juntos['valores']], [('UP3', 1), ('UP4', 2)])


def git(pasta, *args):
    r = subprocess.run(['git', *args], cwd=pasta, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise AssertionError(f'git {" ".join(args)}: {r.stderr}')
    return r.stdout


class Sincronizar(unittest.TestCase):
    """Dois PCs com clones do mesmo repositório (um "GitHub" numa pasta) e o botão Sincronizar."""

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.remoto = self.pasta / 'github.git'
        git(self.pasta, 'init', '--bare', '-b', 'main', str(self.remoto))
        self.pa, self.pb = self.pasta / 'pc-a', self.pasta / 'pc-b'
        git(self.pasta, 'clone', '-q', str(self.remoto), str(self.pa))
        self.identidade(self.pa)
        (self.pa / '.gitignore').write_text('mercado.db*\n', encoding='utf-8')
        (self.pa / 'programa.txt').write_text('versão 1\n', encoding='utf-8')
        self.bancos = []
        self.a = self.abrir(self.pa)  # cria o meus-dados.json
        git(self.pa, 'add', '-A')
        git(self.pa, 'commit', '-qm', 'início')
        git(self.pa, 'push', '-q', '-u', 'origin', 'main')
        git(self.pasta, 'clone', '-q', str(self.remoto), str(self.pb))
        self.identidade(self.pb)
        self.b = self.abrir(self.pb)

    def tearDown(self):
        for banco in self.bancos:
            banco.fechar()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def identidade(self, pasta):
        git(pasta, 'config', 'user.name', 'Teste')
        git(pasta, 'config', 'user.email', 'teste@exemplo.com')

    def abrir(self, pasta):
        banco = Banco(pasta / 'mercado.db', pasta / 'meus-dados.json')
        self.bancos.append(banco)
        return banco

    def test_mandar_e_trazer(self):
        self.a.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3500})
        self.assertTrue(self.a.dados_a_enviar())  # o botão ganha o ponto
        self.assertEqual(sincronia.sincronizar(self.pa, self.a), {'trouxe': [], 'mandou': True, 'codigo_novo': False})
        self.assertFalse(self.a.dados_a_enviar())
        self.assertIn('Meus dados', git(self.pa, 'log', '-1', '--format=%s'))
        self.assertEqual(sincronia.sincronizar(self.pb, self.b), {'trouxe': ['1 valor'], 'mandou': False, 'codigo_novo': False})
        self.assertEqual([v['nome'] for v in self.b.valores()], ['Cosmos'])
        self.assertEqual(sincronia.sincronizar(self.pb, self.b), {'trouxe': [], 'mandou': False, 'codigo_novo': False})

    def test_os_dois_pcs_mudaram(self):
        self.b.salvar_grupo({'nome': 'Armas UP4', 'itens': [{'item_id': COSMOS, 'nome': 'Cosmos'}]})
        sincronia.sincronizar(self.pb, self.b)
        self.a.salvar_config({'rs_por_bi': 480})  # o PC A mudou outra coisa antes de sincronizar
        r = sincronia.sincronizar(self.pa, self.a)
        self.assertEqual((r['trouxe'], r['mandou']), (['1 grupo'], True))
        self.assertEqual(([g['nome'] for g in self.a.grupos()], self.a.config()['rs_por_bi']), (['Armas UP4'], 480))
        self.assertEqual(sincronia.sincronizar(self.pb, self.b)['trouxe'], ['configurações'])
        self.assertEqual(self.b.config()['rs_por_bi'], 480)

    def test_versao_nova_do_programa(self):
        (self.pa / 'programa.txt').write_text('versão 2\n', encoding='utf-8')
        git(self.pa, 'commit', '-qam', 'versão nova')
        git(self.pa, 'push', '-q')
        self.assertTrue(sincronia.sincronizar(self.pb, self.b)['codigo_novo'])
        self.assertEqual((self.pb / 'programa.txt').read_text(encoding='utf-8'), 'versão 2\n')

    def test_nao_mexe_se_o_codigo_foi_mudado(self):
        (self.pb / 'programa.txt').write_text('mexido\n', encoding='utf-8')
        with self.assertRaisesRegex(sincronia.ErroSincronia, 'programa.txt'):
            sincronia.sincronizar(self.pb, self.b)

    def test_sem_acesso_ao_github(self):
        self.a.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3500})
        cabeca = git(self.pa, 'rev-parse', 'HEAD')
        self.remoto.rename(self.pasta / 'fora.git')
        with self.assertRaisesRegex(sincronia.ErroSincronia, 'GitHub'), self.assertLogs('mercado', 'WARNING'):
            sincronia.sincronizar(self.pa, self.a)
        self.assertEqual(git(self.pa, 'rev-parse', 'HEAD'), cabeca)
        self.assertTrue(self.a.dados_a_enviar())

    def test_github_recusa_o_envio(self):
        (self.remoto / 'hooks' / 'pre-receive').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8', newline='\n')
        self.a.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'valor_kk': 3500})
        cabeca = git(self.pa, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(sincronia.ErroSincronia, 'enviar'):
            sincronia.sincronizar(self.pa, self.a)
        self.assertEqual(git(self.pa, 'rev-parse', 'HEAD'), cabeca)  # o commit foi desfeito
        self.assertIn('meus-dados.json', git(self.pa, 'status', '--porcelain'))  # e o dado continua aqui


if __name__ == '__main__':
    unittest.main()
