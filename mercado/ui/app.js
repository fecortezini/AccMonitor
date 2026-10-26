'use strict';
/* Mercado PW — interface. Conversa com o servidor local em /api (ver mercado/servidor.py). */

// ================================================================ utilidades
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const TOKEN = $('meta[name="token"]').content;
const COSMOS = 72573;
const LANCE_MINIMO_PCT = 70;  // o site aceita lances a partir de 70% do preço pedido (valor fixo)
const lanceMinimo = preco => Math.ceil(preco * LANCE_MINIMO_PCT / 100);  // arredonda para cima: 45 → 32
const ICONE = id => `https://pwdatabase.theclassic.games/assets/img/vtheclassicpw187/${id}.png`;
const CLASSE = n => `https://theclassic.games/assets/img/pw_roles/occu_${n}.png`;
const SEM_IMG = `onerror="this.style.visibility='hidden'"`;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const norm = s => String(s ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
const limitar = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const inteiro = n => (n == null ? '—' : Math.round(n).toLocaleString('pt-BR'));
const decimal = (n, casas = 2) => n.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });

/** casas: fixa as casas decimais (as colunas da lista usam as mesmas em todas as linhas, ver casasReais). */
function reais(v, sinal = false, casas = null) {
  if (v == null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  const t = decimal(a, casas ?? (a >= 100 ? 0 : 2));
  const p = sinal ? (v >= 0 ? '+' : '−') : (v < 0 ? '−' : '');
  return `${p}R$ ${t}`;
}
function ouro(kk) {
  if (kk == null) return '—';
  const f = x => x.toLocaleString('pt-BR', { maximumFractionDigits: 3 });
  return kk >= 1000 ? `${f(kk / 1000)} bi` : `${f(kk)} kk`;
}
const pct = p => (p == null ? '' : `${Math.round(p * 100)}%`);
const qtdCurta = q => (q >= 100000 ? `${Math.round(q / 1000)}k` : q >= 10000 ? `${(q / 1000).toFixed(1).replace('.', ',')}k` : String(q));
const kkPara = (kk, bi) => kk / 1000 * bi;

function numeroDe(s) {
  let t = String(s ?? '').trim().replace(/\s/g, '').replace(/^R\$/i, '');
  if (!t) return null;
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
  else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, '');
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
/** Preço em TCC digitado: além de "5000" e "5.000", aceita "5k" (= 5.000). */
function precoDe(s) {
  const k = /^(.*\d)\s*k$/i.exec(String(s ?? '').trim());
  const n = numeroDe(k ? k[1] : s);
  return n != null && k ? n * 1000 : n;
}

function ha(iso) {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `há ${Math.round(s)} s`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  return `há ${Math.round(s / 86400)} d`;
}
const hora = iso => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '');
function quando(iso) {
  const d = new Date(iso);
  const hoje = new Date();
  return d.toDateString() === hoje.toDateString() ? hora(iso)
    : d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' + hora(iso);
}

const PROGRAMA_FECHADO = 'O Mercado PW não está rodando. Feche esta janela e abra de novo pelo “Mercado PW.bat”.';
async function api(metodo, caminho, corpo) {
  const opcoes = { method: metodo, headers: { 'X-Token': TOKEN } };
  if (corpo !== undefined) {
    opcoes.headers['Content-Type'] = 'application/json';
    opcoes.body = JSON.stringify(corpo);
  }
  let r;
  try {
    r = await fetch(caminho, opcoes);
  } catch {  // sem resposta nenhuma: o programa foi encerrado e esta janela ficou aberta
    throw new Error(PROGRAMA_FECHADO);
  }
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dados.erro || `Erro ${r.status}`);
  return dados;
}

let avisoTimer;
function avisar(msg, ruim = false, ms = null) {
  const el = $('#aviso-rapido');
  el.textContent = msg;
  el.classList.toggle('ruim', ruim);
  el.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { el.hidden = true; }, ms ?? (ruim ? 6000 : 3000));
}
window.addEventListener('error', e => avisar(`Erro na interface: ${e.message}`, true));
window.addEventListener('unhandledrejection', e => avisar(`Erro: ${e.reason?.message || e.reason}`, true));

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
function guardar(chave, valor) { try { localStorage.setItem(chave, JSON.stringify(valor)); } catch { /* sem armazenamento */ } }
function lembrar(chave, padrao) { try { return JSON.parse(localStorage.getItem(chave)) ?? padrao; } catch { return padrao; } }

// ================================================================ estado
// itens: "Tem item" (a conta precisa ter todos); algum: "Tem pelo menos um" (basta um deles)
const FILTROS_PADRAO = { nome: '', classes: [], preco_min: null, preco_max: null, nivel_min: null, ceu: '',
  itens: [], algum: [], so_lucro: false, so_novas: false, ordem: 'lucro_rs' };
const S = {
  aba: 'contas', estado: null, versao: null, versaoCarregada: {},
  config: null, filtros: { ...structuredClone(FILTROS_PADRAO), ...lembrar('filtros', {}) },  // cópia: "Limpar" volta ao padrão
  resultado: null, limite: 300, sel: null, conta: null, subAba: null,
  valores: [], resumo: null, form: null, confirmando: null,
  buscas: [], avisos: [], buscaAtual: lembrar('buscaAtual', null), grupos: [],
  classesDesenhadas: '', ceusDesenhados: '',
  lerPrimeiro: lembrar('lerPrimeiro', true),  // "Ler primeiro as destes filtros", na barra de leitura
};
// Linhas da tabela por item: i<item_id>, n<nome> (ainda sem item_id) e g<item_id> (as dos grupos que têm o item)
const valoresPorItem = () => {
  const m = new Map();
  const por = (k, v) => { if (!m.has(k)) m.set(k, []); m.get(k).push(v); };
  for (const v of S.valores) {
    if (v.grupo_id != null) for (const id of v.itens || []) por(`g${id}`, v);
    else por(v.item_id != null ? `i${v.item_id}` : `n${norm(v.nome)}`, v);
  }
  for (const l of m.values()) l.sort((a, b) => b.refino_min - a.refino_min);
  return m;
};
/** A linha que vale para o item, como no servidor (mercado/valor.py, Tabela.linha_para): a faixa do próprio item;
 *  sem uma que sirva, a dos grupos dele, a que dá mais. */
function linhaValorPara(it, indice = valoresPorItem()) {
  const refino = it.refino || 0;
  const faixas = indice.get(`i${it.item_id}`) || indice.get(`n${norm(it.nome)}`) || [];
  const propria = faixas.find(v => v.refino_min <= refino);
  if (propria) return propria;
  const porGrupo = new Map();  // a faixa de cada grupo: a primeira que serve, já que estão do maior refino ao menor
  for (const v of indice.get(`g${it.item_id}`) || []) if (v.refino_min <= refino && !porGrupo.has(v.grupo_id)) porGrupo.set(v.grupo_id, v);
  return [...porGrupo.values()].sort((a, b) => b.valor_kk - a.valor_kk)[0] || null;
}

// ================================================================ topo e estado do coletor
async function atualizarEstado() {
  try {
    const e = await api('GET', '/api/estado');
    S.estado = e;
    desenharTopo(e);
    desenharFiltrosDinamicos(e);
    if (S.versao !== e.versao) {
      S.versao = e.versao;
      recarregarVista();
    }
  } catch (err) {
    const st = $('#status');
    st.className = 'status ruim';
    st.querySelector('span').textContent = 'Programa sem resposta';
    if (err.message === PROGRAMA_FECHADO) {  // na faixa do topo, para não clicar em nada achando que funciona
      const faixa = $('#faixa');
      faixa.querySelector('span').textContent = PROGRAMA_FECHADO;
      faixa.hidden = false;
    }
  }
}

function desenharTopo(e) {
  $('#n-contas').textContent = inteiro(e.ativas);
  $('#c-bi').textContent = `R$ ${decimal(e.rs_por_bi)}`;
  $('#c-tcc').textContent = `R$ ${decimal(e.rs_por_tcc)}`;
  const st = $('#status');
  if (e.sem_conexao_desde) {
    st.className = 'status ruim';
    st.querySelector('span').textContent = `Sem conexão desde ${hora(e.sem_conexao_desde)}`;
  } else if (e.ultima_consulta) {
    st.className = 'status ok';
    st.querySelector('span').textContent = `Atualizado ${ha(e.ultima_consulta)}`;
  } else {
    st.className = 'status';
    st.querySelector('span').textContent = 'Consultando o site…';
  }
  st.title = `A lista é consultada a cada ${e.intervalo_s} s`;
  $('#sincronizar').classList.toggle('pendente', !!e.dados_a_enviar);
  const faixa = $('#faixa');
  faixa.hidden = !(e.erro && !e.sem_conexao_desde);
  if (!faixa.hidden) faixa.querySelector('span').textContent = e.erro;
  desenharCarga();
}

/** Barra "Lendo as contas" enquanto a base não está toda lida. Com filtros, as contas deles podem ser lidas primeiro
 *  (para_ler: as que faltam ler e podem bater com eles, que o servidor devolve na busca). */
function desenharCarga() {
  const e = S.estado;
  if (!e) return;
  const carga = $('#carga');
  carga.hidden = !e.ativas || e.ativas - e.lidas <= 0;
  if (carga.hidden) return;
  const filtrando = temFiltro();
  const botao = $('#ler-primeiro');
  botao.hidden = !filtrando;
  botao.classList.toggle('on', S.lerPrimeiro);
  carga.querySelector('i').style.width = `${(e.lidas / e.ativas) * 100}%`;
  const doFiltro = S.resultado?.para_ler;
  let texto = 'O valor e os filtros de materiais ficam completos quando terminar; as contas novas são lidas primeiro.';
  if (filtrando && S.lerPrimeiro && doFiltro != null) {
    texto = doFiltro ? `Primeiro as que podem bater com estes filtros: faltam <b>${inteiro(doFiltro)}</b>`
      + `${e.por_minuto ? ` (${tempoParaLer(doFiltro, e.por_minuto)})` : ''}. Depois, as outras.`
      : 'As contas destes filtros já foram lidas. Agora, as outras.';
  } else if (!filtrando) {
    texto += ' Com filtros, dá para ler primeiro as contas deles.';
  }
  // quanto falta: as contas da fila do coletor no ritmo dos últimos minutos (por_minuto, que o servidor calcula)
  const falta = !e.fila ? '' : e.por_minuto ? ` · faltam <b>${tempoParaLer(e.fila, e.por_minuto)}</b> (${inteiro(Math.round(e.por_minuto))} por minuto)`
    : ' · calculando quanto falta';
  carga.querySelector('span').innerHTML = `Lendo as contas: <b>${inteiro(e.lidas)}</b> de ${inteiro(e.ativas)}${falta}. ${texto}`;
}

/** Tempo para ler n contas no ritmo de agora: "menos de 1 min", "~25 min" ou "~1 h 20 min". */
function tempoParaLer(n, porMinuto) {
  const min = Math.round(n / porMinuto);
  if (min < 1) return 'menos de 1 min';
  if (min < 60) return `~${min} min`;
  return `~${Math.floor(min / 60)} h${min % 60 ? ` ${min % 60} min` : ''}`;
}

/** Algum filtro que limita as contas? Lucro e ordem não contam: não dá para saber o lucro sem ler a conta. */
function temFiltro() {
  const f = S.filtros;
  return !!(f.nome || f.classes.length || f.preco_min != null || f.preco_max != null || f.nivel_min != null || f.ceu
    || f.itens.length || f.algum.length || f.so_novas);
}

const recarregarVista = debounce(() => {
  if (S.aba === 'contas') buscar().then(recarregarDetalhesSeMudou);
  if (S.aba === 'valores') carregarValores();
  if (S.aba === 'buscas') carregarBuscas();
  S.versaoCarregada[S.aba] = S.versao;
}, 700);

function trocarAba(aba) {
  S.aba = aba;
  history.replaceState(null, '', aba === 'contas' ? location.pathname : `#${aba}`);
  $$('.aba').forEach(b => b.classList.toggle('on', b.dataset.aba === aba));
  $$('.vista').forEach(v => v.classList.toggle('on', v.id === `v-${aba}`));
  fecharBalao();
  if (S.versaoCarregada[aba] !== S.versao) {
    S.versaoCarregada[aba] = S.versao;
    if (aba === 'contas') buscar();
    if (aba === 'valores') carregarValores();
    if (aba === 'buscas') carregarBuscas();
  }
}

