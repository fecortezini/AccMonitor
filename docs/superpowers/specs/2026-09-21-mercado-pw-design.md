# Mercado PW: desenho do programa

**Data:** 2026-09-21
**Status:** aprovado, em desenvolvimento
**Mockups aprovados:** `docs/mockups/contas-layout-a-v2.html` e `docs/mockups/tabela-valores-v2.html`

## 1. Objetivo

Um programa de PC para acompanhar o Marketplace The Classic PW 1.8.7 (`https://marketplace.theclassic.games/pw187`) sem abrir o site. Ele:

1. lista todas as contas anunciadas, com busca avançada por classe, preço, nível, Céu, nome e itens (refino, quantidade, onde estão);
2. avalia cada conta pela **tabela de valores** do usuário, somando os itens da conta que estão na tabela, e compara com o preço;
3. ordena pelas maiores barganhas;
4. avisa quando aparece uma conta nova, ou que baixou de preço, que bate com uma busca salva.

Ele substitui o `helper.py`, que continua na pasta mas deixa de ser necessário.

### Critérios de sucesso

- Abre com dois cliques, numa janela própria, sem abas nem barra de endereço.
- Os filtros de classe, preço, nível, nome e Céu respondem na hora.
- O filtro por equipamento (ex.: Cosmos +10) responde em cerca de 0,5 s, mesmo antes de o programa ter lido as contas.
- O valor e o lucro de todas as contas ficam disponíveis depois da primeira carga (cerca de 2 h, uma única vez). Depois disso, qualquer busca é instantânea.
- Uma conta nova é analisada, e avisada se bater com uma busca salva, em até "intervalo de consulta + ~5 s".

### Fora do escopo

- Comprar automaticamente.
- Continuar rodando com a janela fechada (ícone perto do relógio).
- Histórico de vendas ou "preço justo" calculado pelo mercado.
- Outros servidores ou jogos.
- Ouro carregado pelo personagem: os vendedores retiram antes de anunciar.

## 2. De onde vêm os dados

| Fonte | Endereço | O que traz |
|---|---|---|
| Lista | `GET /pw187` (HTML ~3,2 MB; ~120 KB compactado) | Um card por anúncio: `data-roleid`, `data-price` (TCC), `data-level`, `data-occupation`, nome, classe, Céu |
| Conta | `GET /pw187/details/{id}` (HTML ~1,5 MB) | Todos os itens por aba. Cada item traz `data-item` (JSON com `id`, `name`, `count`, `refine_level`) e o tooltip em `data-pw187-tooltip`. As pedras engastadas aparecem no tooltip como `<img …/{idPedra}.png> Nome Efeito` |
| Catálogo | `GET /pw187/advanced_item_list` (JSON) | 1.408 equipamentos filtráveis: `item_id`, `item_name`, `icon_url`, `mask_groups` |
| Busca do site | `GET /pw187/advanced_filter?…` (JSON, ~0,5 s) | `{roleids:[…]}`. Parâmetros: `item_ids` (vários = OU), `g17_book_min` (Cosmos, id 72573), `class_ids`, `price_min`, `price_max`, `level_min`, `refine_level` + `refine_min_quantity`. Só cobre equipamentos e nunca devolve quantidade |
| Ícones | `pwdatabase.theclassic.games/assets/img/vtheclassicpw187/{id}.png` e `theclassic.games/assets/img/pw_roles/occu_{n}.png` | Imagens dos itens e das classes |

**Identidade de um item:** o `item_id` do jogo. Ele vale para itens comuns, equipamentos do catálogo e pedras engastadas (pelo ícone). O nome serve só para exibir e buscar.

No caso das pedras engastadas, o nome exibido é o texto do tooltip antes do efeito. Por exemplo, "Pedra do Demônio Nível de Ataque +3" vira o nome "Pedra do Demônio", com o efeito "Nível de Ataque +3" guardado à parte.

## 3. Arquitetura

Um único processo Python usando só a biblioteca padrão (nada para instalar). A interface é HTML/CSS/JS servida localmente e aberta no Edge em modo aplicativo, que aparece como uma janela própria.

