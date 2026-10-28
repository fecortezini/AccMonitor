"""Sincronia dos seus dados com o GitHub: o botão "Sincronizar" da interface.

Manda o que mudou neste PC no meus-dados.json (tabela de valores, buscas, grupos e configurações) e
traz o que mudou nos outros, pelo git da pasta do programa. Se os dois PCs mudaram desde a última
sincronia, os dados são juntados item a item (juntar), e não sobra conflito do git para resolver.

Só mexe no git quando é seguro: branch main, sem outras mudanças no código e sem commits dos dois
lados. Fora disso, explica o que falta e não mexe em nada.
"""
import json
import logging
import os
import socket
import subprocess
import threading

from .banco import dados_normalizados

log = logging.getLogger('mercado')
ARQUIVO = 'meus-dados.json'
_uma_por_vez = threading.Lock()


class ErroSincronia(Exception):
    """O que impediu a sincronia, numa mensagem para o usuário."""


def sincronizar(pasta, banco):
    """Manda e traz os dados. Devolve {'trouxe': ['2 valores', ...], 'mandou': bool, 'codigo_novo': bool}.

    codigo_novo: chegou uma versão nova do programa, que vale depois de fechar e abrir de novo.
    """
    if not _uma_por_vez.acquire(blocking=False):
        raise ErroSincronia('A sincronia já está em andamento.')
    try:
        with banco.arquivo_em_uso():
            return _sincronizar(str(pasta), banco)
    finally:
        _uma_por_vez.release()


def _sincronizar(pasta, banco):
    _conferir(pasta)
    try:
        local = banco.dados_compartilhados()
    except ValueError as e:
        raise ErroSincronia(str(e))
    _rodar(pasta, 'fetch', 'origin', 'main', timeout=120,
           erro='Não consegui falar com o GitHub (sem internet ou sem acesso). Tente de novo.')
    atras, frente = (int(n) for n in _rodar(pasta, 'rev-list', '--left-right', '--count', 'origin/main...HEAD').split())
    if atras and frente:
        raise ErroSincronia('Este PC tem commits que o GitHub não tem, e o GitHub tem commits que este PC não tem. '
                            'Junte os dois no git (git pull) antes de sincronizar.')
    juntos, trouxe, codigo_novo = local, [], False
    if atras:
        base = _dados_em(pasta, 'HEAD')  # a última versão que os dois PCs tinham em comum
        juntos = juntar(base, local, _dados_em(pasta, 'origin/main'))
        antes = _rodar(pasta, 'rev-parse', 'HEAD').strip()
        _rodar(pasta, 'checkout', '--', ARQUIVO)  # o que este PC mudou já está em "local"
        _rodar(pasta, 'merge', '--ff-only', 'origin/main', erro='Não consegui trazer as mudanças do GitHub.')
        mudados = _rodar(pasta, 'diff', '--name-only', antes, 'HEAD').split()
        codigo_novo = any(m != ARQUIVO for m in mudados)
        trouxe = _resumo(local, juntos)
    banco.substituir_dados(juntos)
    mandou = _git(pasta, 'diff', '--quiet', 'HEAD', '--', ARQUIVO).returncode != 0 or not _no_git(pasta)
    if mandou:
        _rodar(pasta, 'add', ARQUIVO)
        _rodar(pasta, 'commit', '-m', f'Meus dados ({socket.gethostname()})', '--', ARQUIVO)
    if mandou or frente:
        if _git(pasta, 'push', 'origin', 'main', timeout=180).returncode != 0:
            if mandou:  # desfaz o commit; os dados continuam no arquivo e vão na próxima vez
                _rodar(pasta, 'reset', '--soft', 'HEAD~1')
            raise ErroSincronia('Não consegui enviar para o GitHub (sem internet ou sem acesso). '
                                'Os dados continuam salvos aqui; tente de novo.')
    banco.salvar_meta('enviado_hash', banco.meta('dados_hash'))
    log.info('Sincronizado com o GitHub: %s%s%s', ', '.join(trouxe) or 'nada novo',
             '; mudanças daqui enviadas' if mandou else '', '; chegou versão nova do programa' if codigo_novo else '')
    return {'trouxe': trouxe, 'mandou': mandou, 'codigo_novo': codigo_novo}