// ================================================================ filtros
function desenharFiltrosDinamicos(e) {
  const classes = JSON.stringify(e.classes.map(c => c.classe));
  if (classes !== S.classesDesenhadas) {
    S.classesDesenhadas = classes;
    desenharClasses();
  }
  const ceus = [...new Set(e.ceus.map(c => c.replace(/\s+[IVXLC]+$/, '')))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  const chave = JSON.stringify(ceus);
  if (chave !== S.ceusDesenhados) {
    S.ceusDesenhados = chave;
    const sel = $('#f-ceu');
    sel.innerHTML = '<option value="">Qualquer</option>' + ceus.map(c => `<option>${esc(c)}</option>`).join('');
    sel.value = S.filtros.ceu || '';
  }
}

function desenharClasses() {
  const lista = S.estado?.classes || [];
  $('#f-classes').innerHTML = lista.map(c => `
    <button class="chip ${S.filtros.classes.includes(c.classe) ? 'on' : ''}" data-classe="${esc(c.classe)}" title="${inteiro(c.n)} anúncios">
      <img src="${CLASSE(c.ocupacao)}" alt="" ${SEM_IMG}>${esc(c.classe)}</button>`).join('');
}

function preencherFiltros() {
  const f = S.filtros;
  $('#f-nome').value = f.nome || '';
  $('#f-preco-min').value = f.preco_min ?? '';
  $('#f-preco-max').value = f.preco_max ?? '';
  $('#f-nivel').value = f.nivel_min ?? '';
  $('#f-ceu').value = f.ceu || '';
  $('#f-lucro').classList.toggle('on', !!f.so_lucro);
  $('#f-novas').classList.toggle('on', !!f.so_novas);
  desenharClasses();
  desenharCondicoes();  // também desenha e escolhe a ordenação, que depende das condições
}

const ONDE = [['', 'em qualquer lugar'], ['equipado', 'equipado'], ['mochila', 'na mochila'], ['banco', 'no banco'],
  ['cartas', 'nas cartas'], ['engastada', 'engastada'], ['mascotes', 'nos mascotes']];
// Seção dos itens para cada "onde"; em qualquer lugar, fora o códice e a recompra (como no banco.py)
const SECAO_DO_ONDE = { equipado: 'equipado', mochila: 'inventario', banco: 'banco', cartas: 'cartas',
  engastada: 'engastada', mascotes: 'mascotes' };
const FORA_DA_BUSCA = new Set(['codice', 'recompra']);

// As condições ficam na ordem em que os itens foram escolhidos (a de importância para quem busca), e as colunas
// da lista e a aba Pesquisados seguem essa ordem. Ela não muda quem bate nem o preço por unidade (soma de todos).
// As de "Tem pelo menos um" usam os mesmos campos, mas só filtram: não viram colunas nem entram no preço por unidade.
function desenharCondicoes() {
  $('#f-itens').innerHTML = S.filtros.itens.map((c, i) => condicaoHtml(c, i, true)).join('');
  $('#f-algum').innerHTML = S.filtros.algum.map((c, i) => condicaoHtml(c, i, false)).join('');
  desenharOrdens();
}

function condicaoHtml(c, i, todos) {
  return `
    <div class="condicao" data-i="${i}">
      <div class="condicao-topo">${tituloDaCondicao(c, todos)}<button data-acao="remover" title="Remover"><svg class="ic"><use href="#i-x"/></svg></button></div>
      <div class="condicao-campos">
        <select class="caixa" data-campo="refino_min" title="Refino mínimo">
          <option value="0">qualquer refino</option>${Array.from({ length: 15 }, (_, n) => `<option value="${n + 1}" ${c.refino_min === n + 1 ? 'selected' : ''}>refino ≥ +${n + 1}</option>`).join('')}
        </select>
        <input class="caixa" data-campo="qtd_min" inputmode="numeric" placeholder="quantidade ≥ 1" value="${c.qtd_min > 1 ? c.qtd_min : ''}" title="Quantidade mínima (soma todas as pilhas)">
        <select class="caixa largo" data-campo="onde" title="Onde o item precisa estar">${ONDE.map(([v, t]) => `<option value="${v}" ${(c.onde || '') === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
      </div>
    </div>`;
}

/** Ícone e nome da condição: o item, o texto do nome ou o grupo (com o nome e o número de itens de agora).
 *  todos: a condição é do "Tem item", onde o grupo exige todos os itens dele. */
function tituloDaCondicao(c, todos) {
  if (c.grupo_id != null) {
    const g = S.grupos.find(x => x.id === c.grupo_id);
    const nome = esc(g?.nome ?? c.nome);
    return `<span class="icone-grupo" title="Grupo de itens"><svg class="ic"><use href="#i-list"/></svg></span>
      <b title="${todos ? `Todos os itens do grupo ${nome}` : `Qualquer item do grupo ${nome}`}">${nome}</b>
      <small>${g ? `${todos && g.itens.length > 1 ? 'todos os ' : ''}${inteiro(g.itens.length)} ${g.itens.length === 1 ? 'item' : 'itens'}`
        : S.gruposCarregados ? 'grupo apagado' : ''}</small>`;
  }
  if (c.item_id) return `<img src="${ICONE(c.item_id)}" alt="" ${SEM_IMG}><b title="${esc(c.nome)}">${esc(c.nome)}</b>`;
  return `<b title="Qualquer item com “${esc(c.nome)}” no nome">“${esc(c.nome)}” no nome</b>`;
}

/** Com condições de item, a ordenação ganha as opções pelos itens pesquisados (ver _ordenar_por_itens no banco.py). */
function desenharOrdens() {
  const sel = $('#f-ordem');
  const conds = S.filtros.itens;
  sel.querySelector('optgroup')?.remove();
  if (conds.length) {
    const porItem = conds.length > 1 ? conds.map((c, i) =>
      `<option value="item:${i}">Mais ${esc(c.nome)}${c.refino_min ? ' +' + c.refino_min : ''}</option>`).join('') : '';
    sel.insertAdjacentHTML('beforeend', `<optgroup label="Itens pesquisados">
      <option value="itens">Mais itens pesquisados</option>${porItem}<option value="preco_item">Menor preço por unidade</option></optgroup>`);
  }
  if (![...sel.options].some(o => o.value === S.filtros.ordem)) {
    S.filtros.ordem = conds.length && /^item:/.test(S.filtros.ordem) ? 'itens' : FILTROS_PADRAO.ordem;
  }
  sel.value = S.filtros.ordem;
}

function filtrosMudaram() {
  guardar('filtros', S.filtros);
  S.limite = 300;
  buscarEmBreve();
}

function iniciarFiltros() {
  $('#ler-primeiro').addEventListener('click', () => {
    S.lerPrimeiro = !S.lerPrimeiro;
    guardar('lerPrimeiro', S.lerPrimeiro);
    desenharCarga();
    buscar();  // o pedido vai junto com a busca
  });
  $('#f-classes').addEventListener('click', e => {
    const chip = e.target.closest('[data-classe]');
    if (!chip) return;
    const c = chip.dataset.classe;
    const l = S.filtros.classes;
    S.filtros.classes = l.includes(c) ? l.filter(x => x !== c) : [...l, c];
    chip.classList.toggle('on');
    filtrosMudaram();
  });
  const texto = (id, campo, ler = null) => $(id).addEventListener('input', e => {
    S.filtros[campo] = ler ? ler(e.target.value) : e.target.value;
    filtrosMudaram();
  });
  texto('#f-nome', 'nome');
  texto('#f-preco-min', 'preco_min', precoDe);
  texto('#f-preco-max', 'preco_max', precoDe);
  texto('#f-nivel', 'nivel_min', numeroDe);
  $('#f-ceu').addEventListener('change', e => { S.filtros.ceu = e.target.value; filtrosMudaram(); });
  $('#f-ordem').addEventListener('change', e => { S.filtros.ordem = e.target.value; marcarOrdemNaTabela(); filtrosMudaram(); });
  for (const [id, campo] of [['#f-lucro', 'so_lucro'], ['#f-novas', 'so_novas']]) {
    $(id).addEventListener('click', e => {
      S.filtros[campo] = !S.filtros[campo];
      e.currentTarget.classList.toggle('on', S.filtros[campo]);
      filtrosMudaram();
    });
  }
  for (const [lista, chave] of [['#f-itens', 'itens'], ['#f-algum', 'algum']]) {
    $(lista).addEventListener('click', e => {
      if (!e.target.closest('[data-acao="remover"]')) return;
      const i = Number(e.target.closest('.condicao').dataset.i);
      S.filtros[chave].splice(i, 1);
      const porItem = chave === 'itens' && /^item:(\d+)$/.exec(S.filtros.ordem);  // "Mais <item>" segue o item, não a posição
      if (porItem) {
        const k = Number(porItem[1]);
        S.filtros.ordem = k === i ? 'itens' : `item:${k > i ? k - 1 : k}`;
      }
      desenharCondicoes();
      filtrosMudaram();
    });
    $(lista).addEventListener('change', e => {
      const campo = e.target.dataset.campo;
      if (!campo) return;
      const c = S.filtros[chave][Number(e.target.closest('.condicao').dataset.i)];
      c[campo] = campo === 'onde' ? e.target.value : Math.max(campo === 'qtd_min' ? 1 : 0, Math.round(numeroDe(e.target.value) || 0));
      desenharOrdens();  // o refino aparece no nome das opções "Mais <item>"
      filtrosMudaram();
    });
  }
  $('#limpar-filtros').addEventListener('click', () => {
    S.filtros = structuredClone(FILTROS_PADRAO);
    S.buscaAtual = null;
    guardar('buscaAtual', null);
    preencherFiltros();
    filtrosMudaram();
  });
  $('#salvar-busca').addEventListener('click', abrirModalBusca);
  for (const [seletor, botao, chave] of [['#novo-item', '#add-cond', 'itens'], ['#novo-algum', '#add-algum', 'algum']]) {
    const fechar = () => { $(seletor).hidden = true; $(botao).hidden = false; };
    seletorDeItem($(seletor), item => {
      if (chave === 'itens' && !S.filtros.itens.length) S.filtros.ordem = 'itens';  // buscando itens, primeiro quem tem mais
      const qual = item.grupo_id != null ? { grupo_id: item.grupo_id } : { item_id: item.item_id };
      S.filtros[chave].push({ ...qual, nome: item.nome, refino_min: 0, qtd_min: 1, onde: '' });
      fechar();
      desenharCondicoes();
      filtrosMudaram();
    }, fechar, {
      titulo: q => `Buscar itens com “${q}” no nome`, sempre: true,
      nota: 'Vale também para itens que ainda não apareceram nas contas lidas; elas entram conforme forem lidas.',
    }, chave === 'itens' ? 'todos' : true);
    $(botao).addEventListener('click', () => {
      $(seletor).hidden = false;
      $(botao).hidden = true;
      $(`${seletor} input`).value = '';
      $(`${seletor} .sugestoes`).innerHTML = '';
      $(`${seletor} input`).focus();
    });
  }
}

/** Caixa de busca de itens com sugestões (catálogo do site + itens vistos nas contas).
 *  porNome ({ titulo(texto), nota, sempre }) oferece usar o texto digitado, para itens que ainda não
 *  apareceram em nenhuma conta lida; com "sempre", a opção aparece mesmo quando há sugestões.
 *  comGrupos põe os grupos de itens antes dos itens (todos, com a caixa vazia); escolher um grupo
 *  devolve { grupo_id, nome, itens }. Com 'valor', a legenda do grupo é a da tabela de valores (vale para cada item);
 *  com 'todos', a do "Tem item" (precisa de todos os itens). */
function seletorDeItem(raiz, aoEscolher, aoCancelar, porNome = null, comGrupos = false) {
  const entrada = $('input', raiz);
  const lista = $('.sugestoes', raiz);
  let itens = [];
  let opcoes = [];  // grupos e itens, na ordem da lista (para as setas e o Enter)
  let destaque = 0;
  let seq = 0;
  const desenhar = () => {
    const q = entrada.value.trim();
    const grupos = comGrupos ? S.grupos.filter(g => norm(g.nome).includes(norm(q))) : [];
    opcoes = [...grupos.map(grupo => ({ grupo })), ...(q.length >= 2 ? itens.map(item => ({ item })) : [])];
    if (!opcoes.length && q.length < 2) { lista.innerHTML = ''; return; }
    destaque = limitar(destaque, 0, Math.max(0, opcoes.length - 1));
    const marcar = nome => {
      const i = q ? norm(nome).indexOf(norm(q)) : -1;
      return i < 0 ? esc(nome) : esc(nome.slice(0, i)) + '<mark>' + esc(nome.slice(i, i + q.length)) + '</mark>' + esc(nome.slice(i + q.length));
    };
    let html = opcoes.map(({ grupo, item }, i) => `
      <button class="sugestao ${i === destaque ? 'on' : ''}" data-i="${i}">
        ${grupo ? `<span class="icone-grupo"><svg class="ic"><use href="#i-list"/></svg></span>
          <div><b>${marcar(grupo.nome)}</b><small>${comGrupos === 'valor' ? descricaoItem({ grupo_id: grupo.id, itens: grupo.itens })
            : comGrupos === 'todos' ? `Grupo · precisa de todos os ${inteiro(grupo.itens.length)} ${grupo.itens.length === 1 ? 'item' : 'itens'}`
            : `Grupo · qualquer um de ${inteiro(grupo.itens.length)} ${grupo.itens.length === 1 ? 'item' : 'itens'}`}</small></div>`
        : `<img src="${ICONE(item.item_id)}" alt="" ${SEM_IMG}>
          <div><b>${marcar(item.nome)}</b><small>${esc(descricaoItem(item))}</small></div>`}${i === destaque ? '<kbd>Enter</kbd>' : ''}
      </button>`).join('');
    if (porNome && q.length >= 2 && (porNome.sempre || !itens.some(it => norm(it.nome) === norm(q)))) {
      html += `<button class="sugestao" data-nome="1"><div><b>${porNome.titulo(esc(q))}</b><small>${porNome.nota}</small></div></button>`;
    }
    if (!html) html = '<div class="sugestao vazia">Nenhum item com esse nome.</div>';
    lista.innerHTML = html;
    lista.scrollIntoView({ block: 'nearest' });  // no fim do painel, a lista ficaria abaixo da parte visível
  };
  const escolher =({ grupo, item }) => aoEscolher(grupo ? { grupo_id: grupo.id, nome: grupo.nome, itens: grupo.itens } : item);
  const procurar = debounce(async () => {
    const q = entrada.value.trim();
    const meu = ++seq;
    if (q.length < 2) { itens = []; destaque = 0; desenhar(); return; }
    try {
      const r = await api('GET', `/api/sugestoes?q=${encodeURIComponent(q)}`);
      if (meu !== seq) return;
      itens = r.itens;
      destaque = 0;
      desenhar();
    } catch (err) { avisar(err.message, true); }
  }, 180);
  entrada.addEventListener('input', procurar);
  if (comGrupos) entrada.addEventListener('focus', desenhar);  // com a caixa vazia, os grupos já aparecem
  entrada.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      destaque = limitar(destaque + (e.key === 'ArrowDown' ? 1 : -1), 0, Math.max(0, opcoes.length - 1));
      desenhar();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (opcoes[destaque]) escolher(opcoes[destaque]);
      else if (porNome && entrada.value.trim().length >= 3) aoEscolher({ item_id: null, nome: entrada.value.trim(), tipo: 'item', contas: 0 });
    } else if (e.key === 'Escape') {
      aoCancelar?.();
    }
  });
  lista.addEventListener('mousedown', e => e.preventDefault());
  lista.addEventListener('click', e => {
    const b = e.target.closest('.sugestao');
    if (!b || b.classList.contains('vazia')) return;
    if (b.dataset.nome) aoEscolher({ item_id: null, nome: entrada.value.trim(), tipo: 'item', contas: 0 });
    else escolher(opcoes[Number(b.dataset.i)]);
  });
  entrada.addEventListener('blur', () => setTimeout(() => { if (!raiz.contains(document.activeElement) && !entrada.value.trim()) aoCancelar?.(); }, 150));
  return { limpar: () => { entrada.value = ''; itens = []; opcoes = []; lista.innerHTML = ''; }, focar: () => entrada.focus() };
}

const TIPOS = { livros: 'Livro', armas: 'Arma', cartas: 'Carta', pedra: 'Pedra engastada', elmos: 'Elmo', peitorais: 'Peitoral',
  calcas: 'Calça', botas: 'Botas', braceletes: 'Bracelete', colares: 'Colar', capas: 'Capa', aneis: 'Anel',
  ornamentos: 'Ornamento', astrolabios: 'Astrolábio', conduites: 'Conduíte', item: 'Item', equipamento: 'Equipamento' };
function descricaoItem(it) {
  if (it.grupo_id != null) {
    const n = it.itens?.length || 0;
    return `Grupo · vale para cada um dos ${inteiro(n)} ${n === 1 ? 'item' : 'itens'}`;
  }
  const tipo = TIPOS[it.tipo] || 'Item';
  const partes = [it.tipo === 'pedra' && it.efeito ? `${tipo} · ${it.efeito}` : tipo];
  partes.push(it.contas ? `vista em ${inteiro(it.contas)} ${it.contas === 1 ? 'conta' : 'contas'}` : (it.no_catalogo ? 'no catálogo do site' : 'ainda não vista'));
  return partes.join(' · ');
}

// ================================================================ lista de contas
let buscaSeq = 0;
async function buscar() {
  const meu = ++buscaSeq;
  try {
    const r = await api('POST', '/api/buscar', { ...S.filtros, ler_primeiro: S.lerPrimeiro && temFiltro() });
    if (meu !== buscaSeq) return;
    const condicoes = () => JSON.stringify([itensDaBusca(), algumDaBusca()]);
    const antes = condicoes();
    S.resultado = r;
    desenharLista();
    desenharCarga();
    if (S.conta && condicoes() !== antes) {  // a aba "Pesquisados" acompanha a busca
      if (antes === '[[],[]]') S.subAba = 'busca';
      desenharDetalhes();
    }
  } catch (err) { avisar(err.message, true); }
}

// ---------------------------------------------------------------- itens pesquisados
// Condições de item da última busca, como o servidor devolveu: "Tem item" (busca_itens) e "Tem pelo menos um" (busca_algum).
const itensDaBusca = () => S.resultado?.busca_itens || [];
const algumDaBusca = () => S.resultado?.busca_algum || [];
const somaBusca = c => (c.qtd_busca ? c.qtd_busca.reduce((s, q) => s + q, 0) : null);
const curto = n => n.toLocaleString('pt-BR', { maximumSignificantDigits: 3 });

/** O item atende à condição? Mesma regra do servidor (mercado/banco.py, _filtro_item): pelo id do item,
 *  por qualquer item do grupo (itens, que o servidor devolve) ou, na condição digitada pelo nome, por qualquer
 *  item com esse texto no nome. */
function bateCondicao(it, c) {
  const qual = c.grupo_id != null ? (c.itens || []).includes(it.item_id)
    : c.item_id != null ? it.item_id === c.item_id : norm(it.nome).includes(norm(c.nome));
  if (!qual) return false;
  const secao = SECAO_DO_ONDE[c.onde];
  return (it.refino || 0) >= c.refino_min && (secao ? it.secao === secao : !FORA_DA_BUSCA.has(it.secao));
}

/** Para cada condição da busca: os itens da conta que a atendem, o total de unidades e onde estão. */
function pesquisadosNaConta(d, condicoes = itensDaBusca()) {
  return condicoes.map(c => {
    const achados = d.itens.map((it, i) => [it, i]).filter(([it]) => bateCondicao(it, c));
    const porSecao = new Map();
    for (const [it] of achados) porSecao.set(it.secao, (porSecao.get(it.secao) || 0) + it.qtd);
    const refinos = [...new Set(achados.map(([it]) => it.refino).filter(Boolean))].sort((a, b) => b - a);
    return { c, achados, porSecao, refinos, total: achados.reduce((s, [it]) => s + it.qtd, 0) };
  });
}

/** Marca no cabeçalho da lista a coluna da ordem atual (▾ maior primeiro, ▴ menor primeiro). */
function marcarOrdemNaTabela() {
  const o = S.filtros.ordem;
  const coluna = /^(itens|item:\d+)$/.test(o) ? 'itens' : o === 'lucro_pct' ? 'lucro_rs' : o;
  $$('.tabela th[data-ordem]').forEach(th => {
    th.classList.toggle('ordenado', th.dataset.ordem === coluna);
    th.classList.toggle('sobe', coluna === 'preco' || coluna === 'preco_item');
  });
}

// Cada número da lista tem a sua coluna e, nela, as mesmas casas decimais em todas as linhas:
// assim os algarismos e as vírgulas ficam um embaixo do outro, alinhados com o título.
/** Por unidade: 3 algarismos no menor valor da lista (0,365 → 3 casas; 12,5 → 1; de 100 para cima, nenhuma). */
function casasPorUnidade(contas) {
  const menor = Math.min(...contas.map(c => (somaBusca(c) ? c.preco / somaBusca(c) : Infinity)));
  return menor < 1 ? 3 : menor < 10 ? 2 : menor < 100 ? 1 : 0;
}
/** R$: centavos só se todos os valores da coluna forem menores que R$ 100 (a mesma regra de reais()). */
const casasReais = valores => (valores.some(v => v != null && Math.abs(v) >= 100) ? 0 : 2);

function porUnidadeHtml(c, casas) {
  const soma = somaBusca(c);
  if (soma) {  // embaixo, como no preço: o mesmo cálculo com o lance mínimo
    return `<td class="num">${decimal(c.preco / soma, casas)}<span class="sub" title="Por unidade com o lance mínimo `
      + `(${LANCE_MINIMO_PCT}% do preço)">mín. ${decimal(lanceMinimo(c.preco) / soma, casas)}</span></td>`;
  }
  return soma == null ? '<td class="num" title="Os itens desta conta ainda não foram lidos"><span class="dim">?</span></td>'
    : '<td class="num"><span class="dim">—</span></td>';
}

/** Colunas "Pesquisados": com mais de um item, a soma e depois as unidades de cada um, cada número na sua coluna. */
function pesquisadosHtml(c, busca, destaque) {
  const varios = busca.length > 1;
  if (!c.qtd_busca) {
    return '<td class="num pesq" title="Os itens desta conta ainda não foram lidos"><span class="dim">?</span></td>'
      + (varios ? '<td class="pesq"></td>'.repeat(busca.length) : '');
  }
  const item = (q, i) => `<td class="pesq item${varios ? '' : ' unico'}${String(i) === destaque ? ' on' : ''}" title="${esc(busca[i].nome)}: ${inteiro(q)}"><div>`
    + `<span>${qtdCurta(q)}</span>${busca[i].item_id != null ? `<img src="${ICONE(busca[i].item_id)}" alt="" ${SEM_IMG}>` : ''}</div></td>`;
  return (varios ? `<td class="num pesq soma" title="Soma dos itens pesquisados">${inteiro(somaBusca(c))}</td>` : '')
    + c.qtd_busca.map(item).join('');
}

/** Depois de uma atualização, só recarrega o painel se a conta aberta mudou (lida, preço, valor...). */
function recarregarDetalhesSeMudou() {
  const a = S.conta?.anuncio;
  const c = S.resultado?.contas.find(x => x.id === S.sel);
  if (!a || !c) return;
  const assinatura = x => [x.lida, x.preco, x.valor_kk, x.lucro_rs, x.ativo, x.lances, x.maior_lance].join('|');
  if (assinatura(a) !== assinatura(c)) recarregarDetalhes();
}
const buscarEmBreve = debounce(buscar, 250);

// Lances que a conta já recebeu, como o site mostra em "Fazer lance". As contas da busca na tela são
// relidas a cada 1 min (mais espaçado se forem muitas); um lance novo fica destacado por 30 min.
const LANCE_NOVO_MIN = 30;
const lanceNovo = c => !!c.lance_novo_em && Date.now() - new Date(c.lance_novo_em).getTime() < LANCE_NOVO_MIN * 60000;
function descricaoLance(c) {
  return `${c.lances} ${c.lances === 1 ? 'lance pendente' : 'lances pendentes'}, o maior de ${inteiro(c.maior_lance)} TCC. `
    + `Visto ${ha(c.lances_em)}${lanceNovo(c) ? `; lance novo ${ha(c.lance_novo_em)}` : ''}.`;
}
function lanceHtml(c) {
  if (!c.lances) return '';
  return `<span class="sub lance${lanceNovo(c) ? ' novo' : ''}" title="${descricaoLance(c)}">${lanceNovo(c) ? '▲ ' : ''}`
    + `lance ${inteiro(c.maior_lance)}${c.lances > 1 ? ` · ${c.lances}` : ''}</span>`;
}

function lucroHtml(c, casas) {
  if (c.lucro_rs == null) return '<span class="dim">—</span>';
  return `<b class="${c.lucro_rs >= 0 ? 'ok' : 'ruim'}">${reais(c.lucro_rs, true, casas)}</b><span class="sub">${pct(c.lucro_pct)}</span>`;
}
const rotuloDestaque = d => `${d.qtd > 1 ? inteiro(d.qtd) + '× ' : ''}${d.nome}${d.refino ? ' +' + d.refino : ''}`;

function desenharLista() {
  const r = S.resultado;
  if (!r) return;
  const busca = r.busca_itens || [];
  const partes = [`<b>${inteiro(r.batem)}</b> ${r.batem === 1 ? 'conta bate' : 'contas batem'}`];
  if (r.batem) partes.push(`preço mín. ${inteiro(r.preco_min)} · mediana ${inteiro(r.preco_mediana)} TCC`);
  if (r.a_confirmar) partes.push(`${inteiro(r.a_confirmar)} a confirmar`);
  if (r.nao_lidas) partes.push(`<span title="Contas cujos itens ainda não foram lidos e por isso não entram nestes filtros">${inteiro(r.nao_lidas)} ainda não lidas</span>`);
  $('#resumo').innerHTML = partes.join(' · ');
  $('#col-por-un').hidden = !busca.length;
  const colPesquisados = $('#col-pesquisados');
  colPesquisados.hidden = !busca.length;
  colPesquisados.colSpan = busca.length > 1 ? busca.length + 1 : 1;  // a soma e uma coluna por item
  colPesquisados.classList.toggle('num', busca.length === 1);  // com um item só, é uma coluna de número como as outras
  marcarOrdemNaTabela();
  const visiveis = r.contas.slice(0, S.limite);
  const assinatura = JSON.stringify([visiveis, S.sel, busca, S.filtros.ordem]);
  if (assinatura === S.assinaturaLista) return;  // nada mudou na parte visível
  S.assinaturaLista = assinatura;
  const destaque = /^item:(\d+)$/.exec(S.filtros.ordem)?.[1];  // item escolhido em "Mais <item>"
  const casas = { un: casasPorUnidade(visiveis), valor: casasReais(visiveis.map(c => c.valor_rs)),
    lucro: casasReais(visiveis.map(c => c.lucro_rs)) };
  $('#linhas').innerHTML = visiveis.map(c => `
    <tr data-id="${c.id}" class="${c.id === S.sel ? 'sel' : ''}">
      <td class="conta"><div><span class="nome">${esc(c.nome)}</span>${c.nova ? '<span class="selo nova">NOVA</span>' : ''}${c.a_confirmar ? '<span class="selo confirmar" title="A busca do site diz que tem o item; confirma quando a conta for lida">A CONFIRMAR</span>' : ''}</div>${!c.lida && !c.a_confirmar ? '<span class="sub">itens ainda não lidos</span>' : ''}</td>
      <td><img class="icone-classe" src="${CLASSE(c.ocupacao)}" alt="" ${SEM_IMG}>${esc(c.classe)} ${c.nivel}</td>
      <td class="extra">${esc(c.ceu)}</td>
      <td class="num">${inteiro(c.preco)}<span class="sub" title="Lance mínimo: ${LANCE_MINIMO_PCT}% do preço">mín. ${inteiro(lanceMinimo(c.preco))}</span>${lanceHtml(c)}</td>
      ${busca.length ? porUnidadeHtml(c, casas.un) + pesquisadosHtml(c, busca, destaque) : ''}
      <td class="num extra">${c.valor_rs != null ? reais(c.valor_rs, false, casas.valor) : '<span class="dim">—</span>'}</td>
      <td class="num lucro">${lucroHtml(c, casas.lucro)}</td>
      <td><div class="destaques">${c.destaques.map(d => `<span class="pill ${d.item_id === COSMOS ? 'laranja' : ''}">${esc(rotuloDestaque(d))}</span>`).join('')}</div></td>
    </tr>`).join('');
  const vazio = $('#lista-vazia');
  vazio.hidden = r.contas.length > 0;
  if (!vazio.hidden) {
    vazio.innerHTML = S.estado && !S.estado.ativas ? '<b>Carregando os anúncios…</b>A primeira consulta ao site leva alguns segundos.'
      : '<b>Nenhuma conta bate com esses filtros.</b>Afrouxe algum filtro ou use “Limpar”.';
  }
  const mais = $('#mostrar-mais');
  mais.hidden = r.contas.length <= S.limite;
  mais.textContent = `Mostrar mais (${inteiro(r.contas.length - S.limite)} restantes)`;
  if (!S.sel && visiveis.length) selecionar(visiveis[0].id);
}

function iniciarLista() {
  $('#linhas').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-id]');
    if (tr) selecionar(Number(tr.dataset.id));
  });
  $('.tabela thead').addEventListener('click', e => {  // clicar no título da coluna ordena por ela
    const th = e.target.closest('th[data-ordem]');
    if (!th) return;
    S.filtros.ordem = th.dataset.ordem;
    $('#f-ordem').value = S.filtros.ordem;
    marcarOrdemNaTabela();
    filtrosMudaram();
  });
  $('#mostrar-mais').addEventListener('click', () => { S.limite += 300; S.assinaturaLista = null; desenharLista(); });
  document.addEventListener('keydown', e => {
    if (S.aba !== 'contas' || !S.resultado || e.target.closest('input, select, textarea') || !$('#modal-config').hidden || !$('#modal-busca').hidden) return;
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const lista = S.resultado.contas.slice(0, S.limite);
    const i = lista.findIndex(c => c.id === S.sel);
    const novo = lista[limitar(i + (e.key === 'ArrowDown' ? 1 : -1), 0, lista.length - 1)];
    if (novo) selecionar(novo.id, true);
  });
}