```
pw-market-helper/
  Mercado PW.bat        dois cliques: inicia o programa sem console
  mercado/
    __main__.py         sobe o banco, o servidor, o coletor e abre a janela
    site.py             leitura da lista, da conta, do catálogo e da busca do site
    banco.py            SQLite: esquema e consultas
    valor.py            cálculo de valor, lucro e %
    coletor.py          consulta periódica e fila de contas a ler
    avisos.py           Windows, bipes, navegador, Telegram, Discord
    servidor.py         servidor local (127.0.0.1) com API JSON e os arquivos da interface
    ui/                 index.html, app.css, app.js (JS puro, sem bibliotecas externas)
  mercado.db            criado na primeira execução; é de cada PC
  meus-dados.json       tabela de valores, buscas e configurações; vai pelo git para os outros PCs (seção 3.3)
  tests/                testes com páginas reais salvas
```

`site.py` e `avisos.py` reaproveitam o código já testado do `helper.py` (leitura dos cards, leitura dos itens com seção, notificação do Windows, bipes, Telegram, Discord).

### 3.1 Janela

`__main__.py` escolhe uma porta livre em 127.0.0.1 e abre:

`msedge --app=http://127.0.0.1:{porta}/ --user-data-dir=<pasta>/.janela --no-first-run --window-size=1440,900`

O perfil separado faz a janela ser independente do Edge do usuário. O programa segue aberto enquanto esse Edge tiver uma janela, mesmo minimizada ou atrás de outra, e encerra quando ela é fechada. Se o Edge não for encontrado, abre o navegador padrão e encerra depois de 3 min sem o sinal que a página envia a cada 15 s (2 min se ela nunca abrir).

Se o programa já estiver aberto, um segundo clique só abre outra janela para a instância que já está rodando.

### 3.2 Banco local (SQLite, `mercado.db`)

| Tabela | Campos principais |
|---|---|
| `anuncios` | `id` (roleid), `nome`, `classe`, `ocupacao`, `nivel`, `ceu`, `preco`, `primeiro_visto`, `ultimo_visto`, `ativo`, `itens_lidos_em`, `valor_kk`, `lucro_rs`, `lucro_pct` |
| `itens` | `anuncio_id`, `secao` (equipado, mochila, banco, cartas, runas, mascotes, códice, engastada…), `item_id`, `nome`, `refino`, `qtd`, `tooltip` (segmentos de texto com cor, já limpos) |
| `catalogo` | `item_id`, `nome`, `grupo` (livros, armas, cartas…), `icone` |
| `valores` | `id`, `item_id`, `nome`, `refino_min` (0 = qualquer), `valor_kk` (por unidade), datas |
| `buscas` | `id`, `nome`, `filtros` (JSON), `avisar`, `lucro_min_rs`, `lucro_min_pct`, datas |
| `avisos` | `id`, `busca_id`, `anuncio_id`, `preco`, `lucro_rs`, `quando` |
| `config` | chave e valor (lista na seção 6) |

Índices: `itens(anuncio_id)`, `itens(item_id)`, `anuncios(ativo, preco)`.

### 3.3 Mais de um PC: `meus-dados.json` *(23/09)*

O programa é usado em mais de um PC, e refazer a tabela de valores, as buscas e as configurações em cada um dava trabalho. O `mercado.db` inteiro não pode ir para o git: tem ~110 MB depois da primeira carga (o GitHub recusa arquivos acima de 100 MB) e muda a cada consulta. Por isso, os dados se dividem em dois:

- **Seus dados** (`valores`, `buscas` e as configurações): ficam também no `meus-dados.json`, na pasta do programa e no git. É um arquivo de texto com uma linha por valor e por busca, para o git mostrar e juntar as mudanças.
- **O resto é de cada PC:** anúncios, itens, tooltips, catálogo e o histórico de avisos. Num PC novo, o coletor lê as contas sozinho, começando pelas que têm itens da tabela (seção 4).

**Ficam só em cada PC:** as larguras dos painéis (a tela pode ser outra) e o Telegram e o Discord, para os tokens não irem para o git.

