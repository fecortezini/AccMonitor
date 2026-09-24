# Mercado PW

Programa para PC que acompanha o [Marketplace The Classic](https://marketplace.theclassic.games/pw187) do PW 1.8.7. Ele faz três coisas:

- lista todas as contas anunciadas e permite filtrar por classe, preço, nível, Céu e itens;
- calcula quanto cada conta vale pela **sua** tabela de valores e ordena pelas maiores barganhas;
- avisa na hora quando aparece uma conta nova, ou que baixou de preço, que bate com uma busca salva.

![Aba Contas: filtros, lista ordenada por lucro e detalhes com o tooltip do item](docs/telas/contas.png)

## Como abrir

Você precisa de:
- **Python 3.11 ou mais novo.** Não há pacotes para instalar.
- **Microsoft Edge.** Já vem no Windows 10 e 11.

Para abrir, dê dois cliques em **`Mercado PW.bat`**. O programa abre numa janela própria, sem abas nem barra de endereço, e **fechar a janela encerra o programa**. Minimizada ou atrás do jogo, ela continua aberta e o programa segue trabalhando. Um segundo clique com ele já aberto apenas abre outra janela.

## Primeira vez

1. **Carga inicial.** Assim que abre, o programa baixa a lista de anúncios e começa a ler, em segundo plano, os itens de cada conta. Cada conta é lida uma vez só. Com cerca de 1.500 anúncios, a carga inicial leva por volta de 1 h 45 com as configurações padrão, num ritmo que não sobrecarrega o site. Com a pausa de 1 s e 2 contas lidas ao mesmo tempo (⚙ Configurações), cai para uns 45 min. O que já foi lido fica salvo: se fechar no meio, ele continua de onde parou. A barra no topo mostra o progresso.
2. **O que é lido primeiro:**
   - contas novas ou que baixaram de preço;
   - contas que têm itens da sua tabela de valores (o programa descobre quais são pela busca do próprio site, em menos de 1 s);
   - o restante, das mais baratas para as mais caras.
3. **Cadastre seus valores.** Na aba **Tabela de valores**, digite "cosmos", escolha a faixa de refino e informe o valor em kk ou bi.
4. **Monte uma busca.** Na aba **Contas**, monte os filtros e clique em **Salvar busca e me avisar**.

Nos outros PCs, os passos 3 e 4 não são necessários: os valores, as buscas e as configurações chegam pelo git.

## Em mais de um PC

A tabela de valores, as buscas salvas, os grupos de itens e as ⚙ Configurações ficam no arquivo **`meus-dados.json`**, que vai pelo git junto com o programa. Você configura uma vez, e todos os PCs usam os mesmos dados.

- **Onde você mudou algo:** o programa grava no `meus-dados.json` a cada mudança. Para levar aos outros PCs, envie o arquivo:
  ```
  git add meus-dados.json
  git commit -m "Meus dados"
  git push
  ```
- **No outro PC:** rode `git pull` e abra o programa. Se ele já estiver aberto, a mudança aparece em poucos segundos.
- **O que fica em cada PC:**
  - as contas lidas do site: cada PC lê as suas, começando pelas que têm itens da sua tabela;
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
- **Grupos de itens:** juntam itens que você busca juntos, como as armas de um rank.
  - **Criar e editar:** pelo link **grupos**, ao lado do "Tem pelo menos um". Na janela você cria um grupo, dá um nome e adiciona os itens.
  - **Usar:** ao adicionar uma condição, no "Tem item" ou no "Tem pelo menos um", os grupos aparecem antes dos itens. Com a caixa vazia aparecem todos. Escolha o grupo em vez de pôr item por item.
  - **Como vale na busca:** qualquer item do grupo atende à condição, com o mesmo refino mínimo, quantidade e onde.
  - **Mudanças:** um grupo alterado passa a valer em todas as buscas salvas que o usam.
  - **No outro PC:** os grupos vão no `meus-dados.json`.
  - **Já criados:** **Armas UP4** (as 21 armas com Nível de Ataque +70) e **Armas UP3** (as 32 com +40). O UP3 inclui também as outras armas de Rank 9 com +40, como o Atirador Nebuloso.
- **Lista:** ordenada por lucro, em R$ ou %, com a marca **NOVA** para contas das últimas 24 h. Embaixo do preço aparece, pequeno, o lance mínimo que o site aceita: 70% do preço pedido (também nos detalhes). Contas que ainda não foram lidas, mas que a busca do site diz terem o item, aparecem como **A CONFIRMAR**.
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
- **Painéis:** as divisórias ⋮ podem ser arrastadas, e o botão ⟩ recolhe os detalhes (a lista ganha as colunas Céu e Valor). Use ↑ e ↓ para percorrer a lista.

**Tabela de valores**
- **É global:** cada item é cadastrado uma vez e vale para todas as contas, as de hoje e as futuras.
- **Sugestões:** vêm do catálogo do site (disponível desde o primeiro minuto) e de tudo o que já foi visto nas contas: materiais, pedras e cartas. Um item que ainda não apareceu pode ser cadastrado pelo nome; o valor passa a contar quando o item surgir.

![Tabela de valores com o cadastro de um item](docs/telas/tabela-de-valores.png)

**Buscas e avisos**
- Buscas salvas com "me avisar", preço máximo, lucro mínimo (R$ ou %) e quantas contas batem agora. Exemplo: avisar sempre que aparecer uma conta com um ou mais itens escolhidos por até 5.000 TCC. O preço aceita "5k". Ele é o mesmo "Preço máximo" dos filtros, então vale também para a lista da busca.
- Histórico dos avisos. Clicar num aviso abre a conta.

**⚙ Configurações**

| Opção | O que faz |
|---|---|
| Intervalo de consulta | De quanto em quanto tempo a lista é consultada. Padrão 60 s, mínimo 30 s. |
| Pausa entre contas | Intervalo entre a leitura de uma conta e a próxima. Padrão 2 s, mínimo 1 s. |
| Contas lidas ao mesmo tempo | 1 (padrão) ou 2. Com 2, a carga inicial leva ~40% menos tempo, mas o site recebe o dobro de acessos. Se ele recusar algum (HTTP 403, 429 ou 503), o programa volta sozinho para 1 e avisa no topo. |
| Cotações | Quanto vale 1 bi e 1 TCC em reais. Padrão: 1 bi = R$ 500 e 1 TCC = R$ 1. |
| Avisos | Notificação do Windows (clicar abre o anúncio para comprar), bipes (tocam mesmo com o "Não perturbe" ligado, por exemplo durante o jogo), abrir no navegador, Telegram e Discord (estes dois ficam só no PC em que foram configurados). O botão "Testar avisos" confere se estão funcionando. |

![Configurações](docs/telas/configuracoes.png)

## Como o valor é calculado

- Cada linha da tabela vale **por unidade**, em kk (1 bi = 1.000 kk).
- **Faixas de refino:** com várias faixas do mesmo item, vale a maior que o item atinge. Com Cosmos +10 = 3 bi e +12 = 6 bi, um Cosmos +12 conta 6 bi.
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
| `mercado/` | Código: leitura do site, banco, cálculo, coletor, avisos, servidor local e interface (`mercado/ui`). |
| `meus-dados.json` | Sua tabela de valores, buscas, grupos de itens e configurações. Vai pelo git para os outros PCs (veja "Em mais de um PC"). |
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
- **Ritmo:** o programa só lê páginas públicas do marketplace. Mantenha o intervalo e a pausa em valores razoáveis.
- **Se o site mudar:** se o layout do marketplace mudar, a leitura pode falhar. Nesse caso aparece um aviso no topo da janela e nada do que já foi guardado é apagado.
