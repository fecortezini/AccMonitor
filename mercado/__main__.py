"""Abre o Mercado PW: banco, coletor e servidor, e a janela no Edge em modo aplicativo.

    pyw -m mercado              abre normalmente (é o que o "Mercado PW.bat" faz)
    py -m mercado --sem-janela  só o servidor, mostrando o endereço (para testes)
"""
import argparse
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
from pathlib import Path

from .banco import Banco
from .coletor import Coletor, Estado
from .servidor import App, iniciar

PASTA = Path(__file__).resolve().parent.parent
ARQ_BANCO = PASTA / 'mercado.db'
ARQ_LOG = PASTA / 'mercado.log'
ARQ_INSTANCIA = PASTA / '.instancia.json'
PERFIL_JANELA = PASTA / '.janela'
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


def esperar_janela_fechar(processo, app):
    """Espera o usuário fechar a janela.

    Enquanto o processo do Edge estiver vivo, a janela está aberta (mesmo minimizada).
    Sem processo para acompanhar (navegador padrão), vale o sinal que a página manda a cada 15 s.
    """
    inicio = time.monotonic()
    while True:
        time.sleep(1)
        agora, sinal = time.monotonic(), app.ultimo_sinal
        if processo is not None:
            if processo.poll() is None:
                if sinal is not None and agora - sinal > 600:  # Edge vivo mas página morta há 10 min
                    processo.terminate()
                    return
                continue
            if agora - inicio > 15:  # a janela que abrimos foi fechada
                return
            processo = None  # saiu logo de cara: outro Edge com o mesmo perfil ficou com a janela
        if sinal is None and agora - inicio > 120:
            return
        if sinal is not None and agora - sinal > 180:
            return


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

    banco = Banco(ARQ_BANCO)
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
        esperar_janela_fechar(processo, app)
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