// ================================================================ detalhes da conta
let detSeq = 0;
async function selecionar(id, rolar = false) {
  S.sel = id;
  $$('#linhas tr').forEach(tr => tr.classList.toggle('sel', Number(tr.dataset.id) === id));
  if (rolar) $(`#linhas tr[data-id="${id}"]`)?.scrollIntoView({ block: 'nearest' });
  fecharBalao();
  const meu = ++detSeq;
  if (!S.conta || S.conta.anuncio.id !== id) $('#detalhes').innerHTML = '<div class="det-vazio"><span>Carregando…</span></div>';
  try {
    const d = await api('GET', `/api/conta/${id}`);
    if (meu !== detSeq) return;
    const mesma = S.conta && S.conta.anuncio.id === id;
    S.conta = d;
    if (!mesma || !S.subAba) {
      S.subAba = itensDaBusca().length || algumDaBusca().length ? 'busca'
        : d.itens.some(i => i.secao === 'equipado') ? 'equipado' : 'inventario';
    }
    desenharDetalhes();
  } catch (err) {
    if (meu === detSeq) $('#detalhes').innerHTML = `<div class="det-vazio"><b>Não consegui abrir a conta</b><span>${esc(err.message)}</span></div>`;
  }
}

function recarregarDetalhes() {
  if (S.sel && $('#balao').hidden) selecionar(S.sel);
}

