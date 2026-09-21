"""Formas de avisar: notificação do Windows, bipes, navegador, Telegram e Discord."""
import base64
import json
import logging
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from xml.sax.saxutils import escape

from .site import USER_AGENT

log = logging.getLogger('mercado')

# Identificador de aplicativo do PowerShell: permite mostrar notificações sem instalar nada
_APP_ID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'


def reais(v, sinal=False):
    """1234.5 -> 'R$ 1.235' (com '+' opcional para lucro)."""
    if v is None:
        return '—'
    texto = f'{abs(v):,.0f}'.replace(',', '.') if abs(v) >= 100 else f'{abs(v):,.2f}'.replace('.', ',')
    prefixo = ('+' if v >= 0 else '−') if sinal else ('−' if v < 0 else '')
    return f'{prefixo}R$ {texto}'


def tcc(v):
    return f'{v:,}'.replace(',', '.') + ' TCC'


def windows(titulo, linha1, linha2, url):
    """Notificação que fica na tela até ser fechada; clicar abre o anúncio no site."""
    def x(s):
        return escape(s, {'"': '&quot;'})
    xml = (f'<toast activationType="protocol" launch="{x(url)}" scenario="reminder">'
           f'<visual><binding template="ToastGeneric"><text>{x(titulo)}</text>'
           f'<text>{x(linha1)}</text><text>{x(linha2)}</text></binding></visual>'
           f'<actions><action content="Abrir anúncio" activationType="protocol" arguments="{x(url)}"/>'
           '<action content="Fechar" activationType="system" arguments="dismiss"/></actions></toast>')
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$xml.LoadXml('{xml.replace(chr(39), chr(39) * 2)}')\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_APP_ID}').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($xml))\n")
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                        base64.b64encode(script.encode('utf-16-le')).decode()],
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace').strip()[:300])


def bipes():
    """Tocam mesmo com o "Não perturbe" do Windows ligado (ex.: jogando em tela cheia)."""
    import winsound
    for _ in range(3):
        winsound.Beep(1200, 250)
        time.sleep(0.1)


def telegram(token, chat_id, texto):
    dados = urllib.parse.urlencode({'chat_id': chat_id, 'text': texto, 'disable_web_page_preview': 'true'}).encode()
    urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', data=dados, timeout=20).close()


def discord(webhook, texto):
    req = urllib.request.Request(webhook, data=json.dumps({'content': texto}).encode(),
                                 headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    urllib.request.urlopen(req, timeout=20).close()


def notificar(cfg, titulo, linha1, linha2, texto, url, esperar=False):
    """Avisa por todos os canais ligados nas configurações.

    Roda em segundo plano para não travar o coletor; com esperar=True devolve os erros.
    """
    canais = []
    if cfg.get('aviso_windows'):
        canais.append(('Windows', lambda: windows(titulo, linha1, linha2, url)))
    if cfg.get('aviso_bipes'):
        canais.append(('bipes', bipes))
    if cfg.get('telegram_token') and cfg.get('telegram_chat'):
        canais.append(('Telegram', lambda: telegram(cfg['telegram_token'], str(cfg['telegram_chat']), texto)))
    if cfg.get('discord_webhook'):
        canais.append(('Discord', lambda: discord(cfg['discord_webhook'], texto)))
    if cfg.get('aviso_navegador'):
        canais.append(('navegador', lambda: webbrowser.open(url)))

    erros = []

    def enviar(nome, fn):
        try:
            fn()
        except Exception as e:  # um canal com problema não impede os outros
            log.warning('Aviso pelo %s falhou: %s', nome, e)
            erros.append(f'{nome}: {e}')

    threads = [threading.Thread(target=enviar, args=canal, daemon=True) for canal in canais]
    for t in threads:
        t.start()
    if esperar:
        for t in threads:
            t.join(timeout=70)
    return erros
