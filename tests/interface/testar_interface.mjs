// Teste da interface: dirige um Edge invisível pelo protocolo de depuração (CDP),
// clica nos principais elementos e salva prints de cada etapa. Não grava nada no banco.
//
// Precisa de Node 22+ (WebSocket nativo) e do programa rodando:
//   py -m mercado --sem-janela --porta 8765
//   node tests/interface/testar_interface.mjs http://127.0.0.1:8765/ [pasta das fotos]
//
// Os prints vão para tests/interface/fotos (ignorada pelo git). No fim, lista os erros
// de JavaScript que a página tiver mostrado; "Sem erros na página." é o esperado.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const EDGE = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles, process.env.LOCALAPPDATA]
  .filter(Boolean).map(base => join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')).find(existsSync);
const PORTA = 9333;
const URL_APP = process.argv[2] || 'http://127.0.0.1:8765/';
const SAIDA = process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), 'fotos');
if (!EDGE) throw new Error('Microsoft Edge não encontrado');
mkdirSync(SAIDA, { recursive: true });

const perfil = mkdtempSync(join(tmpdir(), 'edge-cdp-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORTA}`,
  `--user-data-dir=${perfil}`, '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const esperar = ms => new Promise(r => setTimeout(r, ms));

async function enderecoDaPagina() {
  for (let i = 0; i < 60; i++) {
    try {
      const lista = await (await fetch(`http://127.0.0.1:${PORTA}/json/list`)).json();
      const pagina = lista.find(t => t.type === 'page');
      if (pagina) return pagina.webSocketDebuggerUrl;
    } catch { /* ainda subindo */ }
    await esperar(250);
  }
  throw new Error('Edge não abriu o CDP');
}

const ws = new WebSocket(await enderecoDaPagina());
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const pendentes = new Map();
const erros = [];
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pendentes.has(m.id)) { pendentes.get(m.id)(m); pendentes.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') erros.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') erros.push(m.params.args.map(a => a.value ?? a.description).join(' '));
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error' && !/\.png/.test(m.params.entry.url || '')) erros.push(`${m.params.entry.text} ${m.params.entry.url || ''}`);
});
const cdp = (method, params = {}) => new Promise((ok, falha) => {
  const id = ++seq;
  pendentes.set(id, m => (m.error ? falha(new Error(JSON.stringify(m.error))) : ok(m.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
async function js(expr) {
  const r = await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
async function foto(nome) {
  const r = await cdp('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(SAIDA, `${nome}.png`), Buffer.from(r.data, 'base64'));
  console.log('foto', nome);
}
async function posicao(sel) {
  const pos = await js(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null;
    el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
  if (!pos) throw new Error(`não achei ${sel}`);
  return pos;
}
async function passar(sel) {
  const [x, y] = await posicao(sel);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
}
async function clicar(sel) {
  const [x, y] = await posicao(sel);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await cdp('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 });
  }
}
const CODIGOS = { Enter: 13, Escape: 27, ArrowDown: 40, ArrowUp: 38 };
async function tecla(key) {
  for (const type of ['keyDown', 'keyUp']) {
    await cdp('Input.dispatchKeyEvent', { type, key, code: key, windowsVirtualKeyCode: CODIGOS[key] });
  }
}
const digitar = text => cdp('Input.insertText', { text });

try {
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Log.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: URL_APP });
  await esperar(4000);
  await foto('c1-contas');

  // Detalhes da primeira conta da lista. Os passos com .slot.valorizado precisam
  // de pelo menos um valor cadastrado na tabela e de uma conta lida que tenha o item.
  await clicar('#linhas tr:first-child');
  await esperar(1500);
  if (await js(`!!document.querySelector('.slot.valorizado')`)) {
    await passar('.slot.valorizado');
    await esperar(400);
    await foto('c2-tooltip');
    await clicar('.slot.valorizado');
    await esperar(400);
    await foto('c3-balao');
    await tecla('Escape');
  }
  if (await js(`!!document.querySelector('.sub-abas [data-sub="inventario"]')`)) {
    await clicar('.sub-abas [data-sub="inventario"]');
    await esperar(300);
    await clicar('#sub-conteudo .slot');
    await esperar(300);
    await digitar('5');
    await esperar(300);
    await foto('c4-balao-valor');
    await tecla('Escape');
  }

  // Condição de item nos filtros
  await clicar('#add-cond');
  await esperar(200);
  await digitar('cosmos');
  await esperar(1200);
  await foto('c5-sugestoes');
  await tecla('Enter');
  await esperar(1500);
  await foto('c6-condicao');

  await clicar('#salvar-busca');
  await esperar(400);
  await foto('c7-modal-busca');
  await tecla('Escape');

  await clicar('#abrir-config');
  await esperar(800);
  await foto('c8-config');
  await tecla('Escape');

  // Detalhes recolhidos: a lista ganha colunas
  await clicar('#recolher');
  await esperar(600);
  await foto('c9-sem-detalhes');
  await clicar('#abrir-detalhes');
  await esperar(400);

  // Tabela de valores: cadastro (cancelado no fim, nada é salvo)
  await clicar('.aba[data-aba="valores"]');
  await esperar(1200);
  await clicar('#form-seletor input');
  await digitar('pedra do');
  await esperar(1200);
  await foto('v1-sugestoes');
  await tecla('Enter');
  await esperar(400);
  await clicar('#form-valor-n');
  await digitar('20');
  await esperar(300);
  await foto('v2-form');
  await clicar('#form-valor [data-acao="cancelar"]');

  await clicar('.aba[data-aba="buscas"]');
  await esperar(1000);
  await foto('b1-buscas');
} catch (e) {
  console.log('FALHOU:', e.message);
  await foto('zz-falha').catch(() => {});
  process.exitCode = 1;
} finally {
  console.log(erros.length ? `ERROS NA PÁGINA:\n- ${erros.join('\n- ')}` : 'Sem erros na página.');
  if (erros.length) process.exitCode = 1;
  ws.close();
  edge.kill();
}