const ABAS_CONTA = [
  ['equipado', 'Equipado'], ['inventario', 'Mochila'], ['banco', 'Banco'], ['cartas', 'Cartas'],
  ['mascotes', 'Mascotes'], ['engastada', 'Pedras'], ['runas', 'Runas'], ['outros', 'Outros'],
];
const SECOES_PRINCIPAIS = new Set(['equipado', 'inventario', 'banco', 'cartas', 'mascotes', 'engastada', 'runas']);
const NOMES_SECAO = { missoes: 'Missões', runas: 'Runas', 'guarda-roupa': 'Guarda-roupa', materiais: 'Materiais',
  'infante celestial': 'Infante Celestial', pangu: 'PanGu', codice: 'Códice (coleção)', recompra: 'Recompra',
  transmutacao: 'Transmutação', equipado: 'equipado', inventario: 'mochila', banco: 'banco', cartas: 'cartas',
  mascotes: 'mascotes', engastada: 'engastada' };
const abaDoItem = it => (SECOES_PRINCIPAIS.has(it.secao) ? it.secao : 'outros');

function desenharDetalhes() {
  const d = S.conta;
  if (!d) {
    $('#detalhes').innerHTML = `<div class="det-vazio"><svg class="ic"><use href="#i-box"/></svg><b>Nenhuma conta selecionada</b><span>Escolha uma conta na lista para ver os itens e de onde vem o valor.</span></div>`;
    return;
  }
  const a = d.anuncio;
  const cor = a.lucro_rs == null ? '' : a.lucro_rs >= 0 ? 'ok' : 'ruim';
  const bi = S.estado?.rs_por_bi ?? 500;
  const origem = d.detalhes.length ? d.detalhes.map(x => `
      <div class="origem-linha">
        <img src="${ICONE(x.item_id)}" alt="" ${SEM_IMG}>
        <div><b>${x.qtd > 1 ? inteiro(x.qtd) + '× ' : ''}${esc(x.nome)}${x.refino_max ? ' +' + x.refino_max : ''}</b>
          <small>${x.grupo_id != null ? 'grupo · ' : ''}${x.refino_min ? `faixa refino ≥ +${x.refino_min} · ` : ''}${x.secoes.map(s => NOMES_SECAO[s] || s).join(', ')}</small></div>
        <div class="num"><b>${ouro(x.kk)}</b><small class="dim">${reais(kkPara(x.kk, bi))}</small></div>
      </div>`).join('')
    : `<div class="dim">${a.lida ? 'Nenhum item desta conta está na sua tabela de valores. Clique num item acima para dar um valor a ele.' : 'O valor aparece quando os itens forem lidos.'}</div>`;
  let conteudo;
  if (!a.lida) {
    conteudo = `<div class="aguardando"><b>Itens ainda não lidos</b>
      <span>${d.na_fila || S.estado?.lendo === a.id ? 'Esta conta está na fila de leitura.' : 'O programa ainda vai chegar nesta conta.'} Se quiser, passe ela na frente.</span>
      <div><button class="btn fantasma pequeno" id="ler-agora"><svg class="ic"><use href="#i-play"/></svg>Ler agora</button></div></div>`;
  } else {
    const contagem = {};
    for (const it of d.itens) contagem[abaDoItem(it)] = (contagem[abaDoItem(it)] || 0) + 1;
    const abas = ABAS_CONTA.filter(([k]) => contagem[k]);
    if (itensDaBusca().length || algumDaBusca().length) {  // aparece mesmo se a conta não tiver nenhum dos itens pesquisados
      abas.unshift(['busca', 'Pesquisados']);
      contagem.busca = qtdCurta([...pesquisadosNaConta(d), ...pesquisadosNaConta(d, algumDaBusca())]
        .reduce((s, p) => s + p.total, 0));
    }
    if (!abas.some(([k]) => k === S.subAba)) S.subAba = abas[0]?.[0] || 'equipado';
    conteudo = `<div class="sub-abas">${abas.map(([k, t]) =>
      `<button data-sub="${k}" class="${S.subAba === k ? 'on' : ''}">${t}<small>${contagem[k]}</small></button>`).join('')}</div>
      <div id="sub-conteudo">${conteudoSubAba(d)}</div>`;
  }
  $('#detalhes').innerHTML = `
    <div class="det-corpo">
      <div class="det-topo">
        <img src="${CLASSE(a.ocupacao)}" alt="" ${SEM_IMG}>
        <div><h2>${esc(a.nome)}${a.nova ? '<span class="selo nova">NOVA</span>' : ''}</h2>
          <small>${esc(a.classe)} · nível ${a.nivel}${a.ceu ? ' · Céu ' + esc(a.ceu) : ''} · visto ${ha(a.primeiro_visto)}</small></div>
        <button class="icone-btn pequeno" id="recolher" title="Recolher detalhes"><svg class="ic"><use href="#i-right"/></svg></button>
      </div>
      ${a.ativo ? '' : '<div class="aguardando"><b>Este anúncio saiu do ar</b><span>Provavelmente foi vendido ou removido.</span></div>'}
      <div class="dinheiro-grade">
        <div><span>Preço</span><b>${inteiro(a.preco)} TCC</b><small>= ${reais(a.preco_rs)}</small>
          <small title="Lance mínimo: o site aceita lances a partir de ${LANCE_MINIMO_PCT}% do preço">mín. ${inteiro(lanceMinimo(a.preco))}</small>
          ${!a.lances_em ? '' : a.lances ? `<small class="lance${lanceNovo(a) ? ' novo' : ''}" title="${descricaoLance(a)}">${lanceNovo(a) ? '▲ ' : ''}${a.lances} ${a.lances === 1 ? 'lance' : 'lances'} · maior: ${inteiro(a.maior_lance)}</small>`
            : `<small title="Visto ${ha(a.lances_em)}">nenhum lance</small>`}</div>
        <div><span>Valor estimado</span><b>${a.valor_rs != null ? reais(a.valor_rs) : '—'}</b><small>${a.valor_kk == null ? 'itens não lidos' : a.valor_kk === 0 ? 'nenhum item da tabela' : ouro(a.valor_kk)}</small></div>
        <div><span>Lucro</span><b class="${cor}">${reais(a.lucro_rs, true)}</b><small>${a.lucro_pct != null ? pct(a.lucro_pct) + ' do valor' : '&nbsp;'}</small></div>
      </div>
      ${conteudo}
      <div class="det-acoes">
        <button class="btn primario" id="abrir-site"><svg class="ic"><use href="#i-open"/></svg>Abrir no site</button>
        <button class="btn fantasma" id="copiar-link"><svg class="ic"><use href="#i-link"/></svg>Copiar link</button>
      </div>
      <div class="rotulo">De onde vem o valor</div>
      <div class="origem">${origem}</div>
    </div>`;
}

function slotHtml(it, i, indice) {
  const valorizado = linhaValorPara(it, indice) ? 'valorizado' : '';
  return `<button class="slot ${valorizado}" data-i="${i}">
      <img src="${ICONE(it.item_id)}" alt="" loading="lazy" onerror="this.style.opacity='.12'">
      ${it.refino ? `<span class="ref">+${it.refino}</span>` : ''}${it.qtd > 1 ? `<span class="qtd">${qtdCurta(it.qtd)}</span>` : ''}
    </button>`;
}

function conteudoSubAba(d) {
  const indice = valoresPorItem();
  if (S.subAba === 'busca') return conteudoPesquisados(d, indice);
  const itens = d.itens.map((it, i) => [it, i]).filter(([it]) => abaDoItem(it) === S.subAba);
  if (S.subAba === 'engastada') {
    const grupos = new Map();
    for (const [it, i] of itens) {
      const k = `${it.item_id}|${it.efeito}`;
      if (!grupos.has(k)) grupos.set(k, { it, i, qtd: 0 });
      grupos.get(k).qtd += it.qtd;
    }
    return `<div class="pedras">${[...grupos.values()].sort((a, b) => b.qtd - a.qtd).map(g => `
      <div class="pedra"><button class="slot ${linhaValorPara(g.it, indice) ? 'valorizado' : ''}" data-i="${g.i}"><img src="${ICONE(g.it.item_id)}" alt="" ${SEM_IMG}></button>
        <div><b>${inteiro(g.qtd)}× ${esc(g.it.nome)}</b><small>${esc(g.it.efeito)}</small></div></div>`).join('')}</div>`;
  }
  if (S.subAba === 'runas') return conteudoRunas(d, itens, indice);
  if (S.subAba === 'outros') {
    const porSecao = new Map();
    for (const par of itens) {
      if (!porSecao.has(par[0].secao)) porSecao.set(par[0].secao, []);
      porSecao.get(par[0].secao).push(par);
    }
    return [...porSecao].map(([secao, lista]) => `<div class="grupo-secao">${esc(NOMES_SECAO[secao] || secao)}</div>
      <div class="slots">${lista.map(([it, i]) => slotHtml(it, i, indice)).join('')}</div>`).join('');
  }
  return `<div class="slots">${itens.map(([it, i]) => slotHtml(it, i, indice)).join('')}</div>`;
}

/** Aba "Runas": as incorporadas nas habilidades, na ordem do site, e as guardadas, juntando as iguais.
 *  A habilidade vem no efeito ("Equipada em ΨDevorar"); contas lidas antes de o programa guardar isso aparecem todas como guardadas. */
const nivelDaRuna = it => Number(/(?:Nv\.|Nível)\s*(\d+)/i.exec(it.nome)?.[1] || 0);
const runaNegociavel = (d, it) => (d.tooltips[it.tooltip] || []).some(l => l.some(s => Array.isArray(s) && /negociável \(solto\)/i.test(s[0])));
function conteudoRunas(d, itens, indice) {
  const linha = (it, i, qtd, detalhe) => {
    const solta = runaNegociavel(d, it);
    return `<div class="pedra"><button class="slot ${linhaValorPara(it, indice) ? 'valorizado' : ''}" data-i="${i}"><img src="${ICONE(it.item_id)}" alt="" ${SEM_IMG}></button>
      <div><b>${qtd > 1 ? inteiro(qtd) + '× ' : ''}${esc(it.nome)}</b>${detalhe ? `<small>${esc(detalhe)}</small>` : ''}</div>
      ${solta ? '<span class="selo-runa" title="Item negociável (solto): pode ser vendido">negociável</span>' : ''}</div>`;
  };
  const equipadas = itens.filter(([it]) => it.efeito);
  const guardadas = new Map();
  for (const [it, i] of itens.filter(([x]) => !x.efeito)) {
    const k = `${it.item_id}|${runaNegociavel(d, it)}`;
    if (!guardadas.has(k)) guardadas.set(k, { it, i, qtd: 0 });
    guardadas.get(k).qtd += it.qtd;
  }
  const soltas = itens.filter(([it]) => runaNegociavel(d, it)).reduce((s, [it]) => s + it.qtd, 0);
  const total = itens.reduce((s, [it]) => s + it.qtd, 0);
  return `<div class="soma-busca resumo-runas">${inteiro(total)} ${total === 1 ? 'runa' : 'runas'} · <b>${inteiro(equipadas.length)}</b> nas habilidades`
    + ` · <b>${inteiro(total - equipadas.length)}</b> guardadas${soltas ? ` · <b>${inteiro(soltas)}</b> negociáveis` : ''}</div>`
    + (equipadas.length ? `<div class="grupo-secao">Nas habilidades</div><div class="pedras">${equipadas
      .map(([it, i]) => linha(it, i, it.qtd, it.efeito.replace(/^Equipada em\s*/i, ''))).join('')}</div>` : '')
    + (guardadas.size ? `<div class="grupo-secao">Guardadas</div><div class="pedras">${[...guardadas.values()]
      .sort((a, b) => nivelDaRuna(b.it) - nivelDaRuna(a.it) || a.it.nome.localeCompare(b.it.nome))
      .map(g => linha(g.it, g.i, g.qtd, '')).join('')}</div>` : '');
}