**Sincronização** (`Banco.sincronizar`):
- Toda mudança nos seus dados grava o arquivo. Antes de gravar, o programa traz o que mudou nele, para não passar por cima de um `git pull`.
- O arquivo é conferido ao abrir o programa e a cada consulta de estado da interface (3 s). Só a data e o tamanho são comparados, e o conteúdo só é lido quando eles mudam.
- O banco guarda o hash do que foi sincronizado por último, e é ele que diz o que mudou:
  - só o arquivo mudou (`git pull`): o arquivo vai para o banco, e as contas são recalculadas;
  - só o banco mudou (a gravação tinha falhado): o banco vai para o arquivo;
  - os dois mudaram, ou é a primeira vez de um PC que já tinha dados: vale o arquivo, e o que o banco tinha fica em `meus-dados.anterior.json`.
- **Sem arquivo** (primeira vez, ou ele foi apagado): o arquivo é criado com os dados do banco.
- **Arquivo com erro ou conflito do git:** nada é gravado por cima dele. A faixa do topo avisa, e as mudanças nos seus dados são recusadas até ele ser resolvido ou apagado.

## 4. Coletor: como os dados chegam

**Consulta da lista** (a cada `intervalo_s`, padrão 60 s, mínimo 30 s):

1. Baixa e lê a lista.
2. Se vier com menos da metade dos anúncios da consulta anterior, trata como falha e ignora a rodada.
3. Atualiza `anuncios`. Anúncios que sumiram ficam com `ativo = 0`.
4. Anúncios novos, reativados ou com preço menor entram na fila com **prioridade alta**.

**Fila de leitura** (uma conta por vez, com `pausa_s` entre páginas, padrão 2 s, mínimo 1 s). Para cada conta, lê os itens, grava, recalcula o valor e confere as buscas com aviso ligado (seção 7). *Depois (22/09):* com `leituras_simultaneas` em 2, as duas próximas contas são baixadas ao mesmo tempo, e a pausa vem depois das duas. Se o site responder 403, 429 ou 503, a opção volta sozinha para 1.

**Lances** *(25/09)*. A página da conta traz, no botão "Fazer lance", os lances pendentes e o maior (`data-bid-pending`, `data-bid-highest`), sem login. Não há endereço mais leve: o único outro é `/lances/criar`, que dá lance e exige login.
- **Junto com os itens:** quando uma conta é lida, os lances dela vêm da mesma página.
- **Sem contas para ler:** o coletor relê só os lances, com a mesma pausa entre páginas:
  - a conta aberta nos detalhes e as 50 primeiras da busca na tela, cada uma a cada 1 min, ou mais espaçado se forem muitas (no máximo 10 páginas por minuto);
  - as demais contas já lidas, uma a cada 30 s, a de lances vistos há mais tempo;
  - uma página que falha só é tentada de novo 5 min depois.
- **Custo:** cada página tem ~116 KB compactada. Com o programa aberto, são cerca de 5 a 12 páginas por minuto.
- **Lance novo:** maior valor ou mais lances do que da última vez (a primeira leitura é a base). Ele marca `lance_novo_em`, e a lista o destaca por 30 min.

A fila é preenchida nesta ordem:

1. **Alta:** contas novas ou que baixaram de preço.
2. **Média:** contas que a busca do site diz terem algum equipamento da tabela de valores ou das buscas salvas. As contas com Cosmos ficam prontas no primeiro minuto.
3. **Baixa:** as demais ainda não lidas, das mais baratas para as mais caras.

Uma conta só é relida quando o preço muda ou quando é anunciada de novo.

**Tempo da primeira carga:** medido no site real, cada conta leva ~4,7 s (pausa de 2 s + download e leitura), então ~1.500 contas ≈ 2 h com a pausa padrão. O progresso aparece na barra do topo ("itens lidos 812/1.509"). A carga só avança com o programa aberto, e o que já foi lido fica salvo.

## 5. Valor de uma conta

