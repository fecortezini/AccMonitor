import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from mercado import site
from mercado.banco import Banco
from mercado.coletor import ALTA, Coletor, Estado
from mercado.servidor import App
from tests import paginas
from tests.test_coletor import SiteFalso

COSMOS, DEMONIO = site.COSMOS_ID, 38154
SO_NESTE_PC = ('telegram_token', 'telegram_chat', 'discord_webhook',
               'largura_filtros', 'largura_detalhes', 'detalhes_recolhidos')


class ColetorFalso:
    def __init__(self):
        self.repriorizou = 0

    def repriorizar(self):
        self.repriorizou += 1


class MeusDados(unittest.TestCase):
    """meus-dados.json: a tabela de valores, as buscas e as configurações, que vão pelo git para os outros PCs."""

    @classmethod
    def setUpClass(cls):
        cls.lista = site.ler_lista(paginas.lista())
        cls.itens = {rid: site.ler_conta(paginas.conta(rid)) for rid in (45520, 231216)}

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.arquivo = self.pasta / 'meus-dados.json'
        self.anterior = self.pasta / 'meus-dados.anterior.json'
        self.bancos = []
        self.relogio = time.time_ns()

    def tearDown(self):
        for banco in self.bancos:
            banco.fechar()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def abrir(self, pc='este', compartilhado=True):
        """Abre o programa num PC (cada um com o seu banco), com a lista e as duas contas salvas já lidas."""
        banco = Banco(self.pasta / f'{pc}.db', self.arquivo if compartilhado else None)
        self.bancos.append(banco)
        if not banco.contagem()['ativas']:
            banco.atualizar_lista(self.lista)
            for rid, itens in self.itens.items():
                banco.gravar_itens(rid, itens, self.lista[rid].preco)
        return banco

    def ler(self):
        return json.loads(self.arquivo.read_text(encoding='utf-8'))

    def escrever(self, dados):
        """Muda o arquivo por fora, como um git pull que trouxe as mudanças de outro PC."""
        texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, indent=1)
        self.arquivo.write_text(texto, encoding='utf-8')
        self.relogio += 10**9  # o relógio do disco pode não ter andado desde a última gravação
        os.utime(self.arquivo, ns=(self.relogio, self.relogio))

    @staticmethod
    def valores(banco):
        return [(v['nome'], v['refino_min'], v['valor_kk']) for v in banco.valores()]

    # -------------------------------------------------------------- neste PC

    def test_primeira_vez_o_banco_vira_o_arquivo(self):
        antigo = self.abrir(compartilhado=False)  # a versão anterior do programa, sem o arquivo
        antigo.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3500})
        antigo.salvar_busca({'nome': 'Cosmos barato', 'filtros': {'preco_max': 2500}, 'avisar': False})
        antigo.salvar_config({'rs_por_bi': 480, 'intervalo_s': 30, 'telegram_token': 'segredo', 'largura_filtros': 20})
        antigo.fechar()
        banco = self.abrir()
        dados = self.ler()
        self.assertEqual(dados['formato'], 1)
        self.assertEqual([(v['nome'], v['item_id'], v['refino_min'], v['valor_kk']) for v in dados['valores']],
                         [('Cosmos', COSMOS, 10, 3500.0)])
        self.assertEqual([(b['nome'], b['avisar'], b['filtros']) for b in dados['buscas']],
                         [('Cosmos barato', False, {'preco_max': 2500})])
        self.assertEqual((dados['configuracoes']['rs_por_bi'], dados['configuracoes']['intervalo_s']), (480.0, 30))
        for chave in SO_NESTE_PC:  # os tokens e o tamanho dos painéis ficam só no banco deste PC
            self.assertNotIn(chave, dados['configuracoes'])
        self.assertNotIn('segredo', self.arquivo.read_text(encoding='utf-8'))
        self.assertEqual(banco.config()['telegram_token'], 'segredo')
        self.assertFalse(self.anterior.exists())

    def test_arquivo_gerado_deste_banco(self):
        # o arquivo foi gerado de uma cópia deste banco e chegou junto com a versão nova do programa
        antigo = self.abrir(compartilhado=False)
        antigo.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        antigo.fechar()
        shutil.copy(self.pasta / 'este.db', self.pasta / 'copia.db')
        self.abrir('copia')
        gravado = self.arquivo.stat().st_mtime_ns
        banco = self.abrir()
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 6000.0)])
        self.assertIsNotNone(banco.meta('dados_hash'))
        self.assertEqual(self.arquivo.stat().st_mtime_ns, gravado)
        self.assertFalse(self.anterior.exists())

    def test_mudanca_antes_de_reabrir_com_a_versao_nova(self):
        # o arquivo foi gerado com o programa antigo aberto, e a tabela mudou antes de ele ser reaberto
        self.abrir().fechar()
        antigo = Banco(self.pasta / 'este.db')
        self.bancos.append(antigo)
        antigo.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        antigo.fechar()
        banco = self.abrir()
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 6000.0)])
        self.assertEqual([v['nome'] for v in self.ler()['valores']], ['Cosmos'])  # a mudança foi para o arquivo
        self.assertFalse(self.anterior.exists())

    def test_mudancas_vao_para_o_arquivo(self):
        banco = self.abrir()
        vid = banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3000})
        banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 10, 'valor_kk': 3500}, vid)
        bid = banco.salvar_busca({'nome': 'Cosmos', 'filtros': {'itens': [{'item_id': COSMOS}]}})
        banco.salvar_config({'rs_por_bi': 520})
        dados = self.ler()
        self.assertEqual([(v['id'], v['valor_kk']) for v in dados['valores']], [(vid, 3500.0)])
        self.assertEqual([(b['id'], b['filtros']) for b in dados['buscas']], [(bid, {'itens': [{'item_id': COSMOS}]})])
        self.assertEqual(dados['configuracoes']['rs_por_bi'], 520.0)
        banco.apagar_valor(vid)
        banco.apagar_busca(bid)
        dados = self.ler()
        self.assertEqual((dados['valores'], dados['buscas']), ([], []))

    def test_o_que_fica_so_neste_pc_nao_mexe_no_arquivo(self):
        banco = self.abrir()
        gravado = self.arquivo.stat().st_mtime_ns
        banco.salvar_config({'largura_filtros': 30, 'detalhes_recolhidos': True, 'telegram_token': 'x',
                             'discord_webhook': 'y'})
        banco.salvar_config({'rs_por_bi': 500})  # igual ao que já estava: o arquivo não é regravado
        self.assertFalse(banco.sincronizar())
        self.assertEqual(self.arquivo.stat().st_mtime_ns, gravado)

    def test_valor_pelo_nome_ganha_o_item_no_arquivo(self):
        banco = self.abrir()
        lista = dict(self.lista)
        lista[1] = site.Anuncio(id=1, preco=50, nivel=105, ocupacao=6, nome='Futura', classe='Arqueiro', ceu='')
        banco.atualizar_lista(lista)
        banco.salvar_valor({'nome': 'Item Futuro', 'valor_kk': 2})
        self.assertIsNone(self.ler()['valores'][0]['item_id'])
        banco.gravar_itens(1, [site.Item(secao='inventario', item_id=4242, nome='Item Futuro', qtd=3)], 50)
        self.assertEqual(self.ler()['valores'][0]['item_id'], 4242)
        self.assertFalse(banco.sincronizar())

    # -------------------------------------------------------------- em outro PC

    def test_outro_pc_recebe_tudo(self):
        este = self.abrir()
        este.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        este.salvar_valor({'nome': 'Pedra do Demônio', 'valor_kk': 20})  # o item_id vem das contas lidas
        filtros = {'itens': [{'item_id': COSMOS, 'refino_min': 12}], 'preco_max': 20000}
        bid = este.salvar_busca({'nome': 'Cosmos +12', 'filtros': filtros, 'lucro_min_pct': 10})
        este.salvar_config({'rs_por_bi': 480, 'pausa_s': 1, 'aviso_bipes': False, 'telegram_token': 'segredo'})
        outro = self.abrir('outro')  # banco novo, com o arquivo que veio pelo git
        self.assertEqual(self.valores(outro), self.valores(este))
        self.assertEqual([(b['id'], b['nome'], b['filtros'], b['avisar'], b['lucro_min_pct']) for b in outro.buscas()],
                         [(bid, 'Cosmos +12', filtros, True, 10.0)])
        cfg = outro.config()
        self.assertEqual((cfg['rs_por_bi'], cfg['pausa_s'], cfg['aviso_bipes'], cfg['telegram_token']),
                         (480, 1, False, ''))
        self.assertEqual(outro.anuncio(231216)['valor_kk'], 6000 + 24 * 20)  # a conta já vale pela tabela
        self.assertFalse(self.anterior.exists())  # o outro PC não tinha nada

    def test_grupos_vao_para_o_outro_pc(self):
        este = self.abrir()
        gid = este.salvar_grupo({'nome': 'Armas UP4', 'itens': [{'item_id': COSMOS, 'nome': 'Cosmos'}]})
        este.salvar_busca({'nome': 'UP4', 'filtros': {'algum': [{'grupo_id': gid, 'nome': 'Armas UP4'}]}})
        self.assertEqual([(g['id'], g['nome'], g['itens']) for g in self.ler()['grupos']],
                         [(gid, 'Armas UP4', [{'item_id': COSMOS, 'nome': 'Cosmos'}])])
        outro = self.abrir('outro')
        self.assertEqual([(g['id'], g['nome']) for g in outro.grupos()], [(gid, 'Armas UP4')])
        # a busca salva continua apontando para o grupo certo
        self.assertEqual([c['id'] for c in outro.buscar(outro.buscas()[0]['filtros'])['contas']], [231216])
        este.apagar_grupo(gid)
        self.assertEqual(self.ler()['grupos'], [])

    def test_valor_de_grupo_vai_para_o_outro_pc(self):
        este = self.abrir()
        este.salvar_valor({'nome': 'Pedra do Demônio', 'item_id': 38154, 'valor_kk': 90})
        self.assertEqual(self.ler()['formato'], 1)  # sem valor de grupo, o arquivo continua o de antes
        self.assertNotIn('grupo_id', self.ler()['valores'][0])
        gid = este.salvar_grupo({'nome': 'Livros', 'itens': [{'item_id': COSMOS, 'nome': 'Cosmos'}]})
        este.salvar_valor({'grupo_id': gid, 'refino_min': 12, 'valor_kk': 9000})
        arquivo = self.ler()
        self.assertEqual(arquivo['formato'], 2)  # o programa antigo recusa, em vez de perder o valor do grupo
        self.assertEqual([(v['nome'], v.get('grupo_id')) for v in arquivo['valores']],
                         [('Pedra do Demônio', None), ('Livros', gid)])
        outro = self.abrir('outro')
        self.assertEqual([(v['nome'], v['grupo_id'], v['valor_kk']) for v in outro.valores() if v['grupo_id']],
                         [('Livros', gid, 9000.0)])
        self.assertIn(('Livros', 9000.0), [(d['nome'], d['kk']) for d in outro.conta(231216)['detalhes']])  # o Cosmos +12

    def test_pc_que_ja_tinha_dados_fica_com_os_do_arquivo(self):
        este = self.abrir()
        este.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        antigo = self.abrir('outro', compartilhado=False)  # o outro PC já usava o programa, com a própria tabela
        antigo.salvar_valor({'nome': 'Pedra do Demônio', 'valor_kk': 99})
        antigo.salvar_busca({'nome': 'Só do outro PC', 'filtros': {}})
        antigo.salvar_config({'telegram_token': 'do outro PC'})
        antigo.fechar()
        with self.assertLogs('mercado', 'WARNING') as registro:
            outro = self.abrir('outro')
        self.assertIn('meus-dados.anterior.json', registro.output[0])
        self.assertEqual(self.valores(outro), [('Cosmos', 12, 6000.0)])
        self.assertEqual(outro.buscas(), [])
        self.assertEqual(outro.config()['telegram_token'], 'do outro PC')
        self.assertEqual([v['nome'] for v in self.ler()['valores']], ['Cosmos'])
        anterior = json.loads(self.anterior.read_text(encoding='utf-8'))  # nada se perde
        self.assertEqual([v['nome'] for v in anterior['valores']], ['Pedra do Demônio'])
        self.assertEqual([b['nome'] for b in anterior['buscas']], ['Só do outro PC'])

    def test_git_pull_com_o_programa_aberto(self):
        banco = self.abrir()
        banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        self.assertFalse(banco.sincronizar())
        dados = self.ler()
        dados['valores'][0]['valor_kk'] = 7000
        dados['valores'].append({'id': 2, 'item_id': DEMONIO, 'nome': 'Pedra do Demônio', 'valor_kk': 20})
        dados['configuracoes']['rs_por_bi'] = 450
        self.escrever(dados)
        self.assertTrue(banco.sincronizar())
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 7000.0), ('Pedra do Demônio', 0, 20.0)])
        self.assertEqual(banco.config()['rs_por_bi'], 450)
        self.assertEqual(banco.anuncio(231216)['valor_kk'], 7000 + 24 * 20)  # recalculada
        self.assertFalse(banco.sincronizar())
        self.assertFalse(self.anterior.exists())
        with self.assertNoLogs('mercado', 'INFO'):  # reabrir não traz nada: o banco ficou igual ao arquivo
            self.bancos.append(Banco(self.pasta / 'este.db', self.arquivo))
        banco.salvar_valor({'nome': 'Pedra do Demônio', 'item_id': DEMONIO, 'valor_kk': 25}, 2)
        self.assertEqual([v['valor_kk'] for v in self.ler()['valores']], [7000.0, 25.0])

    def test_mudanca_no_programa_parte_do_arquivo_novo(self):
        # o arquivo mudou e o programa ainda não percebeu: a mudança seguinte não grava por cima
        banco = self.abrir()
        banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        dados = self.ler()
        dados['valores'].append({'id': 2, 'item_id': DEMONIO, 'nome': 'Pedra do Demônio', 'valor_kk': 20})
        self.escrever(dados)
        banco.salvar_config({'rs_por_bi': 450})
        self.assertEqual([v['nome'] for v in self.ler()['valores']], ['Cosmos', 'Pedra do Demônio'])
        self.assertEqual(self.ler()['configuracoes']['rs_por_bi'], 450.0)

    def test_juntar_mudancas_de_dois_pcs(self):
        # depois de um merge do git, dois valores podem ficar com o mesmo id: nenhum se perde
        banco = self.abrir()
        dados = self.ler()
        dados['valores'] = [{'id': 1, 'item_id': COSMOS, 'nome': 'Cosmos', 'refino_min': 12, 'valor_kk': 6000},
                            {'id': 1, 'item_id': DEMONIO, 'nome': 'Pedra do Demônio', 'valor_kk': 20}]
        self.escrever(dados)
        self.assertTrue(banco.sincronizar())
        self.assertEqual(sorted(v['id'] for v in banco.valores()), [1, 2])
        self.assertEqual(banco.anuncio(231216)['valor_kk'], 6000 + 24 * 20)

    def test_historico_de_avisos_fica_em_cada_pc(self):
        banco = self.abrir()
        fica = banco.salvar_busca({'nome': 'Fica', 'filtros': {}})
        sai = banco.salvar_busca({'nome': 'Sai', 'filtros': {}})
        banco.registrar_aviso(fica, 45520, 2400, None, 'anúncio novo')
        banco.registrar_aviso(sai, 231216, 15000, None, 'anúncio novo')
        dados = self.ler()
        self.assertNotIn('avisos', dados)
        # no outro PC, "Sai" foi apagada e uma busca nova ficou com o id dela
        dados['buscas'] = [b for b in dados['buscas'] if b['id'] == fica] + [
            {'id': sai, 'nome': 'Nova', 'filtros': {}, 'criado_em': '2030-01-01T00:00:00'}]
        self.escrever(dados)
        self.assertTrue(banco.sincronizar())
        self.assertEqual([(a['busca'], a['anuncio_id']) for a in banco.avisos()], [('Fica', 45520)])

    # -------------------------------------------------------------- arquivo com problema

    def test_conflito_do_git(self):
        banco = self.abrir()
        banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        texto = self.arquivo.read_text(encoding='utf-8')
        linha = next(l for l in texto.splitlines() if '"Cosmos"' in l)
        conflito = texto.replace(linha, f'<<<<<<< HEAD\n{linha}\n=======\n{linha.replace("6000.0", "6500.0")}\n'
                                        '>>>>>>> origin/main')
        self.escrever(conflito)
        with self.assertLogs('mercado', 'WARNING'):
            self.assertFalse(banco.sincronizar())
        self.assertIn('conflito do git', banco.erro_dados)
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 6000.0)])  # o banco segue com o que tinha
        with self.assertRaises(ValueError):  # e não aceita mudanças, para não passar por cima do conflito
            banco.salvar_valor({'nome': 'Pedra do Demônio', 'valor_kk': 20})
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 6000.0)])
        self.assertEqual(self.arquivo.read_text(encoding='utf-8'), conflito)
        self.escrever(texto.replace('6000.0', '6500.0'))  # conflito resolvido
        self.assertTrue(banco.sincronizar())
        self.assertIsNone(banco.erro_dados)
        self.assertEqual(self.valores(banco), [('Cosmos', 12, 6500.0)])

    def test_apagar_o_arquivo_grava_de_novo_os_dados_deste_pc(self):
        banco = self.abrir()
        banco.salvar_valor({'nome': 'Cosmos', 'item_id': COSMOS, 'refino_min': 12, 'valor_kk': 6000})
        self.escrever('{ quebrado')
        with self.assertLogs('mercado', 'WARNING'):
            banco.sincronizar()
        self.assertIn('um erro', banco.erro_dados)
        self.arquivo.unlink()
        self.assertFalse(banco.sincronizar())
        self.assertIsNone(banco.erro_dados)
        self.assertEqual([v['valor_kk'] for v in self.ler()['valores']], [6000.0])

    def test_arquivo_de_versao_mais_nova(self):
        banco = self.abrir()
        self.escrever({**self.ler(), 'formato': 3})
        with self.assertLogs('mercado', 'WARNING'):
            self.assertFalse(banco.sincronizar())
        self.assertIn('versão mais nova', banco.erro_dados)

    # -------------------------------------------------------------- janela e coletor

    def test_janela_aberta_ve_a_mudanca(self):
        banco = self.abrir()
        coletor = ColetorFalso()
        app = App(banco, coletor, Estado())
        versao = app.estado_api({}, None)['versao']
        dados = self.ler()
        dados['configuracoes']['rs_por_bi'] = 450
        self.escrever(dados)
        estado = app.estado_api({}, None)
        self.assertGreater(estado['versao'], versao)  # a interface recarrega a aba aberta
        self.assertEqual((estado['rs_por_bi'], coletor.repriorizou), (450, 1))
        self.escrever('{ quebrado')
        with self.assertLogs('mercado', 'WARNING'):
            self.assertIn('meus-dados.json', app.estado_api({}, None)['erro'])  # aparece na faixa do topo

    def test_coletor_com_o_arquivo_com_erro(self):
        banco = self.abrir()
        banco.salvar_config({'leituras_simultaneas': 2})
        self.escrever('{ quebrado')
        falso = SiteFalso()
        falso.recusar = {'conta/45520'}
        coletor = Coletor(banco, Estado(), site=falso, notificar=lambda *args: None)
        coletor.fila.colocar(45520, ALTA)
        coletor.fila.colocar(231216, ALTA)
        with self.assertLogs('mercado', 'WARNING'):
            coletor.ler_proxima()  # não quebra: a configuração fica como está e a conta volta para a fila
        self.assertIn(45520, coletor.fila)


if __name__ == '__main__':
    unittest.main()