/** Aba "Pesquisados": quanto a conta tem de cada item da busca, onde estão e os próprios itens.
 *  Os do "Tem pelo menos um" vêm num grupo à parte, com os que a conta tem; os que ela não tem ficam numa linha só.
 *  O total e o preço por unidade continuam só com os do "Tem item". */
function conteudoPesquisados(d, indice) {
  const lista = pesquisadosNaConta(d);
  const algum = pesquisadosNaConta(d, algumDaBusca());
  const total = lista.reduce((s, p) => s + p.total, 0);
  const soma = total ? `<div class="soma-busca">${lista.length > 1 ? `Total: <b>${inteiro(total)}</b> · ` : ''}`
    + `${curto(d.anuncio.preco / total)} TCC por unidade · <span title="Por unidade com o lance mínimo (${LANCE_MINIMO_PCT}% do preço)">`
    + `mín. ${curto(lanceMinimo(d.anuncio.preco) / total)}</span></div>` : '';
  const falta = algum.filter(p => !p.total).map(p => nomeDaCondicao(p.c) + (p.c.refino_min ? ' ≥ +' + p.c.refino_min : ''));
  const grupo = algum.length ? `<div class="grupo-secao">Tem pelo menos um</div>${algum.filter(p => p.total).map(linhaPesquisado).join('')}`
    + (falta.length ? `<div class="dim nao-tem">${algum.length === falta.length ? 'Não tem nenhum: ' : 'Não tem: '}${esc(falta.join(', '))}</div>` : '') : '';
  const achados = new Map([...lista, ...algum].flatMap(p => p.achados).map(([it, i]) => [i, it]));  // um item pode atender a duas condições
  const slots = [...achados].sort((a, b) => a[0] - b[0]).map(([i, it]) => slotHtml(it, i, indice)).join('');
  return `<div class="origem">${lista.map(linhaPesquisado).join('')}${soma}${grupo}</div>${slots ? `<div class="slots">${slots}</div>` : ''}`;
}

const nomeDaCondicao = c => (c.grupo_id != null ? `grupo ${c.nome}` : c.item_id != null ? c.nome : `“${c.nome}” no nome`);

/** Linha da aba Pesquisados: o item da condição, onde a conta o tem e quantas unidades. */
function linhaPesquisado(p) {
  // condição de grupo ou digitada pelo nome: se ela achou um item só, mostra o nome e o ícone dele
  const unico = p.c.item_id == null && new Set(p.achados.map(([it]) => it.item_id)).size === 1 ? p.achados[0][0] : null;
  return `
    <div class="origem-linha">
      <img src="${ICONE(p.c.item_id ?? (unico || p.achados[0]?.[0])?.item_id)}" alt="" ${SEM_IMG}>
      <div><b>${esc(unico ? unico.nome : nomeDaCondicao(p.c))}${p.c.refino_min ? ' ≥ +' + p.c.refino_min : ''}</b>
        <small>${p.c.grupo_id != null && unico ? `${esc(p.c.nome)} · ` : ''}${p.total ? [...p.porSecao].map(([s, q]) => `${esc(NOMES_SECAO[s] || s)}: ${inteiro(q)}`).join(' · ')
          + (p.refinos.length ? ' · refino ' + p.refinos.map(r => '+' + r).join(', ') : '') : 'Esta conta não tem.'}</small></div>
      <div class="num"><b>${inteiro(p.total)}</b></div>
    </div>`;
}

function iniciarDetalhes() {
  const painel = $('#detalhes');
  painel.addEventListener('click', e => {
    const sub = e.target.closest('[data-sub]');
    if (sub) {
      S.subAba = sub.dataset.sub;
      $$('.sub-abas button', painel).forEach(b => b.classList.toggle('on', b === sub));
      $('#sub-conteudo').innerHTML = conteudoSubAba(S.conta);
      fecharBalao();
      return;
    }
    const slot = e.target.closest('.slot');
    if (slot) { abrirBalaoValor(S.conta.itens[Number(slot.dataset.i)], slot); return; }
    if (e.target.closest('#abrir-site')) window.open(S.conta.url, '_blank');
    if (e.target.closest('#copiar-link')) navigator.clipboard.writeText(S.conta.url).then(() => avisar('Link copiado.'));
    if (e.target.closest('#recolher')) recolherDetalhes(true);
    if (e.target.closest('#ler-agora')) {
      api('POST', `/api/ler/${S.conta.anuncio.id}`, {}).then(() => avisar('A conta vai ser lida em instantes.'));
    }
  });
  painel.addEventListener('mouseover', e => {
    const slot = e.target.closest('.slot');
    if (!slot || !S.conta) return;
    const it = S.conta.itens[Number(slot.dataset.i)];
    mostrarTooltip(it, slot);
  });
  painel.addEventListener('mouseout', e => { if (e.target.closest('.slot')) esconderTooltip(); });
  $('#abrir-detalhes').addEventListener('click', () => recolherDetalhes(false));
}

function recolherDetalhes(recolher) {
  $('#v-contas').classList.toggle('sem-detalhes', recolher);
  $('#abrir-detalhes').hidden = !recolher;
  api('PUT', '/api/config', { detalhes_recolhidos: recolher }).catch(() => {});
}

