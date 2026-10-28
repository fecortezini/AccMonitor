# Mercado PW

Programa para PC que acompanha o [Marketplace The Classic](https://marketplace.theclassic.games/pw187) do PW 1.8.7. Ele faz três coisas:

- lista todas as contas anunciadas e permite filtrar por classe, preço, nível, Céu e itens;
- calcula quanto cada conta vale pela **sua** tabela de valores e ordena pelas maiores barganhas;
- avisa na hora quando aparece uma conta nova, ou que baixou de preço, que bate com uma busca salva.

Além disso, acompanha as contas que você marca como **favoritas**: avisa quando elas baixam de preço, recebem lance ou saem do mercado, e diz se saíram porque foram vendidas.

![Aba Contas: filtros, lista ordenada por lucro e detalhes com o tooltip do item](docs/telas/contas.png)

## Como abrir

Você precisa de:
- **Python.** Já vem na pasta `python` (o Python 3.13 "embeddable" do python.org, que não precisa instalar). Sem essa pasta, o programa usa o Python do PC, que precisa ser o 3.11 ou mais novo. Não há pacotes para instalar.
- **Microsoft Edge.** Já vem no Windows 10 e 11.

Para abrir, dê dois cliques em **`Mercado PW.bat`**. O programa abre numa janela própria, sem abas nem barra de endereço, e **fechar a janela encerra o programa**. Minimizada ou atrás do jogo, ela continua aberta e o programa segue trabalhando. Um segundo clique com ele já aberto apenas abre outra janela.

## Primeira vez

1. **Carga inicial.** Assim que abre, o programa baixa a lista de anúncios e começa a ler, em segundo plano, os itens de cada conta. Cada conta é lida uma vez só. Com cerca de 1.500 anúncios, a carga inicial leva por volta de 1 h 45 com as configurações padrão, num ritmo que não sobrecarrega o site. Com a pausa de 1 s e 2 contas lidas ao mesmo tempo (⚙ Configurações), cai para uns 45 min. O que já foi lido fica salvo: se fechar no meio, ele continua de onde parou. A barra no topo mostra o progresso e quanto tempo falta, no ritmo dos últimos 5 minutos.
2. **O que é lido primeiro:**
   - contas novas ou que baixaram de preço;
   - com **Ler primeiro as destes filtros** ligado (na barra do topo, aparece quando há filtros), as contas que podem bater com os filtros da aba Contas. Em itens que o site indexa (equipamentos), a busca do próprio site diz quais contas têm o item, e só essas sobem. Nos outros itens, como relíquias e materiais, sobem as que batem com os demais filtros (classe, preço, nível…). A barra mostra quantas faltam. Ao trocar os filtros, as da busca anterior voltam à ordem normal;
   - contas que têm itens da sua tabela de valores (o programa descobre quais são pela busca do próprio site, em menos de 1 s);
   - o restante, das mais baratas para as mais caras.
3. **Cadastre seus valores.** Na aba **Tabela de valores**, digite "cosmos", escolha a faixa de refino e informe o valor em kk ou bi.
4. **Monte uma busca.** Na aba **Contas**, monte os filtros e clique em **Salvar busca e me avisar**.

Nos outros PCs, os passos 3 e 4 não são necessários: os valores, as buscas e as configurações chegam pelo git.

## Em mais de um PC

A tabela de valores, as buscas salvas, os grupos de itens, as favoritas e as ⚙ Configurações ficam no arquivo **`meus-dados.json`**, que vai pelo git junto com o programa. Você configura uma vez, e todos os PCs usam os mesmos dados.

- **Botão Sincronizar** (no topo): clique ao terminar num PC e ao começar no outro.
  - **O que faz:** manda para o GitHub o que mudou aqui e traz o que mudou lá, pelo git da pasta do programa. O programa grava no `meus-dados.json` a cada mudança.
  - **Ponto dourado no botão:** há mudanças daqui ainda não enviadas.
  - **Os dois PCs mudaram:** os dados se juntam item a item e nada se perde. Se o mesmo item mudou nos dois, fica a versão mais recente.
  - **Versão nova do programa:** se chegar uma, ele avisa para fechar e abrir de novo.
  - **Quando ele não mexe no git:** com mudanças no código ainda sem commit, fora do branch `main` ou com commits dos dois lados. Nesses casos ele explica o que falta.
- **Sem o botão:** os mesmos passos podem ser feitos pelo git (`git add meus-dados.json`, `git commit`, `git push` e, no outro PC, `git pull`). Com o programa aberto, o que chega pelo `git pull` aparece em poucos segundos.
- **O que fica em cada PC:**
  - as contas lidas do site: cada PC lê as suas, começando pelas que têm itens da sua tabela;
  - a situação de cada favorita (à venda, confirmando venda ou retirada): cada PC descobre pelo site;
  - o histórico de avisos;
  - a largura dos painéis;
  - o Telegram e o Discord, para os tokens não irem para o git.
- **PC que já tinha dados:** na primeira vez com o arquivo, ficam valendo os dados do `meus-dados.json`, e os que o PC tinha são guardados em `meus-dados.anterior.json`.
- **Conflito no git:** se o `git pull` deixar o `meus-dados.json` com conflito, uma faixa vermelha avisa no topo. Até você resolver, as mudanças na tabela, nas buscas e nas configurações não são salvas. Também dá para apagar o arquivo: o programa grava de novo os dados do PC.

## O que tem em cada aba

**Contas**
- **Filtros:** nome, classes, faixa de preço (TCC), nível mínimo, Céu e condições de item (refino mínimo, quantidade mínima e onde o item está: equipado, mochila, banco, cartas, engastado, mascotes). As sugestões do "Tem item" trazem os equipamentos do site e os itens já vistos nas contas lidas. Qualquer item também pode ser buscado por parte do nome, inclusive os que ainda não apareceram, como uma pedra engastada rara. Por exemplo, "pedra do dem", ou "relíquia maravilha" para juntar as três relíquias numa condição. As contas que tiverem o item aparecem conforme forem lidas.
- **Tem pelo menos um:** fica embaixo do "Tem item". No "Tem item" a conta precisa ter todos os itens; aqui basta ter um deles.
  - **Para que serve:** por exemplo, a arma de um rank, que tem um nome em cada classe. Adicione a arma de cada classe que você quer, e só aparecem as contas que têm uma delas.
  - **Campos:** cada item tem os mesmos campos do "Tem item" (refino, quantidade e onde).
  - **Onde aparece:** na aba **Pesquisados** dos detalhes, num grupo próprio, com o item que a conta tem, onde está e quantas unidades, e numa linha os que ela não tem. Na lista ele não vira coluna nem entra no Por un.
  - **Junto com os outros filtros:** vale com todos, inclusive o "Tem item", e também nas buscas salvas e nos avisos.
- **Grupos de itens:** juntam itens que você busca juntos, como as cartas de um combo ou as armas de um rank.
  - **Criar e editar:** pelo link **grupos**, ao lado do "Tem pelo menos um". Na janela você cria um grupo, dá um nome e adiciona os itens.
  - **Usar:** ao adicionar uma condição, no "Tem item" ou no "Tem pelo menos um", os grupos aparecem antes dos itens. Com a caixa vazia aparecem todos. Escolha o grupo em vez de pôr item por item.
  - **Como vale na busca:** no "Tem item", a conta precisa ter **todos** os itens do grupo, cada um com o refino mínimo, a quantidade e o onde da condição. É o caso das cartas de um combo. No "Tem pelo menos um", basta **um** deles, como a arma de um rank. Para achar qualquer arma UP4, use o grupo no "Tem pelo menos um".
  - **Mudanças:** um grupo alterado passa a valer em todas as buscas salvas que o usam.
  - **No outro PC:** os grupos vão no `meus-dados.json`.
  - **Já criados:**
    - **UP4:** as 21 armas G17 com Nível de Ataque +70.
    - **UP5:** as 31 armas seguintes: a versão de ataque (Nível de Ataque +80, id da UP4 + 1) e a de defesa (Nível de Defesa +80, id + 2).
    - **G17 UP1** e **G17 UP2:** as 12 peças de armadura G17 (Coração de Leão, Ashura da Coragem e Arcanjo da Justiça: peitoral, calça, botas e braçadeira), em ★ no UP1 e ★★ no UP2. São as mesmas contas que o filtro "Armadura G17" do site devolve.
    - **UP3:** as 34 armas ★★★ com Nível de Ataque +40.
    - **R8 UP3:** os sets ★★★ de Classe/Patente 8 das 17 classes (68 peças: peitoral, calça, botas e braçadeira), como a Brigandina do Oceano: Sol.
    - **R9 UP1**, **R9 UP2** e **R9 UP3:** as armaduras de R9 de cada fase (só peitoral, calça, botas e braçadeira). A fase vem da defesa da peça, que é fixa em cada uma, e não das estrelas: o Escárnio das Almas ★★★ é UP2, por exemplo. O UP3 é a série "digno de honra" (Adversidade, Apoteose, Réquiem...) e a das classes novas; nestas, as peças que nenhuma conta lida usava entraram por eliminação.
    - **Combo Seis Soberanos** (combo A) e **Combo Portal de Nuema** (combo S): as 6 cartas de cada combo, uma de cada tipo. No "Tem item", acham as contas com o combo completo; com "equipado", só as que estão com as 6 cartas equipadas.
    - **Runas Nv. 5+:** as 45 runas de nível 5 a 10 das 5 cores (Áurea, Argêntea, Celeste, Escarlate e Verdejante), inclusive as variantes "Nv. 5", "Nível 7" e "Nível 8" com outro id. Use no **"Tem pelo menos um"**: no "Tem item" ele exigiria as 45. Com quantidade, como "3×", acha as contas com pelo menos 3 runas dessas. A busca do site não conhece runas, então só aparecem as contas já lidas.
    - **Runas Nv. 10:** só as 5 runas de nível 10, uma de cada cor. Também é para o "Tem pelo menos um".
- **Lista:** ordenada por lucro, em R$ ou %, com a marca **NOVA** para contas das últimas 24 h. Embaixo do preço aparece, pequeno, o lance mínimo que o site aceita: 70% do preço pedido (também nos detalhes).
- **Lances recebidos:** embaixo do mínimo aparece o maior lance que a conta já recebeu, como "lance 1.296" ou "lance 885 · 2" com dois lances. É o mesmo "Lances pendentes" que o site mostra ao clicar em Fazer lance, sem precisar de login. Um lance novo (dos últimos 30 min) fica verde, com ▲.
  - **As 50 primeiras contas da busca e a conta aberta:** os lances são relidos a cada 1 min, ou mais espaçado se forem muitas, até 10 páginas por minuto. Serve para acompanhar se alguém deu lance numa conta que você quer.
  - **As outras:** relidas devagar, uma a cada 30 s. O tooltip do lance diz há quanto tempo ele foi visto.
  - **O custo:** cerca de 5 a 12 páginas de conta por minuto (116 KB cada) enquanto o programa está aberto. Contas que ainda não foram lidas, mas que a busca do site diz terem o item, aparecem como **A CONFIRMAR**.
- **Itens pesquisados:** com condições de item, a lista ganha as colunas **Por un.** e **Pesquisados**:
  - Por un. é o preço dividido pela soma de todos os itens pesquisados (TCC por unidade). Embaixo, pequeno, aparece o mesmo cálculo com o lance mínimo (também na aba Pesquisados dos detalhes);
  - os itens ficam na ordem em que você os escolhe (por exemplo, do mais importante para o menos importante), e as colunas e a aba Pesquisados seguem essa ordem. Ela não muda quais contas batem nem o Por un.;
  - Pesquisados mostra a soma e quantas unidades de cada item a conta tem, cada número na sua coluna;
  - a contagem junta todas as pilhas e respeita o refino mínimo e o "onde" de cada condição;
  - novas ordenações: "Mais itens pesquisados" (a soma), "Mais …" (um item específico) e "Menor preço por unidade";
  - ao adicionar o primeiro item, a lista já passa para "Mais itens pesquisados";
  - nessas ordenações, os empates ficam com o menor preço, e as contas ainda não lidas aparecem com "?" no fim.
- **Ordenar pela coluna:** clicar no título Preço, Por un., Pesquisados, Valor ou Lucro ordena por ela. A coluna em uso fica dourada, com ▾ (maior primeiro) ou ▴ (menor primeiro).
- **Detalhes:** mostram os itens por aba, com o tooltip do jogo ao passar o mouse, o botão "Abrir no site" e, por último, de onde vem o valor. Com condições de item, a primeira aba, **Pesquisados**, mostra quanto a conta tem de cada item, onde estão (mochila, banco…) e o preço por unidade. Clicar num item abre um balão para dar valor a ele ali mesmo.
- **Aba Runas (nos detalhes):** as runas da conta, separadas em **Nas habilidades** (com a habilidade em que cada uma está incorporada, na ordem do site) e **Guardadas** (as iguais juntas, da de maior nível para a menor). O selo **negociável** marca as runas soltas, que podem ser vendidas. O topo resume quantas são. Contas lidas antes desta versão mostram todas como guardadas até serem lidas de novo.
- **Painéis:** as divisórias ⋮ podem ser arrastadas, e o botão ⟩ recolhe os detalhes (a lista ganha as colunas Céu e Valor). Use ↑ e ↓ para percorrer a lista.

**Tabela de valores**
- **É global:** cada item é cadastrado uma vez e vale para todas as contas, as de hoje e as futuras.
- **Sugestões:** vêm do catálogo do site (disponível desde o primeiro minuto) e de tudo o que já foi visto nas contas: materiais, pedras e cartas. Um item que ainda não apareceu pode ser cadastrado pelo nome; o valor passa a contar quando o item surgir.
- **Valor de um grupo:** os grupos de itens também aparecem nas sugestões. Por exemplo, "Armas UP4 = 100 kk" vale para cada uma das armas do grupo, sem cadastrar uma por uma.
  - **Criar o grupo ali mesmo:** digite o nome (ex.: "Armas UP4") e clique em **Criar grupo de itens**. Na janela, adicione os itens e feche: o grupo já fica escolhido no "Adicionar item", e falta só o valor. **ver grupos** abre a mesma janela para editar os grupos que já existem.
  - **Faixas e exceções:** aceita faixas de refino como um item, por exemplo qualquer refino = 100 kk e ≥ +12 = 1 bi. Um item com valor próprio na tabela usa o dele, e o do grupo serve para os outros. Renomear o grupo muda o nome do valor, e apagar o grupo apaga os valores dele.

![Tabela de valores com o cadastro de um item](docs/telas/tabela-de-valores.png)

**Buscas e avisos**
- Buscas salvas com "me avisar", preço máximo, lucro mínimo (R$ ou %) e quantas contas batem agora. Exemplo: avisar sempre que aparecer uma conta com um ou mais itens escolhidos por até 5.000 TCC. O preço aceita "5k". Ele é o mesmo "Preço máximo" dos filtros, então vale também para a lista da busca.
- Histórico dos avisos, das buscas e das favoritas ("★ Favorita"). Clicar num aviso abre a conta.

**★ Favoritas**
- **Marcar:** clique na ☆ ao lado do nome de uma conta na aba Contas, ou no botão **Favoritar** dos detalhes. Clicar de novo desmarca.
- **A aba:** a lista das favoritas, com preço, lances e a situação de cada uma (**À venda**, **Confirmando venda…** ou **Retirada**), e os detalhes ao lado, como na aba Contas. As que estão confirmando venda vêm primeiro, e uma situação que mudou nos últimos 30 min fica verde, com ▲.
- **Avisos** (pelos mesmos canais das buscas, com "★" no título):

  | Acontecimento | Quando avisa |
  |---|---|
  | Baixou de preço | Na consulta da lista, com o preço de antes e o novo. |
  | Lance novo | Na releitura dos lances. Os das favoritas são relidos a cada 1 min, junto com a conta aberta. Como as outras, só depois da carga inicial. |
  | Saiu do mercado | Na hora: "saiu do mercado, conferindo se foi vendida…". |
  | Vendida | Em ~1 a 2 min: "vendida por 30 TCC (anunciada por 40 TCC, lance aceito)". Clicar abre a página da venda no site. |
  | Retirada | 10 min depois de sair, quando não aparece venda: "saiu do mercado sem venda". |
  | Anunciada de novo | Uma retirada que volta ao mercado, com o preço novo. |

- **Como ele sabe que foi vendida:** procura o nome da conta no [histórico de vendas](https://marketplace.theclassic.games/history?game=pw187) do site 1, 3 e 10 min depois de ela sair da lista. A página de cada venda com esse nome mostra o ID da conta, que confirma se é ela. São 1 ou 2 páginas a mais por favorita que sai. Sem internet, a busca é refeita depois, sem contar como tentativa.
- **Vendida sai das favoritas:** depois do aviso, ela deixa de ser favorita (também no outro PC, pelo Sincronizar), e os itens guardados dela são apagados. Se quem comprou anunciar a conta de novo, ela aparece na lista como qualquer outra.
- **Programa fechado:** ao abrir, as favoritas que saíram enquanto ele estava fechado são procuradas no histórico, que guarda 90 dias. Nesse caso não vem o aviso "saiu", só o resultado.
- **Itens:** os itens de uma favorita que saiu do ar continuam guardados, mesmo depois dos 7 dias em que os das outras contas são apagados.
- **Limitações:**
  - se o comprador trocar o nome da conta, a venda não é achada, e ela aparece como retirada;
  - se ela for vendida e anunciada de novo enquanto o programa estava fechado, ele só vê o preço novo.

**⚙ Configurações**

| Opção | O que faz |
|---|---|
| Intervalo de consulta | De quanto em quanto tempo a lista é consultada. Padrão 60 s, mínimo 30 s. |
| Pausa entre contas | Intervalo entre a leitura de uma conta e a próxima. Padrão 2 s, mínimo 1 s. |
| Contas lidas ao mesmo tempo | De 1 (padrão) a 8. Com 2, a carga inicial leva ~40% menos tempo, mas o site recebe o dobro de acessos; acima disso, mais ainda. Se ele recusar algum (HTTP 403, 429 ou 503), o programa volta sozinho para 1 e avisa no topo com quantas contas estava lendo. |
| Cotações | Quanto vale 1 bi e 1 TCC em reais. Padrão: 1 bi = R$ 500 e 1 TCC = R$ 1. |
| Avisos | Notificação do Windows (clicar abre o anúncio para comprar), bipes (tocam mesmo com o "Não perturbe" ligado, por exemplo durante o jogo), abrir no navegador, Telegram e Discord (estes dois ficam só no PC em que foram configurados). O botão "Testar avisos" confere se estão funcionando. |

![Configurações](docs/telas/configuracoes.png)

## Como o valor é calculado

- Cada linha da tabela vale **por unidade**, em kk (1 bi = 1.000 kk).
- **Faixas de refino:** com várias faixas do mesmo item, vale a maior que o item atinge. Com Cosmos +10 = 3 bi e +12 = 6 bi, um Cosmos +12 conta 6 bi. Cada faixa é o valor total do item com aquele refino: se o livro vale 3 bi e o +12 acrescenta 2,4 bi, cadastre qualquer refino = 3 bi e ≥ +12 = 5,4 bi.
- **Grupos:** a linha de um grupo vale para cada item dele, com as mesmas faixas. O valor do próprio item vem antes. Se nenhuma faixa dele serve para o refino que a conta tem, vale o do grupo. Com o item em mais de um grupo, vale o grupo que dá mais.
- **Quantidades:** itens empilháveis contam quantidade × valor, e cada pedra engastada conta uma unidade.
- **O que fica de fora:** o códice (coleção de visuais) e a lista de recompra. O ouro que o personagem carrega também não entra, porque os vendedores costumam retirá-lo.
- **Contas:**
  - valor em R$ = soma dos itens em kk ÷ 1.000 × R$ por bi;
  - preço em R$ = TCC × R$ por TCC;
  - lucro = valor − preço;
  - % = lucro ÷ valor.
- **Contas sem nenhum item da tabela** ficam sem lucro ("—").

## Arquivos

| Caminho | O que é |
|---|---|
| `Mercado PW.bat` | Abre o programa. |
| `python/` | O Python que o programa usa, sem instalar (o "embeddable" 3.13 do python.org). O `python313._pth` inclui a pasta do programa (`..`) para o `-m mercado` funcionar. |
| `mercado/` | Código: leitura do site, banco, cálculo, coletor, avisos, servidor local e interface (`mercado/ui`). |
| `meus-dados.json` | Sua tabela de valores, buscas, grupos de itens, favoritas e configurações. Vai pelo git para os outros PCs (veja "Em mais de um PC"). |
| `mercado.db` | As contas lidas do site, o histórico de avisos e uma cópia dos seus dados. Fica só neste PC. |
| `mercado.log` | Registro do que o programa fez, inclusive o motivo de cada encerramento. Útil se algo der errado. |
| `.janela/` | Perfil separado do Edge usado pela janela do programa. |
| `docs/` | Desenho do programa e telas aprovadas. |
| `helper.py`, `filtros.toml`, `iniciar.bat` | A primeira versão, de linha de comando. Ainda funciona, mas o programa novo faz tudo o que ela fazia. |

## Para desenvolvedores

```
py -m unittest discover -s tests -t .     # testes (usam páginas reais salvas em tests/paginas)
py -m mercado --sem-janela --porta 8765   # só o servidor, para abrir no navegador
```

- **Segurança:** o servidor local só aceita conexões do próprio PC. Cada chamada da interface leva um token gerado a cada execução.
- **Ritmo:** o programa só lê páginas públicas do marketplace. Mantenha o intervalo e a pausa em valores razoáveis. O ritmo dos lances fica nas constantes `LANCES_*` do `mercado/coletor.py`, e o das buscas no histórico de vendas nas `BUSCAS_DE_VENDA_MIN`, `VENDA_FOLGA_MIN`, `VENDAS_A_CONFERIR` e `BUSCA_FALHOU_S`.
- **Se o site mudar:** se o layout do marketplace mudar, a leitura pode falhar. Nesse caso aparece um aviso no topo da janela e nada do que já foi guardado é apagado.