- **A tabela é global.** Cada valor é cadastrado uma única vez e vale para todas as contas, atuais e futuras. Depois só precisa editar.
- **Uma linha da tabela** tem `item_id`, `refino_min` e `valor_kk` por unidade. O usuário digita em kk ou bi, e 1 bi = 1.000 kk.
- **Linha cadastrada só pelo nome** (item ainda não visto): casa pelo nome normalizado, sem diferenciar maiúsculas e acentos. Quando o item aparece numa conta, o `item_id` é preenchido automaticamente.
- **Faixas de refino:** para cada item da conta, vale a linha do mesmo `item_id` com o maior `refino_min` ≤ refino do item. Um Cosmos +12 com as faixas +10 = 3 bi e +12 = 6 bi conta 6 bi, não 9.
- **Quantidade:** itens empilháveis contam `qtd × valor`. Cada pedra engastada conta como uma unidade.
- **Onde o item está não importa:** conta equipado, na mochila, no banco, engastado etc.
- **Conversão:**
  - `valor_rs = valor_kk / 1000 × rs_por_bi`
  - `preco_rs = preco_tcc × rs_por_tcc`
  - `lucro_rs = valor_rs − preco_rs`
  - `lucro_pct = lucro_rs / valor_rs` (0 quando o valor é 0)
- **Recálculo:** mudar um valor ou uma cotação recalcula todas as contas lidas, em menos de 1 s.
- **Conta ainda não lida:** fica com o valor em branco e a marca "itens ainda não lidos".

## 6. Interface

Tema escuro, fonte Segoe UI Variable, ícones reais do jogo, conforme os mockups aprovados. A barra do topo mostra as abas, as cotações (clicáveis para editar), "atualizado há X s", o progresso da carga e a engrenagem das configurações.

### Aba Contas (layout A, versão 2)

- **Três painéis.** Filtros (~27% da largura), lista e detalhes (~33%). As divisórias podem ser arrastadas e as larguras ficam salvas. O painel de detalhes pode ser recolhido.
- **Filtros:**
  - nome;
  - classes (chips);
  - preço mínimo e máximo (TCC);
  - nível mínimo;
  - Céu;
  - condições de item: item escolhido por sugestões (ou por parte do nome, que vale também para itens ainda não vistos nas contas lidas), refino ≥, quantidade ≥ e onde (qualquer, equipado, mochila, banco, cartas, engastada);
  - *Depois (24/09):* "Tem pelo menos um" (`algum` nos filtros), embaixo do "Tem item" (`itens`), com as mesmas condições. No "Tem item" a conta precisa atender a todas; aqui basta uma. Exemplo: a arma de um rank, que tem um nome em cada classe. Na aba Pesquisados dos detalhes, ele ganha um grupo próprio: os itens que a conta tem, com as seções e as unidades, e numa linha os que ela não tem. Não entra nas colunas de itens pesquisados da lista, no preço por unidade nem nas ordens por itens;
  - "só com lucro" e "só novas (24 h)";
  - ordenação: lucro R$, lucro %, preço, valor, nível ou mais novas. Com condições de item, também mais itens pesquisados (soma), mais de um item específico e menor preço por unidade.
- **Lista:**
  - Colunas: conta (com a marca NOVA nas primeiras 24 h desde que o programa a viu pela primeira vez; as contas da primeira consulta de um banco novo não ganham a marca), classe e nível, preço (com o lance mínimo embaixo, pequeno), lucro (R$ e %) e destaques (os itens da tabela que mais pesam).
  - Com condições de item, entram as colunas "Por un." (preço dividido pela soma dos itens pesquisados) e "Pesquisados" (a soma e as unidades de cada item pesquisado). A contagem é a mesma do filtro: todas as pilhas que atendem ao refino mínimo e ao "onde" da condição.
  - Acima da lista: quantas contas batem, o preço mínimo e a mediana.
  - As setas ↑ e ↓ trocam a conta selecionada.
- **Detalhes:**
  - cabeçalho com classe, nível e Céu;
  - preço (com o lance mínimo), valor estimado e lucro;
  - sub-abas (Equipado, Mochila, Banco, Cartas, Mascotes, Códice…) com a grade de itens: ícone, quantidade e tooltip colorido ao passar o mouse. Com condições de item, a primeira é "Pesquisados": quanto a conta tem de cada item, em que seções e o preço por unidade;
  - botões "Abrir no site" e "Copiar link";
  - por último, "de onde vem o valor", item por item, para os itens aparecerem logo abaixo do preço.