// ---------------------------------------------------------------- tooltip dos itens
const corSegura = c => (/^#[0-9a-f]{6}$/i.test(c || '') ? c : '#d8dbe3');
function mostrarTooltip(it, el) {
  const tip = $('#tooltip');
  const linhas = S.conta.tooltips[it.tooltip];
  let html;
  if (linhas) {
    html = linhas.map(l => `<div class="linha">${l.map(seg => (Array.isArray(seg)
      ? `<span style="color:${corSegura(seg[1])}">${esc(seg[0])}</span>`
      : `<img src="${ICONE(seg.i)}" alt="">`)).join('')}</div>`).join('');
  } else {
    html = `<div class="linha">${esc(it.nome)}${it.refino ? ' +' + it.refino : ''}</div>${it.efeito ? `<div style="color:#5fbab9">${esc(it.efeito)}</div>` : ''}`;
  }
  if (it.qtd > 1) html += `<div class="linha" style="color:#8b93a7">Quantidade: ${inteiro(it.qtd)}</div>`;
  const v = linhaValorPara(it);
  html += v ? `<div class="linha" style="color:#f5cd6f;margin-top:4px">${v.grupo_id != null ? `Pelo grupo ${esc(v.nome)}` : 'Na sua tabela'}: ${ouro(v.valor_kk)} por unidade</div>`
    : '<div class="linha" style="color:#768097;margin-top:4px">Clique para dar um valor a este item</div>';
  tip.innerHTML = html;
  tip.hidden = false;
  const r = el.getBoundingClientRect();
  const t = tip.getBoundingClientRect();
  let x = r.right + 10;
  if (x + t.width > innerWidth - 8) x = r.left - t.width - 10;
  const y = limitar(r.top, 8, innerHeight - t.height - 8);
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${y}px`;
}
const esconderTooltip = () => { $('#tooltip').hidden = true; };

// ---------------------------------------------------------------- balão "definir valor"
function abrirBalaoValor(it, el) {
  esconderTooltip();
  const balao = $('#balao');
  const indice = valoresPorItem();
  const vale = linhaValorPara(it, indice);
  // vale pelo grupo: o balão cadastra um valor só para este item (o do grupo se muda na tabela de valores)
  const peloGrupo = vale?.grupo_id != null ? vale : null;
  const existente = peloGrupo ? null : vale;
  const refinavel = it.refino > 0;
  const bi = S.estado?.rs_por_bi ?? 500;
  const nesta = S.conta.itens.filter(x => x.item_id === it.item_id && x.secao !== 'codice' && x.secao !== 'recompra'
    && (x.refino || 0) >= (existente?.refino_min ?? (refinavel ? it.refino : 0))).reduce((s, x) => s + x.qtd, 0) || it.qtd;
  const estado = {
    refino_min: existente ? existente.refino_min : (refinavel ? it.refino : 0),
    unidade: existente ? (existente.valor_kk >= 1000 ? 'bi' : 'kk') : (refinavel || it.secao === 'equipado' ? 'bi' : 'kk'),
    valor: '',
  };
  if (existente) estado.valor = String(estado.unidade === 'bi' ? existente.valor_kk / 1000 : existente.valor_kk).replace('.', ',');
  // o lucro novo sai sem o que a linha de agora soma; a do grupo também vale para outros itens da conta, por isso só a parte deste
  const anterior = existente ? S.conta.detalhes.find(x => x.valor_id === existente.id)
    : peloGrupo ? { kk: peloGrupo.valor_kk * nesta } : null;
  const desenhar = () => {
    const n = numeroDe(estado.valor);
    const kk = n == null ? null : estado.unidade === 'bi' ? n * 1000 : n;
    const lucro = S.conta.anuncio.lucro_rs;
    let calc = '<div><span>Digite o valor por unidade</span></div>';
    if (kk != null && kk > 0) {
      const total = kk * nesta;
      const novoLucro = lucro == null ? null : lucro - (anterior ? kkPara(anterior.kk, bi) : 0) + kkPara(total, bi);
      calc = `<div><span>Nesta conta: ${inteiro(nesta)} × ${ouro(kk)}</span><b>${ouro(total)} ≈ ${reais(kkPara(total, bi))}</b></div>`
        + (novoLucro != null ? `<div><span>Lucro da conta</span><b><span class="dim" style="font-weight:500">${reais(lucro, true)} →</span> <span class="${novoLucro >= 0 ? 'ok' : 'ruim'}">${reais(novoLucro, true)}</span></b></div>` : '');
    }
    balao.innerHTML = `
      <div class="balao-topo"><img class="icone-item" src="${ICONE(it.item_id)}" alt="" ${SEM_IMG}>
        <div><b>${esc(it.nome)}${it.refino ? ' +' + it.refino : ''}</b><small>${it.efeito ? esc(it.efeito) + ' · ' : ''}${inteiro(nesta)} ${nesta === 1 ? 'unidade' : 'unidades'} nesta conta</small></div></div>
      ${peloGrupo ? `<div class="conversao">Hoje vale <b>${ouro(peloGrupo.valor_kk)}</b> pelo grupo <b>${esc(peloGrupo.nome)}</b>${peloGrupo.refino_min ? ` (refino ≥ +${peloGrupo.refino_min})` : ''}. Salvar aqui dá um valor só para este item, que passa a valer no lugar do grupo.</div>` : ''}
      ${refinavel ? `<div class="campo"><label>Condição</label><div class="seg" data-seg="refino">
          <button data-v="0" class="${estado.refino_min === 0 ? 'on' : ''}">qualquer refino</button>
          <button data-v="${it.refino}" class="${estado.refino_min === it.refino ? 'on' : ''}">refino ≥ +${it.refino}</button></div></div>` : ''}
      <div class="campo"><label>Valor por unidade</label>
        <div class="valor-entrada"><input class="caixa" id="balao-valor" inputmode="decimal" value="${esc(estado.valor)}" placeholder="0">
          <div class="seg" data-seg="unidade"><button data-v="kk" class="${estado.unidade === 'kk' ? 'on' : ''}">kk</button><button data-v="bi" class="${estado.unidade === 'bi' ? 'on' : ''}">bi</button></div></div></div>
      <div class="calculo">${calc}</div>
      <div class="erro-form" id="balao-erro"></div>
      <div class="form-acoes"><button class="btn fantasma" data-acao="cancelar">Cancelar</button>
        <button class="btn primario" data-acao="salvar">${existente ? 'Atualizar valor' : 'Salvar na tabela'}</button></div>`;
  };
  desenhar();
  balao.hidden = false;
  posicionarBalao(balao, el);
  const entrada = () => $('#balao-valor');
  entrada().focus();
  balao.oninput = e => {
    if (e.target.id !== 'balao-valor') return;
    estado.valor = e.target.value;
    const pos = e.target.selectionStart;
    desenhar();
    entrada().focus();
    entrada().setSelectionRange(pos, pos);
  };
  balao.onclick = async e => {
    const seg = e.target.closest('[data-seg] button');
    if (seg) {
      estado[seg.parentElement.dataset.seg === 'refino' ? 'refino_min' : 'unidade'] = seg.parentElement.dataset.seg === 'refino' ? Number(seg.dataset.v) : seg.dataset.v;
      desenhar();
      entrada().focus();
      return;
    }
    const acao = e.target.closest('[data-acao]')?.dataset.acao;
    if (acao === 'cancelar') fecharBalao();
    if (acao === 'salvar') {
      const n = numeroDe(estado.valor);
      if (n == null || n <= 0) { $('#balao-erro').textContent = 'Informe um valor maior que zero.'; return; }
      const corpo = { nome: it.nome, item_id: it.item_id, refino_min: estado.refino_min, valor_kk: estado.unidade === 'bi' ? n * 1000 : n };
      try {
        const mesmaFaixa = existente && existente.refino_min === estado.refino_min;
        if (mesmaFaixa) await api('PUT', `/api/valores/${existente.id}`, corpo);
        else await api('POST', '/api/valores', corpo);
        fecharBalao();
        avisar('Valor salvo. Todas as contas foram recalculadas.');
        await carregarValores(false);
        buscar();
        selecionar(S.conta.anuncio.id);
      } catch (err) { $('#balao-erro').textContent = err.message; }
    }
  };
  balao.onkeydown = e => {
    if (e.key === 'Enter') balao.querySelector('[data-acao="salvar"]').click();
    if (e.key === 'Escape') fecharBalao();
  };
}

function posicionarBalao(balao, el) {
  const r = el.getBoundingClientRect();
  const b = balao.getBoundingClientRect();
  const x = limitar(r.left + r.width / 2 - 40, 8, innerWidth - b.width - 8);
  let y = r.bottom + 10;
  const acima = y + b.height > innerHeight - 8;
  if (acima) y = Math.max(8, r.top - b.height - 10);
  balao.classList.toggle('acima', acima);
  balao.style.left = `${x}px`;
  balao.style.top = `${y}px`;
  balao.style.setProperty('--seta', `${limitar(r.left + r.width / 2 - x - 6, 14, b.width - 26)}px`);
}
function fecharBalao() { $('#balao').hidden = true; }
document.addEventListener('mousedown', e => {
  if (!$('#balao').hidden && !e.target.closest('#balao') && !e.target.closest('.slot')) fecharBalao();
});

// ---------------------------------------------------------------- divisórias ajustáveis
function aplicarLarguras(cfg) {
  const main = $('#v-contas');
  main.style.setProperty('--w-filtros', `${cfg.largura_filtros}%`);
  main.style.setProperty('--w-detalhes', `${cfg.largura_detalhes}%`);
  main.classList.toggle('sem-detalhes', !!cfg.detalhes_recolhidos);
  $('#abrir-detalhes').hidden = !cfg.detalhes_recolhidos;
}
function iniciarDivisores() {
  $$('.divisor').forEach(div => div.addEventListener('mousedown', e => {
    e.preventDefault();
    const main = $('#v-contas');
    const caixa = main.getBoundingClientRect();
    const lado = div.dataset.lado;
    let valor = null;
    div.classList.add('arrastando');
    document.body.style.cursor = 'col-resize';
    const mover = ev => {
      if (lado === 'filtros') {
        valor = limitar((ev.clientX - caixa.left) / caixa.width * 100, 15, 45);
        main.style.setProperty('--w-filtros', `${valor}%`);
      } else {
        valor = limitar((caixa.right - ev.clientX) / caixa.width * 100, 20, 50);
        main.style.setProperty('--w-detalhes', `${valor}%`);
      }
    };
    const soltar = () => {
      removeEventListener('mousemove', mover);
      div.classList.remove('arrastando');
      document.body.style.cursor = '';
      if (valor != null) api('PUT', '/api/config', { [lado === 'filtros' ? 'largura_filtros' : 'largura_detalhes']: Math.round(valor) }).catch(() => {});
    };
    addEventListener('mousemove', mover);
    addEventListener('mouseup', soltar, { once: true });
  }));
}

// ================================================================ tabela de valores
const GRUPOS = [['grupo', 'Grupos de itens'], ['livros', 'Livros'], ['armas', 'Armas'], ['pedra', 'Pedras engastadas'],
  ['cartas', 'Cartas'], ['equip', 'Equipamentos'], ['item', 'Materiais e outros']];
const EQUIPAMENTOS = new Set(['elmos', 'peitorais', 'calcas', 'botas', 'braceletes', 'colares', 'capas', 'aneis',
  'ornamentos', 'astrolabios', 'conduites', 'equipamento']);
const grupoDe = t => (['grupo', 'livros', 'armas', 'pedra', 'cartas'].includes(t) ? t : EQUIPAMENTOS.has(t) ? 'equip' : 'item');
const ICONE_GRUPO = '<span class="icone-grupo"><svg class="ic"><use href="#i-list"/></svg></span>';

async function carregarValores(desenhar = true) {
  try {
    const r = await api('GET', '/api/valores');
    S.valores = r.valores;
    S.resumo = r.resumo;
    if (desenhar) {
      desenharValores();
      // o formulário só é desenhado na primeira vez: redesenhar apagaria o que está sendo digitado
      if (!S.formDesenhado) { S.formDesenhado = true; desenharFormValor(); }
    }
  } catch (err) { avisar(err.message, true); }
}

function desenharValores() {
  const r = S.resumo;
  const m = r?.melhor;
  $('#kpis').innerHTML = `
    <div class="kpi"><span>Valores cadastrados</span><b>${inteiro(r?.valores || 0)}</b><em>${inteiro(r?.itens || 0)} ${r?.itens === 1 ? 'item diferente' : 'itens diferentes'}</em></div>
    <div class="kpi"><span>Contas com algum item da tabela</span><b>${inteiro(r?.contas_com_item || 0)}</b><em>de ${inteiro(r?.ativas || 0)} anunciadas</em></div>
    <div class="kpi ${m && m.lucro_rs >= 0 ? 'destaque' : ''}" id="kpi-melhor" title="Ver esta conta" style="cursor:pointer"><span>Maior lucro agora</span><b class="${m && m.lucro_rs >= 0 ? 'ok' : 'ruim'}">${m ? reais(m.lucro_rs, true) : '—'}</b><em>${m ? `${esc(m.nome)} · ${esc(m.classe)} ${m.nivel} · ${inteiro(m.preco)} TCC` : 'Cadastre valores para ver'}</em></div>`;
  const filtro = norm($('#filtrar-valores').value);
  const ordem = $('#ordem-valores').value;
  const lista = S.valores.filter(v => !filtro || norm(v.nome).includes(filtro)).sort((a, b) =>
    ordem === 'nome' ? a.nome.localeCompare(b.nome, 'pt-BR') || b.refino_min - a.refino_min
      : ordem === 'contas' ? b.contas - a.contas : b.valor_kk - a.valor_kk);
  let html = '';
  for (const [g, titulo] of GRUPOS) {
    const doGrupo = lista.filter(v => grupoDe(v.tipo) === g);
    if (!doGrupo.length) continue;
    html += `<div class="grupo-valores">${titulo} <em>${doGrupo.length}</em></div>` + doGrupo.map(linhaValorHtml).join('');
  }
  $('#lista-valores').innerHTML = html || `<div class="vazio-valores"><b>${S.valores.length ? 'Nada com esse nome.' : 'Nenhum valor cadastrado ainda.'}</b>${S.valores.length ? '' : 'Comece pelo item que você mais procura: digite “cosmos” no painel ao lado.'}</div>`;
}

function linhaValorHtml(v) {
  const editando = S.form?.id === v.id ? 'editando' : '';
  const confirmando = S.confirmando === v.id;
  const laranja = ['livros', 'armas'].includes(v.tipo) ? 'ouro' : '';
  const sobre = v.grupo_id != null ? (v.grupo_apagado ? 'Grupo apagado: não vale para nenhum item' : descricaoItem(v))
    : `${TIPOS[v.tipo] || 'Item'}${v.efeito ? ' · ' + v.efeito : ''}${v.visto ? '' : ' · ainda não visto em contas'}`;
  return `<div class="linha-valor ${editando} ${confirmando ? 'confirmando' : ''}" data-id="${v.id}">
    ${v.grupo_id != null ? ICONE_GRUPO : `<img class="icone-item ${laranja}" src="${v.item_id ? ICONE(v.item_id) : ''}" alt="" ${SEM_IMG}>`}
    <div class="nome-valor"><b style="${laranja ? 'color:var(--laranja)' : ''}">${esc(v.nome)}</b>
      <small>${esc(sobre)}</small></div>
    <div>${v.refino_min ? `<span class="pill ouro">refino ≥ +${v.refino_min}</span>` : '<span class="dim">qualquer</span>'}</div>
    <div class="valor-unit"><b>${ouro(v.valor_kk)}</b><small>≈ ${reais(v.valor_rs)}</small></div>
    ${confirmando ? `<div class="confirmacao"><span class="dim" style="align-self:center">Apagar?</span><button class="btn pequeno perigo" data-acao="sim">Sim</button><button class="btn pequeno fantasma" data-acao="nao">Não</button></div>`
      : `<div class="num">${inteiro(v.contas)}</div>
    <div class="acoes-linha"><button data-acao="editar" title="Editar"><svg class="ic"><use href="#i-edit"/></svg></button><button data-acao="apagar" title="Apagar"><svg class="ic"><use href="#i-trash"/></svg></button></div>`}
  </div>`;
}

function novoForm() {
  return { id: null, item: null, refino_min: 0, unidade: 'kk', valor: '', erro: '' };
}

function desenharFormValor() {
  const f = S.form || (S.form = novoForm());
  const bi = S.estado?.rs_por_bi ?? 500;
  const it = f.item;
  const n = numeroDe(f.valor);
  const kk = n == null ? null : f.unidade === 'bi' ? n * 1000 : n;
  const refinavel = it && (it.grupo_id != null || it.no_catalogo || ['livros', 'armas'].includes(it.tipo) || EQUIPAMENTOS.has(it.tipo));
  const faixas = [0, 8, 10, 11, 12];
  if (f.refino_min && !faixas.includes(f.refino_min)) faixas.push(f.refino_min);
  let corpo;
  if (!it) {
    corpo = `<div class="seletor-item" id="form-seletor">
        <div class="entrada"><svg class="ic"><use href="#i-search"/></svg><input placeholder="Digite o nome do item…" autocomplete="off"></div>
        <div class="sugestoes"></div></div>
      <div class="conversao">Aparecem os grupos de itens, os equipamentos do site e tudo o que já foi visto nas contas: materiais, pedras e cartas.</div>
      <div class="form-grupos">
        <div><b>Um valor para vários itens</b><small>Junte itens num grupo, como as armas UP4, e dê um valor só, que vale para cada um deles.</small></div>
        <div class="form-grupos-acoes"><button class="btn fantasma pequeno" data-acao="novo-grupo" title="Cria um grupo com o nome digitado acima (ou “Novo grupo”). Adicione os itens e feche a janela: o grupo fica escolhido aqui para dar o valor."><svg class="ic"><use href="#i-plus"/></svg>Criar grupo de itens</button>
          <button class="link" data-acao="grupos"><svg class="ic"><use href="#i-list"/></svg>ver grupos${S.grupos.length ? ` (${inteiro(S.grupos.length)})` : ''}</button></div>
      </div>`;
  } else {
    const grupo = it.grupo_id != null;
    const media = it.contas ? Math.round((it.unidades || it.contas) / it.contas) : null;
    corpo = `<div class="escolhido">${grupo ? ICONE_GRUPO : `<img class="icone-item" src="${it.item_id ? ICONE(it.item_id) : ''}" alt="" ${SEM_IMG}>`}
        <div><b>${esc(it.nome)}</b><small>${esc(descricaoItem(it))}${grupo ? ' · <button class="link fino" data-acao="grupos">ver itens</button>' : ''}</small></div>
        ${f.id ? '' : '<button class="link" data-acao="trocar">trocar</button>'}</div>
      <div class="campo"><label>Condição</label>
        <div class="seg" data-seg="refino">${faixas.sort((a, b) => a - b).map(r => `<button data-v="${r}" class="${f.refino_min === r ? 'on' : ''}" ${!refinavel && r ? 'disabled' : ''}>${r ? '≥ +' + r : 'Qualquer'}</button>`).join('')}</div>
        <small class="conversao">${grupo ? 'Vale para cada item do grupo com esse refino ou mais. Um item com valor próprio na tabela usa o dele.'
          : refinavel ? 'Vale para o item com esse refino ou mais. Cadastre faixas diferentes para refinos diferentes.' : 'Este item não tem refino.'}</small></div>
      <div class="campo"><label>Valor por unidade</label>
        <div class="valor-entrada"><input class="caixa" id="form-valor-n" inputmode="decimal" value="${esc(f.valor)}" placeholder="0">
          <div class="seg" data-seg="unidade"><button data-v="kk" class="${f.unidade === 'kk' ? 'on' : ''}">kk</button><button data-v="bi" class="${f.unidade === 'bi' ? 'on' : ''}">bi</button></div></div>
        <small class="conversao">${kk ? `= ${ouro(kk)} ≈ <b>${reais(kkPara(kk, bi))}</b> por unidade` : '1 bi = 1.000 kk'}</small></div>
      ${it.contas == null ? '' : `<div class="impacto">
        <div><span>Contas que têm</span><b>${inteiro(it.contas || 0)}</b></div>
        <div><span>Média por conta</span><b>${media != null ? inteiro(media) + ' un.' : '—'}</b></div>
        <div><span>Soma média</span><b>${kk && media != null ? '≈ ' + reais(kkPara(kk * media, bi)) : '—'}</b></div>
      </div>`}
      <div class="erro-form">${esc(f.erro)}</div>
      <div class="form-acoes"><button class="btn fantasma" data-acao="cancelar">Cancelar</button>
        <button class="btn primario" data-acao="salvar"><svg class="ic"><use href="#i-${f.id ? 'edit' : 'plus'}"/></svg>${f.id ? 'Salvar alteração' : 'Adicionar à tabela'}</button></div>`;
  }
  $('#form-valor').innerHTML = `<div class="form"><div><h3>${f.id ? 'Editar valor' : 'Adicionar item'}</h3>
      <div class="sub">${f.id ? 'Mude a faixa de refino ou o valor por unidade.' : 'Cadastre uma vez e o valor vale para todas as contas.'}</div></div>${corpo}</div>`;
  if (!it) {
    const sel = seletorDeItem($('#form-seletor'), escolhido => {
      S.form = { ...novoForm(), item: escolhido, unidade: ['livros', 'armas'].includes(escolhido.tipo) || EQUIPAMENTOS.has(escolhido.tipo) ? 'bi' : 'kk' };
      desenharFormValor();
      $('#form-valor-n')?.focus();
    }, null, { titulo: q => `Cadastrar “${q}” pelo nome`, nota: 'Ainda não visto em nenhuma conta; passa a valer quando aparecer.' }, 'valor');
    if (S.aba === 'valores' && document.activeElement === document.body) sel.focar();
  }
}

function iniciarValores() {
  $('#filtrar-valores').addEventListener('input', desenharValores);
  $('#ordem-valores').addEventListener('change', desenharValores);
  $('#kpis').addEventListener('click', e => {
    if (e.target.closest('#kpi-melhor') && S.resumo?.melhor) abrirConta(S.resumo.melhor.id);
  });
  $('#lista-valores').addEventListener('click', async e => {
    const linha = e.target.closest('.linha-valor');
    const acao = e.target.closest('[data-acao]')?.dataset.acao;
    if (!linha || !acao) return;
    const v = S.valores.find(x => x.id === Number(linha.dataset.id));
    if (acao === 'editar') {
      S.form = { id: v.id, item: { item_id: v.item_id, grupo_id: v.grupo_id, itens: v.itens, nome: v.nome, tipo: v.tipo, efeito: v.efeito, contas: v.contas, unidades: v.unidades, no_catalogo: v.no_catalogo },
        refino_min: v.refino_min, unidade: v.valor_kk >= 1000 ? 'bi' : 'kk', valor: '', erro: '' };
      S.form.valor = String(S.form.unidade === 'bi' ? v.valor_kk / 1000 : v.valor_kk).replace('.', ',');
      desenharValores();
      desenharFormValor();
      $('#form-valor-n')?.focus();
    } else if (acao === 'apagar') {
      S.confirmando = v.id;
      desenharValores();
    } else if (acao === 'nao') {
      S.confirmando = null;
      desenharValores();
    } else if (acao === 'sim') {
      S.confirmando = null;
      try {
        await api('DELETE', `/api/valores/${v.id}`);
        if (S.form?.id === v.id) { S.form = novoForm(); desenharFormValor(); }
        avisar('Valor apagado.');
        carregarValores();
      } catch (err) { avisar(err.message, true); }
    }
  });
  const form = $('#form-valor');
  form.addEventListener('input', e => {
    if (e.target.id !== 'form-valor-n') return;
    S.form.valor = e.target.value;
    const pos = e.target.selectionStart;
    desenharFormValor();
    const campo = $('#form-valor-n');
    campo.focus();
    campo.setSelectionRange(pos, pos);
  });
  form.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.id === 'form-valor-n') form.querySelector('[data-acao="salvar"]')?.click();
  });
  form.addEventListener('click', async e => {
    const seg = e.target.closest('[data-seg] button');
    if (seg && !seg.disabled) {
      if (seg.parentElement.dataset.seg === 'refino') S.form.refino_min = Number(seg.dataset.v);
      else S.form.unidade = seg.dataset.v;
      desenharFormValor();
      return;
    }
    const acao = e.target.closest('[data-acao]')?.dataset.acao;
    if (acao === 'grupos') {
      abrirGrupos();
    } else if (acao === 'novo-grupo') {
      const nome = $('#form-seletor input')?.value.trim() || '';
      abrirGrupos();
      S.grupoParaValor = await novoGrupo(nome);
    } else if (acao === 'trocar' || acao === 'cancelar') {
      S.form = novoForm();
      desenharValores();
      desenharFormValor();
    } else if (acao === 'salvar') {
      const f = S.form;
      const n = numeroDe(f.valor);
      if (n == null || n <= 0) { f.erro = 'Informe um valor maior que zero.'; desenharFormValor(); return; }
      const corpo = { nome: f.item.nome, item_id: f.item.item_id, grupo_id: f.item.grupo_id, refino_min: f.refino_min, valor_kk: f.unidade === 'bi' ? n * 1000 : n };
      try {
        if (f.id) await api('PUT', `/api/valores/${f.id}`, corpo);
        else await api('POST', '/api/valores', corpo);
        avisar(f.id ? 'Valor atualizado.' : 'Item adicionado à tabela.');
        S.form = novoForm();
        await carregarValores();
        desenharFormValor();
      } catch (err) { f.erro = err.message; desenharFormValor(); }
    }
  });
}

// ================================================================ buscas e avisos
async function carregarBuscas() {
  try {
    const [b, a] = await Promise.all([api('GET', '/api/buscas'), api('GET', '/api/avisos')]);
    S.buscas = b.buscas;
    S.avisos = a.avisos;
    desenharBuscas();
  } catch (err) { avisar(err.message, true); }
}

function pillsDosFiltros(f) {
  const p = [];
  if (f.nome) p.push(`nome: ${f.nome}`);
  if (f.classes?.length) p.push(f.classes.join(', '));
  if (f.preco_min != null && f.preco_max != null) p.push(`${inteiro(f.preco_min)} a ${inteiro(f.preco_max)} TCC`);
  else if (f.preco_max != null) p.push(`até ${inteiro(f.preco_max)} TCC`);
  else if (f.preco_min != null) p.push(`a partir de ${inteiro(f.preco_min)} TCC`);
  if (f.nivel_min) p.push(`nível ≥ ${f.nivel_min}`);
  if (f.ceu) p.push(`Céu ${f.ceu}`);
  const condicao = c => `${c.qtd_min > 1 ? inteiro(c.qtd_min) + '× ' : ''}${c.grupo_id != null ? 'grupo ' : ''}${c.nome}${c.refino_min ? ' ≥ +' + c.refino_min : ''}${c.onde ? ' · ' + (ONDE.find(o => o[0] === c.onde)?.[1] || c.onde) : ''}`;
  for (const c of f.itens || []) p.push(condicao(c));
  if (f.algum?.length) p.push(`pelo menos um: ${f.algum.map(condicao).join(', ')}`);
  if (f.so_lucro) p.push('só com lucro');
  if (f.so_novas) p.push('só novas');
  return p.length ? p.map(t => `<span class="pill">${esc(t)}</span>`).join('') : '<span class="pill">todas as contas</span>';
}

function desenharBuscas() {
  const ativas = S.buscas.filter(b => b.avisar).length;
  const n = $('#n-buscas');
  n.hidden = !ativas;
  n.textContent = `${ativas} ${ativas === 1 ? 'ativa' : 'ativas'}`;
  $('#lista-buscas').innerHTML = S.buscas.length ? S.buscas.map(b => `
    <div class="busca" data-id="${b.id}">
      <div class="busca-topo"><h4>${esc(b.nome)}</h4><span class="dim" style="font-size:12px">me avisar</span>
        <button class="chave ${b.avisar ? 'on' : ''}" data-acao="avisar" role="switch" aria-checked="${b.avisar}"></button></div>
      <div class="chips">${pillsDosFiltros(b.filtros)}${b.lucro_min_rs != null ? `<span class="pill ouro">lucro ≥ ${reais(b.lucro_min_rs)}</span>` : ''}${b.lucro_min_pct != null ? `<span class="pill ouro">lucro ≥ ${b.lucro_min_pct}%</span>` : ''}</div>
      <div class="busca-rodape">
        ${S.confirmando === `b${b.id}` ? `<span>Apagar esta busca e o histórico dela?</span><span class="espaco"></span>
          <button class="btn pequeno perigo" data-acao="sim">Apagar</button><button class="btn pequeno fantasma" data-acao="nao">Não</button>`
        : `<span><b style="color:var(--tx)">${inteiro(b.batem)}</b> ${b.batem === 1 ? 'conta bate' : 'contas batem'} agora${b.ultimo_aviso ? ' · último aviso ' + ha(b.ultimo_aviso) : ''}</span>
          <span class="espaco"></span>
          <button class="btn pequeno fantasma" data-acao="abrir"><svg class="ic"><use href="#i-filter"/></svg>Abrir na lista</button>
          <button class="btn pequeno fantasma" data-acao="editar">Editar</button>
          <button class="btn pequeno fantasma" data-acao="apagar" title="Apagar"><svg class="ic"><use href="#i-trash"/></svg></button>`}
      </div>
    </div>`).join('')
    : `<div class="cartao vazio-valores"><b>Nenhuma busca salva ainda.</b>Monte os filtros na aba Contas e clique em “Salvar busca e me avisar”.</div>`;
  $('#lista-avisos').innerHTML = S.avisos.length ? S.avisos.map(a => `
    <div class="aviso-linha" data-conta="${a.anuncio_id}">
      <time>${quando(a.quando)}</time>
      <div><b>${esc(a.conta || 'Conta ' + a.anuncio_id)}${a.ativo === 0 ? ' <span class="dim" style="font-weight:400">(saiu do ar)</span>' : ''}</b>
        <small>${esc(a.busca)} · ${esc(a.classe || '')} ${a.nivel || ''} · ${esc(a.motivo)}</small></div>
      <div class="num"><b>${inteiro(a.preco)} TCC</b><small class="${a.lucro_rs >= 0 ? 'ok' : 'ruim'}" style="display:block">${a.lucro_rs != null ? reais(a.lucro_rs, true) : ''}</small></div>
    </div>`).join('')
    : '<div class="vazio-valores"><b>Nenhum aviso ainda.</b>Quando uma conta nova bater com uma busca salva, ela aparece aqui.</div>';
}

function iniciarBuscas() {
  $('#lista-buscas').addEventListener('click', async e => {
    const card = e.target.closest('.busca');
    const acao = e.target.closest('[data-acao]')?.dataset.acao;
    if (!card || !acao) return;
    const b = S.buscas.find(x => x.id === Number(card.dataset.id));
    try {
      if (acao === 'avisar') {
        await api('PUT', `/api/buscas/${b.id}`, { ...b, avisar: !b.avisar });
        carregarBuscas();
      } else if (acao === 'abrir') {
        S.filtros = { ...structuredClone(FILTROS_PADRAO), ...structuredClone(b.filtros) };
        S.buscaAtual = { id: b.id, nome: b.nome };
        guardar('buscaAtual', S.buscaAtual);
        preencherFiltros();
        filtrosMudaram();
        trocarAba('contas');
      } else if (acao === 'editar') {
        abrirModalBusca(b);
      } else if (acao === 'apagar') {
        S.confirmando = `b${b.id}`;
        desenharBuscas();
      } else if (acao === 'nao') {
        S.confirmando = null;
        desenharBuscas();
      } else if (acao === 'sim') {
        S.confirmando = null;
        await api('DELETE', `/api/buscas/${b.id}`);
        if (S.buscaAtual?.id === b.id) { S.buscaAtual = null; guardar('buscaAtual', null); }
        avisar('Busca apagada.');
        carregarBuscas();
      }
    } catch (err) { avisar(err.message, true); }
  });
  $('#lista-avisos').addEventListener('click', e => {
    const linha = e.target.closest('[data-conta]');
    if (linha) abrirConta(Number(linha.dataset.conta));
  });
}

function abrirConta(id) {
  trocarAba('contas');
  selecionar(id, true);
}

// ---------------------------------------------------------------- janela "salvar busca"
let buscaEditando = null;
function abrirModalBusca(existente) {
  buscaEditando = existente && existente.id ? existente : null;
  const f = buscaEditando ? buscaEditando.filtros : S.filtros;
  const atual = !buscaEditando && S.buscaAtual;
  $('#t-busca').textContent = buscaEditando ? 'Editar busca' : 'Salvar busca';
  $('#b-nome').value = buscaEditando ? buscaEditando.nome : atual ? atual.nome : sugestaoDeNome(f);
  $('#b-resumo').innerHTML = pillsDosFiltros(f);
  $('#b-avisar').classList.toggle('on', buscaEditando ? buscaEditando.avisar : true);
  $('#b-preco-max').value = f.preco_max != null ? inteiro(f.preco_max) : '';
  mostrarPrecoDaJanela();
  $('#b-lucro-rs').value = buscaEditando?.lucro_min_rs ?? '';
  $('#b-lucro-pct').value = buscaEditando?.lucro_min_pct ?? '';
  $('#b-salvar').textContent = buscaEditando ? 'Salvar' : atual ? `Atualizar “${atual.nome}”` : 'Salvar busca';
  $('#modal-busca').hidden = false;
  $('#b-nome').select();
}
function sugestaoDeNome(f) {
  const partes = [];
  const nome = c => c.nome + (c.refino_min ? ' +' + c.refino_min : '');
  if (f.itens?.length) partes.push(f.itens.map(nome).join(' e '));
  if (f.algum?.length) partes.push(f.algum.map(nome).join(' ou '));
  if (f.classes?.length) partes.push(f.classes.join('/'));
  if (f.preco_max != null) partes.push(`até ${inteiro(f.preco_max)} TCC`);
  return partes.join(' · ').slice(0, 60) || 'Minha busca';
}
/** O preço da janela é o preço máximo da própria busca: vale para o aviso e para a lista da busca. */
const filtrosDaJanela = () => ({ ...(buscaEditando ? buscaEditando.filtros : S.filtros), preco_max: precoDe($('#b-preco-max').value) });
function mostrarPrecoDaJanela() {
  const f = filtrosDaJanela();
  const invalido = f.preco_max == null && $('#b-preco-max').value.trim() !== '';
  const conversao = $('#b-preco-rs');
  conversao.textContent = invalido ? 'Use um número, como 5000 ou 5k.'
    : f.preco_max != null ? `= ${reais(f.preco_max * (S.estado?.rs_por_tcc ?? 1))}` : '';
  conversao.classList.toggle('ruim', invalido);
  $('#b-resumo').innerHTML = pillsDosFiltros(f);
}
function iniciarModalBusca() {
  $('#b-avisar').addEventListener('click', e => e.currentTarget.classList.toggle('on'));
  $('#b-preco-max').addEventListener('input', mostrarPrecoDaJanela);
  $('#b-salvar').addEventListener('click', async () => {
    const filtros = filtrosDaJanela();
    if (filtros.preco_max == null && $('#b-preco-max').value.trim()) { avisar('Preço inválido. Use um número, como 5000 ou 5k.', true); return; }
    if (filtros.preco_max != null && filtros.preco_min != null && filtros.preco_min > filtros.preco_max) {
      avisar(`O preço mínimo dos filtros (${inteiro(filtros.preco_min)} TCC) é maior que esse preço.`, true);
      return;
    }
    const corpo = {
      nome: $('#b-nome').value.trim(),
      filtros,
      avisar: $('#b-avisar').classList.contains('on'),
      lucro_min_rs: numeroDe($('#b-lucro-rs').value),
      lucro_min_pct: numeroDe($('#b-lucro-pct').value),
    };
    try {
      const id = buscaEditando?.id ?? S.buscaAtual?.id;
      if (id) await api('PUT', `/api/buscas/${id}`, corpo);
      const novo = id ? { id } : await api('POST', '/api/buscas', corpo);
      if (!buscaEditando) { S.buscaAtual = { id: novo.id, nome: corpo.nome }; guardar('buscaAtual', S.buscaAtual); }
      // a busca aberta na lista fica com o mesmo preço, para o próximo "Atualizar" não desfazer o que foi salvo aqui
      if ((!buscaEditando || buscaEditando.id === S.buscaAtual?.id) && S.filtros.preco_max !== filtros.preco_max) {
        S.filtros.preco_max = filtros.preco_max;
        preencherFiltros();
        filtrosMudaram();
      }
      $('#modal-busca').hidden = true;
      avisar(corpo.avisar ? 'Busca salva. Você vai ser avisado quando aparecer uma conta nova que bata.' : 'Busca salva.');
      carregarBuscas();
    } catch (err) {
      if (/não encontrad/i.test(err.message) && S.buscaAtual) { S.buscaAtual = null; guardar('buscaAtual', null); }
      avisar(err.message, true);
    }
  });
}

// ================================================================ grupos de itens
// Um grupo junta itens buscados juntos, como as armas de um rank, que têm um nome em cada classe.
// Na busca ele vira uma condição só, que vale para qualquer item dele.
async function carregarGrupos() {
  try {
    S.grupos = (await api('GET', '/api/grupos')).grupos;
    S.gruposCarregados = true;
  } catch (err) { avisar(err.message, true); }
  desenharCondicoes();  // os cartões de grupo mostram o nome e o número de itens de agora
  if (!$('#modal-grupos').hidden) desenharGrupos();
}

/** focar: { id, campo: 'nome' | 'item' } põe o cursor no nome ou na caixa de adicionar desse grupo. */
function desenharGrupos(focar = null) {
  const lista = $('#lista-grupos');
  lista.innerHTML = S.grupos.length ? S.grupos.map(g => `
    <div class="grupo" data-id="${g.id}">
      <div class="grupo-topo">
        <span class="icone-grupo"><svg class="ic"><use href="#i-list"/></svg></span>
        <input class="caixa" data-campo="nome" value="${esc(g.nome)}" maxlength="60" title="Nome do grupo" autocomplete="off">
        <span class="dim">${inteiro(g.itens.length)} ${g.itens.length === 1 ? 'item' : 'itens'}</span>
        ${S.confirmando === `g${g.id}` ? `<span>Apagar o grupo?</span>
          <button class="btn pequeno perigo" data-acao="sim">Apagar</button><button class="btn pequeno fantasma" data-acao="nao">Não</button>`
        : '<button class="icone-btn sem-borda pequeno" data-acao="apagar" title="Apagar o grupo"><svg class="ic"><use href="#i-trash"/></svg></button>'}
      </div>
      <div class="grupo-itens">${g.itens.map(it => `<span class="pill" title="${esc(it.nome)}"><img src="${ICONE(it.item_id)}" alt="" ${SEM_IMG}>${esc(it.nome)}<button data-acao="tirar" data-item="${it.item_id}" title="Tirar do grupo"><svg class="ic"><use href="#i-x"/></svg></button></span>`).join('')
        || '<span class="dim">Nenhum item ainda: adicione abaixo.</span>'}</div>
      <div class="seletor-item"><div class="entrada"><svg class="ic"><use href="#i-search"/></svg><input placeholder="Adicionar item ao grupo…" autocomplete="off"></div><div class="sugestoes"></div></div>
    </div>`).join('')
    : '<div class="vazio-valores"><b>Nenhum grupo ainda.</b>Crie um com “Novo grupo”.</div>';
  for (const card of $$('.grupo', lista)) {
    const g = S.grupos.find(x => x.id === Number(card.dataset.id));
    seletorDeItem($('.seletor-item', card), item => salvarGrupo(g, { itens: [...g.itens, { item_id: item.item_id, nome: item.nome }] }, 'item'));
  }
  if (focar) $(`.grupo[data-id="${focar.id}"] ${focar.campo === 'nome' ? 'input[data-campo="nome"]' : '.seletor-item input'}`, lista)?.focus();
}

/** Grava o grupo com as mudanças; focar ('nome' | 'item') volta o cursor para ele, para adicionar o próximo item. */
async function salvarGrupo(g, mudancas, focar = null) {
  try {
    await api('PUT', `/api/grupos/${g.id}`, { nome: g.nome, itens: g.itens, ...mudancas });
  } catch (err) { avisar(err.message, true); }
  await carregarGrupos();
  if (focar) desenharGrupos({ id: g.id, campo: focar });
}

function abrirGrupos() {
  S.confirmando = null;
  S.grupoParaValor = null;
  $('#modal-grupos').hidden = false;
  desenharGrupos();
}

/** Cria um grupo vazio e o mostra na janela: com o nome digitado, o cursor vai para "adicionar item"; sem ele,
 *  para o nome ("Novo grupo", já selecionado para trocar). Devolve o id, ou null se não deu. */
async function novoGrupo(nomeBase = '') {
  let nome = nomeBase || 'Novo grupo';
  for (let n = 2; S.grupos.some(g => g.nome === nome); n++) nome = `${nomeBase || 'Novo grupo'} ${n}`;
  try {
    const { id } = await api('POST', '/api/grupos', { nome, itens: [] });
    await carregarGrupos();
    desenharGrupos({ id, campo: nomeBase ? 'item' : 'nome' });
    if (!nomeBase) $(`#lista-grupos .grupo[data-id="${id}"] input[data-campo="nome"]`)?.select();
    return id;
  } catch (err) { avisar(err.message, true); return null; }
}

