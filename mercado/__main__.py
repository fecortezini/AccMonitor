"""Abre o Mercado PW: banco, coletor e servidor, e a janela no Edge em modo aplicativo.

    pyw -m mercado              abre normalmente (é o que o "Mercado PW.bat" faz)
    py -m mercado --sem-janela  só o servidor, mostrando o endereço (para testes)
"""
import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

from .banco import Banco
from .coletor import Coletor, Estado
from .servidor import App, iniciar

PASTA = Path(__file__).resolve().parent.parent
ARQ_BANCO = PASTA / 'mercado.db'
ARQ_DADOS = PASTA / 'meus-dados.json'  # tabela de valores, buscas e configurações; vai pelo git para os outros PCs
ARQ_LOG = PASTA / 'mercado.log'
ARQ_INSTANCIA = PASTA / '.instancia.json'
PERFIL_JANELA = PASTA / '.janela'
TITULO_JANELA = 'Mercado PW'  # o <title> da página, que o Edge usa como título da janela
log = logging.getLogger('mercado')


def configurar_log():
    arquivo = logging.handlers.RotatingFileHandler(ARQ_LOG, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    arquivo.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
    log.addHandler(arquivo)
    if sys.stderr is not None:  # com pythonw não há console
        log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)


def achar_edge():
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        if base and (caminho := Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe').exists():
            return str(caminho)
    return shutil.which('msedge')


def abrir_janela(url):
    """Abre a interface numa janela própria do Edge (sem abas nem barra de endereço)."""
    edge = achar_edge()
    if not edge:
        log.warning('Edge não encontrado; abrindo no navegador padrão')
        webbrowser.open(url)
        return None
    return subprocess.Popen([
        edge, f'--app={url}', f'--user-data-dir={PERFIL_JANELA}', '--no-first-run', '--no-default-browser-check',
        '--window-size=1440,900', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    ])


def instancia_aberta():
    """Dados da instância que já está rodando, se houver uma respondendo."""
    try:
        dados = json.loads(ARQ_INSTANCIA.read_text(encoding='utf-8'))
        req = urllib.request.Request(f"http://127.0.0.1:{dados['porta']}/api/estado", headers={'X-Token': dados['token']})
        urllib.request.urlopen(req, timeout=3).close()
        return dados
    except Exception:
        return None


if sys.platform == 'win32':
    _user32 = ctypes.WinDLL('user32')
    _CADA_JANELA = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_CADA_JANELA, wintypes.LPARAM]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def janela_aberta(pid=None):
    """True se a janela do programa está aberta, mesmo minimizada ou atrás de outra; None se não der para saber.

    Com o pid do Edge que abrimos, vale qualquer janela dele: a do programa ou uma do "Abrir no site".
    Sem o pid, vale a janela com o título da página (esperar_janela_fechar também olha por ela quando o
    nosso Edge não tem janela).
    """
    if sys.platform != 'win32':
        return None
    achou = False

    def cada(hwnd, _):
        nonlocal achou
        titulo = ctypes.create_unicode_buffer(256)
        if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextW(hwnd, titulo, 256):
            if pid is None:
                achou = titulo.value == TITULO_JANELA
            else:
                dono = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
                achou = dono.value == pid
        return not achou  # para na primeira que achar

    try:
        _user32.EnumWindows(_CADA_JANELA(cada), 0)
    except OSError:
        return None
    return achou


def esperar_janela_fechar(processo, app, janela=janela_aberta, dormir=time.sleep):
    """Espera o usuário fechar a janela e devolve o motivo, que vai para o log.

    Com o Edge, o programa segue enquanto a janela existir, mesmo minimizada ou atrás do jogo. O sinal que a
    página manda a cada 15 s não serve para isso: o Edge para as páginas escondidas, e o sinal some. Ele só
    vale no navegador padrão, onde não há janela para olhar. Os tempos são contados em voltas de 1 s, e não
    pelo relógio, para uma suspensão do Windows não contar como tempo sem janela ou sem sinal.
    """
    com_edge = processo is not None
    voltas = sem_janela = sem_sinal = 0
    sinal = app.ultimo_sinal
    while True:
        dormir(1)
        voltas += 1
        if app.ultimo_sinal != sinal:
            if sem_sinal >= 600:
                log.info('A página voltou a mandar sinal depois de %d min parada', sem_sinal // 60)
            sinal, sem_sinal = app.ultimo_sinal, 0
        else:
            sem_sinal += 1
        # A janela pode ser de outro Edge: a do segundo clique no .bat, aberta enquanto o nosso Edge fechava a
        # primeira, nasce num processo novo. Por isso, antes de encerrar, vale também a janela com o título.
        if processo is not None and processo.poll() is not None:
            if voltas > 15 and janela(None) is not True:
                return 'a janela foi fechada'
            processo = None  # saiu logo de cara, ou a janela é de outro Edge: daqui em diante, a janela com o título
        aberta = janela(processo.pid if processo else None) if com_edge else None
        if aberta is False and processo is not None:
            aberta = janela(None) is True
        if aberta is not None:
            if aberta and sem_sinal == 600:  # só para o log: mostra quando o Edge para a página escondida
                log.info('A página não manda sinal há 10 min, mas a janela continua aberta')
            sem_janela = 0 if aberta else sem_janela + 1
            if sem_janela >= 30 and voltas > 60:
                return 'o Edge ficou aberto sem a janela do programa' if processo else 'a janela foi fechada'
            continue
        if processo is not None:
            continue  # sem como ver as janelas: vale o processo do Edge, que está vivo
        if sem_sinal >= (180 if sinal is not None else 120):
            return 'a página parou de mandar sinal' if sinal is not None else 'a página não abriu'


def main():
    ap = argparse.ArgumentParser(prog='mercado', description='Mercado PW: acompanha o Marketplace The Classic (PW 1.8.7).')
    ap.add_argument('--sem-janela', action='store_true', help='só o servidor, sem abrir a janela')
    ap.add_argument('--porta', type=int, default=0, help='porta do servidor local (padrão: uma livre)')
    args = ap.parse_args()
    configurar_log()

    aberta = instancia_aberta()
    if aberta:
        log.info('O programa já está aberto; abrindo outra janela')
        abrir_janela(f"http://127.0.0.1:{aberta['porta']}/")
        return

    banco = Banco(ARQ_BANCO, ARQ_DADOS)
    if limpas := banco.limpar_antigos():
        log.info('Itens de %d anúncios antigos apagados', limpas)
    estado = Estado()
    coletor = Coletor(banco, estado)
    app = App(banco, coletor, estado)
    servidor, porta = iniciar(app, args.porta)
    ARQ_INSTANCIA.write_text(json.dumps({'porta': porta, 'token': app.token, 'pid': os.getpid()}), encoding='utf-8')
    coletor.start()
    url = f'http://127.0.0.1:{porta}/'
    log.info('Mercado PW aberto em %s', url)
    processo = None
    try:
        if args.sem_janela:
            while True:
                time.sleep(3600)
        processo = abrir_janela(url)
        log.info('Encerrando porque %s', esperar_janela_fechar(processo, app))
    except KeyboardInterrupt:
        pass
    finally:
        coletor.parar()
        servidor.shutdown()
        if processo is not None and processo.poll() is None:
            processo.terminate()
        ARQ_INSTANCIA.unlink(missing_ok=True)
        log.info('Mercado PW encerrado')


if __name__ == '__main__':
    main()