- **Atalho:** clicar num item da conta abre o balão "Definir valor", que grava direto na tabela.
- **Contas não lidas nos filtros de equipamento:** a busca do site (`item_ids`) confirma que a conta tem o item. O refino só dá para confirmar no caso do Cosmos (`g17_book_min`). Essas contas aparecem marcadas "a confirmar" até serem lidas e sobem para a prioridade média da fila.
- **Contas não lidas nos filtros de material ou quantidade:** a lista informa "X contas ainda não lidas".

### Aba Tabela de valores

- Itens cadastrados agrupados por tipo: livros, armas, cartas, pedras, materiais e outros.
- Cada linha mostra a condição de refino, o valor por unidade (kk ou bi), o valor em R$ e quantas contas têm o item. Editar e apagar aparecem ao passar o mouse.
- Painel "Adicionar item" com sugestões que vêm de duas fontes:
  1. o catálogo do site (1.408 equipamentos), disponível desde a abertura, sem precisar ver nenhuma conta antes;
  2. todo item já visto nas contas lidas (materiais, pedras, cartas), que aumenta conforme a carga avança.
- Se o item ainda não apareceu em nenhuma conta, dá para cadastrar pelo nome exato. Ele fica marcado "ainda não visto" e passa a valer quando surgir numa conta.
- Resumo no topo: valores cadastrados, contas com algum item da tabela e maior lucro no momento.

### Aba Buscas e avisos

- Buscas salvas: nome, resumo dos filtros, "me avisar" liga/desliga, preço máximo (TCC), lucro mínimo (R$ ou %), quantas contas batem agora e data do último aviso. O preço máximo da janela é o mesmo `preco_max` dos filtros da busca, e não um limite à parte; ao salvar a busca aberta na lista, o filtro da lista acompanha.
- Histórico de avisos. Clicar num aviso abre a conta na aba Contas.

### Configurações (janela da engrenagem)

| Chave | Padrão |
|---|---|
| `intervalo_s` | 60 (mínimo 30) |
| `pausa_s` | 2 (mínimo 1) |
| `leituras_simultaneas` | 1 (máximo 2) |
| `rs_por_bi` | 500,00 |
| `rs_por_tcc` | 1,00 |
| `aviso_windows` | ligado |
| `aviso_bipes` | ligado |
| `aviso_navegador` | desligado |
| `telegram_token`, `telegram_chat` | vazio |
| `discord_webhook` | vazio |

As larguras dos painéis também ficam em `config`. Elas, o Telegram e o Discord são de cada PC. As outras configurações vão para o `meus-dados.json` (seção 3.3).

## 7. Avisos

- Disparam quando uma conta nova, reativada ou com preço menor é lida e bate com uma busca que tem "me avisar" ligado, incluindo o preço máximo e o lucro mínimo, se houver. Uma conta acima do preço máximo que baixa até ele também avisa.
- **Não repetem:** uma mesma combinação de busca + conta + preço só avisa uma vez. Uma nova baixa de preço avisa de novo.
- **Canais:**
  - notificação do Windows, que fica na tela até ser fechada; clicar nela ou em "Abrir anúncio" abre o anúncio no site para comprar;
  - 3 bipes;
  - navegador;
  - Telegram e Discord, opcionais.
- O aviso também entra no histórico da aba Buscas e avisos.

## 8. Erros

- **Site fora do ar ou lento:** mantém os últimos dados, mostra "sem conexão desde HH:MM" no topo e tenta de novo na próxima consulta. Uma conta que falha volta para a fila.
- **O site mudou e a leitura quebrou:** a lista vazia ou a conta sem nenhum item vira um aviso claro no topo ("não consegui ler a lista; o site pode ter mudado"). Nada é apagado do banco.
- **Busca do site indisponível:** os filtros de equipamento usam só as contas já lidas, com o aviso "resultado parcial".
- **Tooltips:** só texto e cor são guardados e exibidos. Nenhum HTML do site é injetado na interface.
- **Porta ou banco ocupados:** mensagem clara e o programa não abre uma segunda cópia.
- **`meus-dados.json` com erro ou conflito do git:** a faixa do topo avisa, o banco continua com os últimos dados e as mudanças na tabela, nas buscas e nas configurações são recusadas até o arquivo ser resolvido ou apagado (seção 3.3).