/** Grupo criado pela Tabela de valores: ao fechar a janela, ele já fica escolhido no "Adicionar item", para dar o valor. */
function grupoProntoParaValor() {
  const g = S.grupos.find(x => x.id === S.grupoParaValor);
  S.grupoParaValor = null;
  if (!g || !g.itens.length || S.aba !== 'valores' || S.form?.item) return;
  S.form = { ...novoForm(), item: { grupo_id: g.id, nome: g.nome, itens: g.itens } };
  desenharFormValor();
  $('#form-valor-n')?.focus();
}

function iniciarGrupos() {
  const modal = $('#modal-grupos');
  const lista = $('#lista-grupos');
  $('#abrir-grupos').addEventListener('click', abrirGrupos);
  $('#novo-grupo').addEventListener('click', () => novoGrupo());
  new MutationObserver(() => { if (modal.hidden && S.grupoParaValor) grupoProntoParaValor(); })
    .observe(modal, { attributes: true, attributeFilter: ['hidden'] });
  lista.addEventListener('change', e => {
    if (e.target.dataset.campo !== 'nome') return;
    const g = S.grupos.find(x => x.id === Number(e.target.closest('.grupo').dataset.id));
    salvarGrupo(g, { nome: e.target.value.trim() });
  });
  lista.addEventListener('click', async e => {
    const acao = e.target.closest('[data-acao]')?.dataset.acao;
    if (!acao) return;
    const g = S.grupos.find(x => x.id === Number(e.target.closest('.grupo').dataset.id));
    if (acao === 'tirar') {
      const item = Number(e.target.closest('[data-item]').dataset.item);
      salvarGrupo(g, { itens: g.itens.filter(it => it.item_id !== item) });
    } else if (acao === 'apagar' || acao === 'nao') {
      S.confirmando = acao === 'apagar' ? `g${g.id}` : null;
      desenharGrupos();
    } else if (acao === 'sim') {
      S.confirmando = null;
      try {
        await api('DELETE', `/api/grupos/${g.id}`);
        avisar('Grupo apagado.');
      } catch (err) { avisar(err.message, true); }
      carregarGrupos();
    }
  });
}

