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
- O valor e o lucro de todas as contas ficam disponíveis depois da primeira carga (1 h a 1 h30, uma única vez). Depois disso, qualquer busca é instantânea.
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
  mercado.db            criado na primeira execução
  tests/                testes com páginas reais salvas
```

`site.py` e `avisos.py` reaproveitam o código já testado do `helper.py` (leitura dos cards, leitura dos itens com seção, notificação do Windows, bipes, Telegram, Discord).

### 3.1 Janela

`__main__.py` escolhe uma porta livre em 127.0.0.1 e abre:

`msedge --app=http://127.0.0.1:{porta}/ --user-data-dir=<pasta>/.janela --no-first-run --window-size=1440,900`

O perfil separado faz a janela ser independente do Edge do usuário. O programa encerra quando esse processo do Edge termina, ou seja, quando a janela é fechada. Se o Edge não for encontrado, abre o navegador padrão e encerra depois de 90 s sem sinal da página, que envia um sinal a cada 20 s.

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

## 4. Coletor: como os dados chegam

**Consulta da lista** (a cada `intervalo_s`, padrão 60 s, mínimo 30 s):

1. Baixa e lê a lista.
2. Se vier com menos da metade dos anúncios da consulta anterior, trata como falha e ignora a rodada.
3. Atualiza `anuncios`. Anúncios que sumiram ficam com `ativo = 0`.
4. Anúncios novos, reativados ou com preço menor entram na fila com **prioridade alta**.

**Fila de leitura** (uma conta por vez, com `pausa_s` entre páginas, padrão 2 s, mínimo 1 s). Para cada conta, lê os itens, grava, recalcula o valor e confere as buscas com aviso ligado (seção 7).

A fila é preenchida nesta ordem:

1. **Alta:** contas novas ou que baixaram de preço.
2. **Média:** contas que a busca do site diz terem algum equipamento da tabela de valores ou das buscas salvas. As contas com Cosmos ficam prontas no primeiro minuto.
3. **Baixa:** as demais ainda não lidas, das mais baratas para as mais caras.

Uma conta só é relida quando o preço muda ou quando é anunciada de novo.

**Tempo da primeira carga:** cerca de 1.500 contas × ~3,5 s ≈ 1 h a 1 h30 com a pausa padrão. O progresso aparece na barra do topo ("itens lidos 812/1.509"). A carga só avança com o programa aberto, e o que já foi lido fica salvo.

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
  - condições de item: item escolhido por sugestões, refino ≥, quantidade ≥ e onde (qualquer, equipado, mochila, banco, cartas, engastada);
  - "só com lucro" e "só novas (24 h)";
  - ordenação: lucro R$, lucro %, preço, valor, nível ou mais novas.
- **Lista:**
  - Colunas: conta (com a marca NOVA nas primeiras 24 h desde que o programa a viu pela primeira vez; as contas da primeira consulta de um banco novo não ganham a marca), classe e nível, preço, lucro (R$ e %) e destaques (os itens da tabela que mais pesam).
  - Acima da lista: quantas contas batem, o preço mínimo e a mediana.
  - As setas ↑ e ↓ trocam a conta selecionada.
- **Detalhes:**
  - cabeçalho com classe, nível e Céu;
  - preço, valor estimado e lucro;
  - "de onde vem o valor", item por item;
  - sub-abas (Equipado, Mochila, Banco, Cartas, Mascotes, Códice…) com a grade de itens: ícone, quantidade e tooltip colorido ao passar o mouse;
  - botões "Abrir no site" e "Copiar link".
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

- Buscas salvas: nome, resumo dos filtros, "me avisar" liga/desliga, lucro mínimo (R$ ou %), quantas contas batem agora e data do último aviso.
- Histórico de avisos. Clicar num aviso abre a conta na aba Contas.

### Configurações (janela da engrenagem)

| Chave | Padrão |
|---|---|
| `intervalo_s` | 60 (mínimo 30) |
| `pausa_s` | 2 (mínimo 1) |
| `rs_por_bi` | 500,00 |
| `rs_por_tcc` | 1,00 |
| `aviso_windows` | ligado |
| `aviso_bipes` | ligado |
| `aviso_navegador` | desligado |
| `telegram_token`, `telegram_chat` | vazio |
| `discord_webhook` | vazio |

As larguras dos painéis também ficam em `config`.

## 7. Avisos

- Disparam quando uma conta nova, reativada ou com preço menor é lida e bate com uma busca que tem "me avisar" ligado, incluindo o lucro mínimo, se houver.
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

## 9. Decisões tomadas durante a implementação

- **Itens repetidos na página:** a seção "Cartas equipadas" repete as cartas que já estão em "Equipamento", e o boneco do topo repete o equipamento. As duas ficam de fora para não contar em dobro.
- **Fora da soma do valor e dos filtros "em qualquer lugar":** o códice (coleção de visuais) e a recompra.
- **Lucro só quando existe valor:** uma conta sem nenhum item da tabela aparece com "—" em vez de um lucro negativo igual ao preço.
- **A fila se ajusta à tabela:** ao cadastrar valores ou salvar buscas, as contas não lidas que a busca do site aponta com esses itens sobem na fila na hora.
- **Botão "Ler agora":** nos detalhes de uma conta ainda não lida, passa a conta na frente da fila.
- **Segurança da API:** o servidor escuta só em 127.0.0.1. Cada chamada exige o token da execução (cabeçalho X-Token) e um cabeçalho Host local.
- **Tooltips:** guardados uma vez só, compactados, reduzidos a texto e cor.
- **Limpeza:** os itens de anúncios fora do ar há mais de 7 dias são apagados ao abrir o programa.
- **Janela:** o programa acompanha o processo do Edge que abriu. Se esse processo terminar logo na abertura (outra janela do mesmo perfil ficou com ela), passa a valer o sinal que a página envia a cada 15 s.
- **Atualização da interface:** ela consulta o estado a cada 3 s, mas só redesenha a lista se algo visível mudou e só recarrega os detalhes se a conta aberta mudou. O formulário de cadastro nunca é redesenhado enquanto você digita.

## 10. Testes

- **Testes automáticos** (`python -m unittest`) com páginas reais salvas em `tests/paginas/`: a lista, a conta 45520 e uma conta com Cosmos +12 e Pedras do Demônio. Eles cobrem:
  - leitura dos cards;
  - leitura dos itens por seção, refino, quantidade e pedras engastadas;
  - cálculo do valor (faixas, quantidades, pedras, conversões);
  - filtros no SQLite;
  - avisos (novo, baixa de preço, lucro mínimo, sem repetição);
  - ordem da fila.
- **Teste completo** com uma lista simulada contendo uma conta nova, conferindo aviso, histórico e interface.
- **Conferência manual da janela:** abrir, filtrar, ver detalhes, cadastrar valor, salvar busca e alterar configurações.