## 9. Decisões tomadas durante a implementação

- **Itens repetidos na página:** a seção "Cartas equipadas" repete as cartas que já estão em "Equipamento", e o boneco do topo repete o equipamento. As duas ficam de fora para não contar em dobro.
- **Fora da soma do valor e dos filtros "em qualquer lugar":** o códice (coleção de visuais) e a recompra.
- **Lucro só quando existe valor:** uma conta sem nenhum item da tabela aparece com "—" em vez de um lucro negativo igual ao preço.
- **A fila se ajusta à tabela:** ao cadastrar valores ou salvar buscas, as contas não lidas que a busca do site aponta com esses itens sobem na fila na hora.
- **Botão "Ler agora":** nos detalhes de uma conta ainda não lida, passa a conta na frente da fila.
- **Segurança da API:** o servidor escuta só em 127.0.0.1. Cada chamada exige o token da execução (cabeçalho X-Token) e um cabeçalho Host local.
- **Tooltips:** guardados uma vez só, compactados, reduzidos a texto e cor.
- **Limpeza:** os itens de anúncios fora do ar há mais de 7 dias são apagados ao abrir o programa.
- **Janela:** o programa acompanha o processo do Edge que abriu e segue aberto enquanto ele tiver uma janela visível (a do programa ou uma do "Abrir no site"), mesmo minimizada ou atrás do jogo. As janelas são vistas pela API do Windows (`EnumWindows`, via ctypes).
  - **Edge aberto sem janela por 30 s:** o programa encerra e fecha o Edge.
  - **Edge que sai logo na abertura:** outra janela do mesmo perfil ficou com ela, e a janela passa a ser achada pelo título da página.
  - **Navegador padrão:** só nele vale o sinal que a página envia a cada 15 s.
  - **Contagem:** os tempos são contados em voltas de 1 s, e não pelo relógio, para uma suspensão do Windows não contar.
  - **Log:** registra o motivo de cada encerramento e quando a página passa 10 min sem sinal com a janela aberta.
  - *Depois (24/09):* antes, o programa fechava o Edge quando a página passava 10 min sem sinal, mesmo com a janela aberta. O programa fechava sozinho de tempos em tempos.
- **Atualização da interface:** ela consulta o estado a cada 3 s, mas só redesenha a lista se algo visível mudou e só recarrega os detalhes se a conta aberta mudou. O formulário de cadastro nunca é redesenhado enquanto você digita.
- **Botão Sincronizar (25/09, `mercado/sincronia.py`):**
  - `git fetch` e, se o GitHub andou, junta item a item três versões do `meus-dados.json`: a do último commit em comum (base), a daqui e a do GitHub (`juntar`);
  - depois avança o `main` (`merge --ff-only`), grava o resultado, faz o commit só do arquivo e o `git push`;
  - se o push falha, o commit é desfeito (`reset --soft`);
  - não mexe no git com mudanças no código sem commit, fora do `main`, no meio de um merge ou com commits dos dois lados;
  - o ponto no botão compara o hash dos dados com o do último envio (`enviado_hash`).
- **Grupos de itens (24/09):**
  - ficam na tabela `grupos` (nome e itens em JSON, com `item_id` e nome) e no `meus-dados.json`;
  - na busca, uma condição `grupo_id` vale para qualquer item do grupo: `item_id IN (…)`, com o refino, a quantidade (somada entre os itens) e o "onde" da condição;
  - `_resolver_grupos` põe os itens e o nome de agora na condição; um grupo apagado não acha nada;
  - a busca do site junta os equipamentos do catálogo que estão no grupo numa consulta só (o site trata vários itens com OU);
  - na interface, os grupos aparecem primeiro nas sugestões de "Tem item" e "Tem pelo menos um";
  - os grupos Armas UP4 e UP3 saíram da linha "Nível de Ataque +70" ou "+40" nos tooltips das armas.