// ================================================================ configurações
async function abrirConfig(foco) {
  try {
    const cfg = await api('GET', '/api/config');
    S.config = cfg;
    const modal = $('#modal-config');
    $$('[data-campo]', modal).forEach(el => {
      const v = cfg[el.dataset.campo];
      if (el.classList.contains('passo')) desenharPasso(el, v);
      else if (el.classList.contains('chave')) el.classList.toggle('on', !!v);
      else if (el.closest('.dinheiro')) el.value = decimal(v);
      else el.value = v ?? '';
    });
    $$('details', modal).forEach(d => { d.open = !!(d.querySelector('input').value); });
    modal.hidden = false;
    const alvo = foco && modal.querySelector(`[data-campo="${foco}"]`);
    if (alvo) { alvo.focus(); alvo.select?.(); }
  } catch (err) { avisar(err.message, true); }
}
function desenharPasso(el, v) {
  el.dataset.valor = v;
  el.innerHTML = `<button data-d="-1" title="Diminuir"><svg class="ic"><use href="#i-minus"/></svg></button>
    <input value="${v}${el.dataset.sufixo || ''}" inputmode="numeric"><button data-d="1" title="Aumentar"><svg class="ic"><use href="#i-plus"/></svg></button>`;
}
function valoresDaConfig() {
  const modal = $('#modal-config');
  const cfg = {};
  $$('[data-campo]', modal).forEach(el => {
    const campo = el.dataset.campo;
    if (el.classList.contains('passo')) cfg[campo] = Number(el.dataset.valor);
    else if (el.classList.contains('chave')) cfg[campo] = el.classList.contains('on');
    else if (el.closest('.dinheiro')) cfg[campo] = numeroDe(el.value);
    else cfg[campo] = el.value.trim();
  });
  return cfg;
}
// ================================================================ sincronizar com o GitHub
// Manda o que mudou aqui no meus-dados.json (tabela, buscas, grupos e configurações) e traz o que mudou no
// outro PC, pelo git da pasta do programa (mercado/sincronia.py).
function iniciarSincronia() {
  const botao = $('#sincronizar');
  botao.addEventListener('click', async () => {
    botao.disabled = true;
    $('span', botao).textContent = 'Sincronizando…';
    try {
      const r = await api('POST', '/api/sincronizar', {});
      const partes = [r.trouxe.length ? `chegou do outro PC: ${r.trouxe.join(', ')}` : '',
        r.mandou ? 'as mudanças daqui foram enviadas' : ''].filter(Boolean);
      avisar(partes.length ? `Sincronizado: ${partes.join('; ')}.` : 'Tudo em dia: nada novo para mandar ou trazer.');
      if (r.codigo_novo) avisar('Sincronizado, e chegou uma versão nova do programa: feche e abra de novo para usar.', false, 12000);
      await Promise.all([carregarGrupos(), carregarValores(false), carregarBuscas(), atualizarEstado()]);
    } catch (err) {
      avisar(err.message, true, 12000);
    }
    botao.disabled = false;
    $('span', botao).textContent = 'Sincronizar';
  });
}

function iniciarConfig() {
  const modal = $('#modal-config');
  $('#abrir-config').addEventListener('click', () => abrirConfig());
  $$('.cotacao').forEach(b => b.addEventListener('click', () => abrirConfig(b.dataset.config)));
  modal.addEventListener('click', e => {
    const passo = e.target.closest('.passo button');
    if (passo) {
      const el = passo.closest('.passo');
      const v = limitar(Number(el.dataset.valor) + Number(passo.dataset.d) * Number(el.dataset.passo), Number(el.dataset.min), Number(el.dataset.max));
      desenharPasso(el, v);
      return;
    }
    const chave = e.target.closest('.chave');
    if (chave) chave.classList.toggle('on');
  });
  modal.addEventListener('change', e => {
    const el = e.target.closest('.passo');
    if (!el) return;
    const n = numeroDe(e.target.value.replace(/[^\d.,]/g, ''));
    desenharPasso(el, limitar(Math.round(n ?? Number(el.dataset.valor)), Number(el.dataset.min), Number(el.dataset.max)));
  });
  $('#salvar-config').addEventListener('click', async () => {
    try {
      const cfg = await api('PUT', '/api/config', valoresDaConfig());
      S.config = cfg;
      modal.hidden = true;
      avisar('Configurações salvas.');
      atualizarEstado();
      recarregarVista();
    } catch (err) { avisar(err.message, true); }
  });
  $('#testar-aviso').addEventListener('click', async e => {
    const botao = e.currentTarget;
    botao.disabled = true;
    botao.textContent = 'Enviando…';
    try {
      const r = await api('POST', '/api/testar-aviso', valoresDaConfig());
      if (r.erros.length) avisar(`Alguns avisos falharam: ${r.erros.join(' · ')}`, true);
      else avisar('Aviso de teste enviado.');
    } catch (err) { avisar(err.message, true); }
    botao.disabled = false;
    botao.textContent = 'Testar avisos';
  });
}

// ================================================================ início
function iniciarJanelas() {
  $$('.fundo-modal').forEach(m => m.addEventListener('mousedown', e => {
    if (e.target === m || e.target.closest('[data-fechar]')) m.hidden = true;
  }));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    $$('.fundo-modal').forEach(m => { m.hidden = true; });
    fecharBalao();
    esconderTooltip();
  });
  $$('.aba').forEach(b => b.addEventListener('click', () => trocarAba(b.dataset.aba)));
  $('#rolagem').addEventListener('scroll', esconderTooltip, { passive: true });
  $('#detalhes').addEventListener('scroll', () => { esconderTooltip(); fecharBalao(); }, { passive: true });
}

async function iniciar() {
  iniciarJanelas();
  iniciarFiltros();
  iniciarLista();
  iniciarDetalhes();
  iniciarDivisores();
  iniciarValores();
  iniciarBuscas();
  iniciarModalBusca();
  iniciarGrupos();
  iniciarSincronia();
  iniciarConfig();
  preencherFiltros();
  desenharDetalhes();
  try {
    S.config = await api('GET', '/api/config');
    aplicarLarguras(S.config);
  } catch { /* segue com o padrão */ }
  await carregarGrupos();
  await atualizarEstado();
  await carregarValores(false);
  carregarBuscas();
  const aba = location.hash.slice(1);
  if (['valores', 'buscas'].includes(aba)) trocarAba(aba);
  setInterval(atualizarEstado, 3000);
  const sinal = () => api('POST', '/api/sinal', {}).catch(() => {});
  sinal();
  setInterval(sinal, 15000);
}
iniciar();