def _conferir(pasta):
    """Só segue se o git está num estado em que dá para trazer e mandar sem risco."""
    if _git(pasta, 'rev-parse', '--is-inside-work-tree').stdout.strip() != 'true':
        raise ErroSincronia('A pasta do programa não é um repositório git.')
    ramo = _rodar(pasta, 'rev-parse', '--abbrev-ref', 'HEAD').strip()
    if ramo != 'main':
        raise ErroSincronia(f'O git está no branch "{ramo}". Volte para o main para sincronizar.')
    if _git(pasta, 'rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode == 0:
        raise ErroSincronia('O git está no meio de um merge. Termine ou cancele o merge antes de sincronizar.')
    outros = [linha[3:] for linha in _rodar(pasta, 'status', '--porcelain').splitlines()
              if not linha.startswith('??') and linha[3:].strip('"') != ARQUIVO]
    if outros:
        raise ErroSincronia(f'Há mudanças no código desta pasta que ainda não foram para o git '
                            f'({", ".join(outros[:3])}). Faça o commit delas ou descarte antes de sincronizar.')


def juntar(base, local, remoto):
    """Junta as mudanças deste PC (local) e do outro (remoto) desde a última sincronia (base).

    Item a item (valores, buscas e grupos pelo id; configurações pela chave):
    - o que só um lado criou, mudou ou apagou fica como esse lado deixou;
    - os dois mudaram o mesmo item: fica a versão mais recente (atualizado_em);
    - um apagou e o outro mudou: fica a mudança;
    - os dois criaram um item com o mesmo id: o do outro PC fica com o id, e o deste ganha um novo.
      As buscas e os valores deste PC que usavam um grupo que mudou de id passam a usar o id novo;
    - uma configuração mudada nos dois: fica a deste PC.
    As favoritas também vão pelo id, que é o da conta: marcada nos dois PCs, fica uma só (ver _juntar_favoritas).
    """
    cfg = {chave: remoto['configuracoes'].get(chave, v) if v == base['configuracoes'].get(chave) else v
           for chave, v in local['configuracoes'].items()}
    grupos, novos_ids = _juntar_lista(base['grupos'], local['grupos'], remoto['grupos'])
    valores, _ = _juntar_lista(base['valores'], local['valores'], remoto['valores'], _trocar_grupo_do_valor(novos_ids))
    buscas, _ = _juntar_lista(base['buscas'], local['buscas'], remoto['buscas'], _trocar_grupos(novos_ids))
    favoritas = _juntar_favoritas(base['favoritas'], local['favoritas'], remoto['favoritas'])
    return dados_normalizados({'configuracoes': cfg, 'valores': valores, 'buscas': buscas, 'grupos': grupos,
                               'favoritas': favoritas})


def _juntar_lista(base, local, remoto, ajustar_local=None):
    """(itens juntados, {id antigo: id novo} dos itens deste PC que tiveram de mudar de id)."""
    b_, l_, r_ = ({x['id']: x for x in lista} for lista in (base, local, remoto))
    ajustar = ajustar_local or (lambda x: x)
    juntos, renumerar = [], []
    for i in sorted(set(b_) | set(l_) | set(r_)):
        b, l, r = b_.get(i), l_.get(i), r_.get(i)
        if l == r:
            escolhido = l                  # iguais, ou os dois apagaram
        elif l == b:
            escolhido = r                  # só o outro PC mudou (ou apagou)
        elif r == b:
            escolhido = ajustar(l)         # só este PC mudou (ou apagou)
        elif b is None:                    # os dois criaram com o mesmo id
            escolhido = r
            renumerar.append(l)
        elif l is None or r is None:       # um apagou e o outro mudou
            escolhido = ajustar(l) if l is not None else r
        else:                              # os dois mudaram: fica a versão mais recente
            escolhido = ajustar(l) if l.get('atualizado_em', '') >= r.get('atualizado_em', '') else r
        if escolhido is not None:
            juntos.append(escolhido)
    proximo, novos_ids = max((x['id'] for x in juntos), default=0) + 1, {}
    for x in renumerar:
        novos_ids[x['id']] = proximo
        juntos.append({**ajustar(x), 'id': proximo})
        proximo += 1
    return juntos, novos_ids


def _juntar_favoritas(base, local, remoto):
    """Como _juntar_lista, mas o id é o da conta e nunca muda: a mesma conta marcada nos dois PCs fica uma só,
    a marcada primeiro. Desmarcada (ou vendida) num PC e intocada no outro, sai."""
    b_, l_, r_ = ({x['id']: x for x in lista} for lista in (base, local, remoto))
    juntas = []
    for i in sorted(set(b_) | set(l_) | set(r_)):
        b, l, r = b_.get(i), l_.get(i), r_.get(i)
        if l == r or r == b:
            escolhida = l
        elif l == b:
            escolhida = r
        elif l is None or r is None:  # um desmarcou e o outro mudou: fica a mudança
            escolhida = l if l is not None else r
        else:                         # marcada nos dois
            escolhida = min(l, r, key=lambda f: f['criado_em'])
        if escolhida is not None:
            juntas.append(escolhida)
    return juntas


def _trocar_grupos(novos_ids):
    """Ajuste das buscas deste PC: as condições de grupo passam para o id novo do grupo."""
    if not novos_ids:
        return None

    def trocar(busca):
        filtros = json.loads(json.dumps(busca['filtros']))  # cópia
        for chave in ('itens', 'algum'):
            for c in filtros.get(chave) or []:
                if isinstance(c, dict) and c.get('grupo_id') in novos_ids:
                    c['grupo_id'] = novos_ids[c['grupo_id']]
        return {**busca, 'filtros': filtros}
    return trocar


def _trocar_grupo_do_valor(novos_ids):
    """Ajuste dos valores deste PC: o valor de um grupo passa para o id novo do grupo."""
    if not novos_ids:
        return None
    return lambda v: {**v, 'grupo_id': novos_ids[v['grupo_id']]} if v.get('grupo_id') in novos_ids else v


def _resumo(antes, depois):
    """O que mudou de antes para depois, em partes curtas: ['2 valores', '1 grupo', 'configurações']."""
    partes = []
    for secao, um, varios in (('valores', 'valor', 'valores'), ('buscas', 'busca', 'buscas'), ('grupos', 'grupo', 'grupos'),
                              ('favoritas', 'favorita', 'favoritas')):
        a, d = ({x['id']: x for x in dados[secao]} for dados in (antes, depois))
        if n := sum(a.get(i) != d.get(i) for i in set(a) | set(d)):
            partes.append(f'{n} {um if n == 1 else varios}')
    if antes['configuracoes'] != depois['configuracoes']:
        partes.append('configurações')
    return partes


def _dados_em(pasta, ref):
    """Os dados do meus-dados.json numa versão do git (vazios se ele não existe nela)."""
    r = _git(pasta, 'show', f'{ref}:{ARQUIVO}')
    texto = r.stdout.strip() if r.returncode == 0 else ''
    return dados_normalizados(json.loads(texto) if texto else {})


def _no_git(pasta):
    return _git(pasta, 'ls-files', '--error-unmatch', ARQUIVO).returncode == 0


def _git(pasta, *args, timeout=60):
    try:
        return subprocess.run(['git', *args], cwd=pasta, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except FileNotFoundError:
        raise ErroSincronia('O git não foi encontrado neste PC.')
    except subprocess.TimeoutExpired:
        raise ErroSincronia(f'O git demorou demais ("git {args[0]}"). Confira a internet e tente de novo.')


def _rodar(pasta, *args, timeout=60, erro=None):
    """Roda o git e devolve a saída; se ele falhar, a sincronia para com a mensagem erro (ou a do git)."""
    r = _git(pasta, *args, timeout=timeout)
    if r.returncode != 0:
        detalhe = ((r.stderr or r.stdout).strip().splitlines() or [''])[-1]
        log.warning('git %s falhou: %s', ' '.join(args), detalhe)
        raise ErroSincronia(erro or f'O git falhou em "git {args[0]}": {detalhe}')
    return r.stdout