- **"Tem pelo menos um" no banco (24/09):**
  - cada condição vira uma subconsulta, e elas se juntam com `UNION`;
  - das contas ainda não lidas, entram como "a confirmar" as que a busca do site aponta para pelo menos um dos equipamentos;
  - os itens também contam nas buscas salvas para a fila do coletor (`ids_valorizados`).
- **Ordens pelos itens pesquisados:** as contas ainda não lidas ("a confirmar") vão para o fim, porque não se sabe quanto têm. "Mais …" (um item) segue o item quando outra condição é removida. Sem condições de item, essas ordens somem e volta a ordem padrão. Ao adicionar o primeiro item, a ordem passa para "Mais itens pesquisados".
- **Ordenar pela coluna:** os títulos Preço, Por un., Pesquisados, Valor e Lucro ordenam a lista, e o "Ordenar por" acompanha. O "Ordenar por" fica no fim do painel de filtros e some da tela quando há várias condições de item.
- **Lance mínimo:** o site aceita lances a partir de 70% do preço pedido. O valor é fixo no programa (`LANCE_MINIMO_PCT` no app.js), arredondado para cima (45 → 32), igual ao que o site mostra (2.400 → 1.680, 15.000 → 10.500). *Depois (24/09):* o Por un. mostra embaixo o preço por unidade com o lance mínimo (lance mínimo ÷ soma dos itens pesquisados), com as mesmas casas decimais da coluna. A aba Pesquisados dos detalhes mostra o mesmo.
- **Colunas de número alinhadas:** cada número da lista tem a sua coluna, com o título alinhado do mesmo lado (à direita), e as mesmas casas decimais em todas as linhas. Por unidade: 3 algarismos no menor valor. R$: centavos só se todos os valores forem menores que R$ 100. Nos pesquisados, a soma e cada item são colunas separadas, com o número colado no ícone. Com a lista estreita, as marcas NOVA e A CONFIRMAR descem para baixo do nome.
- **Item digitado pelo nome:** a condição vale para qualquer item com o texto no nome, sem diferenciar maiúsculas e acentos. Na Tabela de valores, o nome continua exato, porque o valor é de um item só.
- **Mais de um PC (23/09):** os seus dados vão pelo git no `meus-dados.json`, e as contas continuam em cada PC (seção 3.3). Foram descartados:
  - o `mercado.db` no git, pelo tamanho;
  - o banco inteiro numa pasta do OneDrive: o SQLite não aguenta ser sincronizado com o programa aberto, e só um PC poderia abrir por vez;
  - um banco na internet, que exigiria instalar pacotes e deixaria as buscas lentas.
- **Ids ao juntar mudanças de dois PCs:** depois de um merge do git, valores ou buscas com o mesmo id ganham um id novo, e nenhum se perde. O histórico de avisos de uma busca apagada, ou que virou outra (data de criação diferente), sai junto.

## 10. Testes

- **Testes automáticos** (`python -m unittest`) com páginas reais salvas em `tests/paginas/`: a lista, a conta 45520 e uma conta com Cosmos +12 e Pedras do Demônio. Eles cobrem:
  - leitura dos cards;
  - leitura dos itens por seção, refino, quantidade e pedras engastadas;
  - cálculo do valor (faixas, quantidades, pedras, conversões);
  - filtros no SQLite;
  - avisos (novo, baixa de preço, preço máximo, lucro mínimo, sem repetição);
  - ordem da fila;
  - `meus-dados.json`: primeira vez, outro PC vazio ou com dados, `git pull` com o programa aberto, conflito do git, ids repetidos e o que fica só em cada PC.
- **Teste completo** com uma lista simulada contendo uma conta nova, conferindo aviso, histórico e interface.
- **Conferência manual da janela:** abrir, filtrar, ver detalhes, cadastrar valor, salvar busca e alterar configurações.
