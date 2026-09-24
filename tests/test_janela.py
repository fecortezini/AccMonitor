import unittest

from mercado.__main__ import esperar_janela_fechar


class AppFalso:
    ultimo_sinal = None


class EdgeFalso:
    """Processo do Edge que fica vivo até a volta `fecha_em` (None = nunca)."""
    pid = 4242

    def __init__(self, fecha_em=None):
        self.fecha_em, self.voltas = fecha_em, 0

    def poll(self):
        self.voltas += 1
        return 0 if self.fecha_em is not None and self.voltas >= self.fecha_em else None


def esperar(processo, janela=None, sinais=None):
    """Roda esperar_janela_fechar sem esperar de verdade: cada volta vale 1 s. Devolve (motivo, voltas, pids).

    janela(volta, pid) diz se a janela está aberta; sinais(volta) diz se a página mandou sinal nessa volta.
    """
    app, voltas, pids = AppFalso(), 0, set()

    def dormir(_):
        nonlocal voltas
        voltas += 1
        if voltas > 100_000:
            raise AssertionError('não encerrou')
        if sinais and sinais(voltas):
            app.ultimo_sinal = voltas

    def ver_janela(pid):
        pids.add(pid)
        return janela(voltas, pid)

    motivo = esperar_janela_fechar(processo, app, janela=ver_janela if janela else None, dormir=dormir)
    return motivo, voltas, pids


class Janela(unittest.TestCase):
    def test_janela_escondida_sem_sinal_continua_aberta(self):
        # minimizada ou atrás do jogo, o Edge pode parar a página e o sinal some, mas a janela está lá
        with self.assertLogs('mercado', 'INFO') as registro:
            motivo, voltas, _ = esperar(EdgeFalso(fecha_em=3 * 3600), janela=lambda v, pid: True,
                                        sinais=lambda v: v in (5, 3000))
        self.assertEqual((motivo, voltas), ('a janela foi fechada', 3 * 3600))
        self.assertEqual([r.getMessage() for r in registro.records],
                         ['A página não manda sinal há 10 min, mas a janela continua aberta',
                          'A página voltou a mandar sinal depois de 49 min parada',
                          'A página não manda sinal há 10 min, mas a janela continua aberta'])

    def test_fechar_a_janela_encerra(self):
        motivo, voltas, pids = esperar(EdgeFalso(fecha_em=200), janela=lambda v, pid: v < 199)
        self.assertEqual((motivo, voltas, pids), ('a janela foi fechada', 200, {4242}))

    def test_edge_aberto_sem_janela(self):
        motivo, voltas, _ = esperar(EdgeFalso(), janela=lambda v, pid: v < 100)
        self.assertEqual((motivo, voltas), ('o Edge ficou aberto sem a janela do programa', 129))

    def test_janela_demorando_a_abrir(self):
        # no primeiro minuto a janela ainda pode não ter aparecido
        motivo, voltas, _ = esperar(EdgeFalso(fecha_em=500), janela=lambda v, pid: v > 45)
        self.assertEqual((motivo, voltas), ('a janela foi fechada', 500))

    def test_outro_edge_ficou_com_a_janela(self):
        # o Edge que abrimos saiu logo: a janela é de outro Edge do mesmo perfil e é achada pelo título
        motivo, voltas, pids = esperar(EdgeFalso(fecha_em=2), janela=lambda v, pid: v < 1000)
        self.assertEqual((motivo, voltas, pids), ('a janela foi fechada', 1029, {4242, None}))

    def test_sem_como_ver_as_janelas_vale_o_edge(self):
        motivo, voltas, _ = esperar(EdgeFalso(fecha_em=5000), janela=lambda v, pid: None)
        self.assertEqual((motivo, voltas), ('a janela foi fechada', 5000))

    def test_navegador_padrao_vale_o_sinal(self):
        # sem o Edge não há janela para olhar: a página manda sinal a cada 15 s até a volta 300
        motivo, voltas, pids = esperar(None, janela=lambda v, pid: True, sinais=lambda v: v % 15 == 0 and v <= 300)
        self.assertEqual((motivo, voltas, pids), ('a página parou de mandar sinal', 480, set()))
        self.assertEqual(esperar(None)[:2], ('a página não abriu', 120))


if __name__ == '__main__':
    unittest.main()
