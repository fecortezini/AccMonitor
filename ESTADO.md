# Estado do projeto

*Atualizado em 23/09/2026.*

## O projeto

O **Mercado PW** é um programa de PC que acompanha o Marketplace The Classic (PW 1.8.7). Ele lista todas as contas anunciadas, calcula quanto cada uma vale pela sua **tabela de valores** e mostra as maiores barganhas (valor dos itens − preço). Também avisa na hora quando aparece uma conta nova, ou mais barata, que bate com uma busca salva.

- **Tecnologia:** Python puro (nada para instalar), com a interface em HTML/JS aberta numa janela própria do Edge.
- **Detalhes:** o funcionamento está no [README](README.md), e o desenho completo em [docs/superpowers/specs](docs/superpowers/specs/2026-09-21-mercado-pw-design.md).

## Onde estamos

**A primeira versão está pronta e testada.** Tudo o que o desenho aprovado previa foi implementado:

- **Leitura do site:** lista de anúncios, itens de cada conta (inclusive pedras engastadas), catálogo de equipamentos e a busca avançada do próprio site.
- **Banco local (SQLite):** contas, itens, tabela de valores global, buscas salvas e avisos.
- **Cálculo do valor:**
  - faixas de refino, onde vale a maior faixa atingida;
  - quantidade × valor por unidade;
  - cotação do bi e do TCC em R$;
  - lucro e % de desconto.
- **Coletor em segundo plano:** consulta a lista a cada 60 s (configurável) e lê as contas numa fila. Primeiro as novas e as que baixaram de preço, depois as que têm itens da tabela, depois o resto.
- **Avisos:** notificação do Windows, bipes, navegador, Telegram e Discord, sem repetir.
- **Interface:** três abas (Contas, Tabela de valores, Buscas e avisos) mais as configurações, seguindo os mockups aprovados.
- **Janela própria:** o Edge abre em modo aplicativo, e fechar a janela encerra o programa.

**Melhorias depois da primeira versão:**
- **Botão Sincronizar (25/09):** no topo. Manda para o GitHub o que mudou no `meus-dados.json` e traz o que mudou no outro PC, pelo git da pasta (`mercado/sincronia.py`).
  - **Os dois PCs mudaram:** os dados se juntam item a item. Valores, buscas e grupos são comparados pelo id e configurações pela chave, e no mesmo item fica a versão mais recente. Não sobra conflito do git.
  - **Quando não mexe no git:** com mudanças no código sem commit, fora do `main` ou com commits dos dois lados. Nesses casos ele explica o que falta.
  - **Se o envio falha:** o commit é desfeito e os dados ficam para a próxima.
  - **Ponto dourado:** mudanças daqui ainda não enviadas.
  - **Versão nova do programa:** se chegar uma, pede para fechar e abrir de novo.
- **Lances (25/09):** a lista mostra embaixo do preço o maior lance que a conta recebeu, e os detalhes mostram "N lances · maior: X". Vem do botão "Fazer lance" da página da conta (`data-bid-pending` e `data-bid-highest`), sem login.
  - **Ritmo:** as 50 primeiras contas da busca e a conta aberta são relidas a cada 1 min (mais espaçado se forem muitas, até 10 páginas por minuto). As outras, uma a cada 30 s.
  - **Lance novo:** maior valor ou mais lances do que da última vez; fica verde por 30 min e vai para o log.
- **Combos de cartas (26/10):** no "Tem item", um grupo passa a exigir **todos** os itens dele. No "Tem pelo menos um", continua bastando um.
  - **Grupos criados:**
    - **Combo Seis Soberanos** (combo A): Imperador Locen, Senhora da Noite, Gorath, Imperador Chigo, Imperador Aohe e Asa Espectral.
    - **Combo Portal de Nuema** (combo S): Althea, Kestra, Astrid, Lorelei, Saki e Tensa.
    - Em cada combo, uma carta de cada tipo: Destruidor, Batalha, Durabilidade, Alma Primordial, Vida Primordial e Longevidade.
  - **Como foram achados:** o tooltip das cartas no site não serve. Todas as cartas, até as de nível C, mostram "Seis Soberanos da Chama da Vela (6)".
    - **Seis Soberanos:** saiu das descrições das cartas A. São os seis "Soberanos de Morai" (Leste, Norte, Central, Oeste, Sul e Superior), servos de Aurogon, que em chinês é 烛龙, o "Dragão da Vela".
    - **Portal de Nuema:** passado pelo usuário.
  - **Na prática (663 contas lidas):** 204 contas têm o Seis Soberanos completo e 431 o Portal de Nuema. As cartas ficam quase sempre equipadas. Para só as contas com as 6 equipadas, use "onde: equipado".
  - **Busca do site (contas ainda não lidas):** ela junta vários itens com OU. Para o grupo no "Tem item", o programa busca cada item e fica só com as contas que aparecem em todas as buscas.
- **Grupo Runas Nv. 5+ (26/10):** criado pela API, com as 45 runas de nível 5 a 10 conhecidas. São 5 cores × níveis 5 a 10 (ids 52179–52184, 52189–52194, 52199–52204, 52209–52214, 52219–52224), mais as variantes "Nv. 5" 200359–200363, "Nível 7" 69801–69805 e "Nível 8" 69808–69812. O "Pacote Runa Nível 5" ficou de fora.
  - **O nível está no nome:** cada nível é um item com id próprio, sem refino. A página da conta mostra as runas na aba Habilidades, cada uma na habilidade em que está ("Equipada em …").
  - **É para o "Tem pelo menos um".** A busca do site não conhece runas, então as contas não lidas não aparecem "a confirmar".
  - **Na prática (1.621 contas lidas):** 1.110 têm runa de nível 5+, 786 de 8+, 404 de 9+ e 337 de nível 10. As de nível 5 e "Nível 8" são comuns.
  - **Runas Nv. 10:** a pedido do usuário, ficou também um grupo só com as 5 de nível 10 (52184, 52194, 52204, 52214, 52224). Às 14:02 eram 350 contas lidas.
- **Grupos trazidos do GitHub (26/10):** do commit 2345589 (origin/main) vieram só os grupos R8 UP3 e R9 UP1/UP2/UP3, a pedido do usuário. O UP3 ficou de fora.
  - **Como:** com a mesma junção do Sincronizar (`sincronia.juntar`). A base é o HEAD (4eb08ff) e o "remoto" é ele mais os 4 grupos. O HEAD não andou, porque o `meus-dados.json` e o README tinham mudanças locais que conflitariam num `git pull`.
  - **Ids:** os 4 grupos ficaram com os ids do GitHub (8 a 11). Os criados aqui hoje foram renumerados: Combo Seis Soberanos 12, Combo Portal de Nuema 13, Runas Nv. 5+ 14 e Runas Nv. 10 15. A busca salva foi junto. O id 7 ficou livre para o UP3 do GitHub, e a próxima sincronia só acrescenta o UP3, sem renumerar nem duplicar (simulado).
- **Grupos de itens (24/09):** juntam itens buscados juntos, como as armas de um rank.
  - **Na busca:** o grupo vira uma condição só, que vale para qualquer item dele. Funciona no "Tem item" e no "Tem pelo menos um", e escolher item por item continua possível.
  - **Criar e editar:** pelo link "grupos", no painel de filtros.
  - **Outro PC:** os grupos vão no `meus-dados.json`.
  - **Criados para você:** **Armas UP4** (21 armas com "Nível de Ataque +70") e **Armas UP3** (32 com "+40").
    - **Como foram achadas:** pelos tooltips das armas lidas nas contas. Todas as armas ★★★ do catálogo do site aparecem em alguma conta, então as listas estão completas.
    - **UP3:** tem os pares das UP4 (a mesma arma um nível abaixo, com o id anterior) e as outras armas de Rank 9 com +40 (Atirador Nebuloso e outras da série 3298x, Fúria da Lua Brilhante, Destruidor Solar, Perdão Divino, Elo de Destinos Celeste).
- **Tem pelo menos um (24/09):** um filtro novo embaixo do "Tem item". A conta precisa ter pelo menos um dos itens, não todos. Serve, por exemplo, para a arma de um rank, que tem um nome em cada classe.
  - **Campos:** os mesmos do "Tem item".
  - **Onde aparece:** na aba Pesquisados dos detalhes, num grupo próprio que mostra qual dos itens a conta tem. Na lista não vira coluna nem entra no Por un.
  - **Onde mais vale:** nas buscas salvas, nos avisos e na fila do coletor.
- **Programa fechando sozinho (24/09):** a janela sumia de tempos em tempos.
  - **O que o programa fazia:** fechava o Edge à força quando a página passava 10 min sem mandar o sinal de "estou aberta" (a cada 15 s), mesmo com a janela aberta. É a única saída automática do programa. Não houve falha do Edge, atualização nem suspensão do Windows nos horários dos fechamentos, e o coletor trabalhava normalmente até o último segundo.
  - **Agora:** o programa segue aberto enquanto o Edge tiver a janela, mesmo minimizada ou atrás do jogo, olhando as janelas pela API do Windows. O sinal só vale no navegador padrão, quando o Edge não é encontrado.
  - **Log:** o `mercado.log` registra o motivo de cada encerramento ("Encerrando porque …") e quando a página passa 10 min sem sinal com a janela aberta.
  - **Ainda sem confirmar:** por que a página parava de mandar o sinal. Em teste, uma janela minimizada mandou o sinal normalmente por 13 min. A suspeita é o Edge parar páginas escondidas.
- **Mesmos dados em todos os PCs (23/09):** a tabela de valores, as buscas e as ⚙ Configurações ficam no `meus-dados.json`, que vai pelo git. Assim, não é preciso configurar tudo de novo em outro PC.
  - **Como funciona:** o programa grava no arquivo a cada mudança. Quando ele muda por fora (`git pull`), o programa percebe ao abrir, ou em até 3 s se já estiver aberto.
  - **Fica em cada PC:** as contas lidas, o histórico de avisos, a largura dos painéis e o Telegram e o Discord (para os tokens não irem para o git).
  - **Por que não o banco inteiro:** o `mercado.db` tem 112 MB, acima do limite de 100 MB do GitHub, e muda a cada consulta. Um PC novo lê as contas sozinho em ~1 h, começando pelas que têm itens da tabela.
  - **O banco do PC NOT-LAB04 é o oficial:** o `meus-dados.json` foi gerado dele em 23/09, com 23 valores e 3 buscas. Num PC que já tinha dados, eles são trocados pelos do arquivo na primeira abertura, e os antigos ficam em `meus-dados.anterior.json`.
  - **Conflito no git:** o programa não grava por cima do arquivo. Uma faixa no topo avisa até o conflito ser resolvido ou o arquivo apagado.
- **Itens pesquisados (21/09):** com condições de item:
  - a lista mostra quantas unidades de cada item a conta tem (coluna Pesquisados);
  - dá para ordenar por mais itens, por um item específico ou por menor preço por unidade;
  - ao adicionar o primeiro item, a lista já ordena por quem tem mais;
  - os detalhes ganham a aba Pesquisados.
- **Ordenar pela coluna (21/09):** clicar no título Preço, Por un., Pesquisados, Valor ou Lucro ordena a lista.
- **Ordem dos itens (22/09):**
  - os itens ficam na ordem em que são escolhidos, que serve para indicar a importância. As colunas da lista e a aba Pesquisados seguem essa ordem. A ordem alfabética foi testada e descartada por esconder essa escolha;
  - essa ordem não muda quais contas batem nem o Por un., que usa a soma de todos os itens. Um teste garante isso;
  - corrigido o "Limpar" numa janela aberta sem filtros guardados: ele trazia de volta os itens em vez de limpar.
- **Leitura mais rápida (22/09):** a conexão com o site é reaproveitada de uma página para a próxima, em vez de abrir uma nova a cada conta. No site real, cada página caiu de ~1,4 s para ~0,85 s. Com um proxy configurado no Windows, o programa continua abrindo uma conexão por página.
  - **Onde vai o tempo de cada conta (medido):** ~1 s o servidor montando a página, ~0,6 s de transferência, ~0,1 a 0,2 s para ler o HTML e ~40 ms no banco, mais a pausa configurada.
- **Contas lidas ao mesmo tempo (22/09):** nova opção nas ⚙ Configurações, 1 (padrão) ou 2.
  - **Como funciona:** com 2, o coletor baixa as duas próximas contas da fila juntas (a segunda numa thread ajudante, com a própria conexão) e faz a pausa depois das duas.
  - **Medido no site real, com pausa de 1 s:** 2,2 s por conta lendo uma por vez e 1,3 s lendo duas.
  - **Se o site recusar:** com a opção em 2, uma resposta 403, 429 ou 503 faz ela voltar sozinha para 1, e aparece um aviso no topo.
  - **Risco de bloqueio (avaliado em 22/09):** o site não tem `robots.txt`, serviço anti-robô nem cabeçalhos de limite de acesso, e não recusou nenhuma das ~1.260 contas lidas até então. Com 2, são ~45 páginas por minuto: dá para notar nos registros do servidor, mas é bem menos do que as proteções automáticas costumam barrar.
  - **Até 8 (26/10):** o máximo subiu de 2 para 8, para testar até onde o site aceita. Se ele recusar, o aviso do topo e o `mercado.log` dizem com quantas contas ao mesmo tempo foi.
  - **Resultado do teste (26/10): o site bloqueou o IP três vezes, por 1 h cada.** O 2º começou às 10:32 e liberou perto das 11:32. O programa tentou às 11:07, no meio dele, e isso não aumentou o bloqueio.
    - **Como o bloqueio aparece:** primeiro "read operation timed out", depois nenhuma conexão (WinError 10060). Todo o theclassic.games para de responder, mas o ping continua. Não vem nenhum HTTP 403/429/503, então a volta automática para 1 não dispara.
    - **1º bloqueio:** 8 ao mesmo tempo com pausa de 2 s. Foram 573 contas em 12 min (~47/min).
    - **2º bloqueio:** 4 ao mesmo tempo, com pausa de 2 s por 11 min (570 contas, ~52/min) e depois de 1 s (~75/min). Foi bloqueado 1 min e meio depois de passar para 1 s.
    - **3º bloqueio (14:00):** o programa foi aberto às 13:31 com 1 ao mesmo tempo e pausa de 2 s (~17/min). Às 13:53 passou para 2 (~31/min). Foram ~572 contas em 29 min, mais ~25 consultas da lista. De fora do programa, só 1 página (a de uma conta, às 13:51).
    - **Conclusão:** não é a velocidade. Os três bloqueios vieram depois de **~600 a 650 acessos** desde o fim do bloqueio anterior, em 18, 15 e 29 min. No 3º, os últimos 15 min tiveram só ~330 páginas, então a janela de contagem é de pelo menos 30 min, talvez 1 h. Parece um fail2ban: N acessos numa janela, bloqueio de 1 h.
    - **Lances:** depois da carga inicial, a releitura de lances baixa até 12 páginas por minuto (10 das contas na tela e 1 das outras a cada 30 s). São até 720 por hora, acima desse limite se a janela for de 1 h. Durante a carga ela não roda, só com a fila vazia.
    - **O servidor:** monta uma página em 0,4 a 0,6 s, mas com várias ao mesmo tempo cada uma demora mais (1,4 a 1,7 s). Cada página tem ~1,2 MB de HTML (~120 KB compactados).
- **Tempo que falta (26/10):** a barra "Lendo as contas" mostra quanto falta para ler a fila, no ritmo dos últimos 5 min, por exemplo "faltam ~36 min (33 por minuto)". Com menos de 1 min de leitura, aparece "calculando quanto falta". O ritmo é calculado no `Estado` do coletor (`por_minuto`, em `/api/estado`).
- **Busca do site para cartas (26/10):** conferida com a Althea. Entre as 702 contas lidas, ela achou exatamente as 521 que têm a carta, em qualquer lugar da conta. Por isso as contas não lidas de um combo, que aparecem "a confirmar", são praticamente certas.
- **Lance mínimo (22/09):** embaixo do preço, na lista e nos detalhes, aparece pequeno o lance mínimo: 70% do preço pedido, fixo e arredondado para cima. *Em 24/09:* o Por un. também ganhou embaixo o preço por unidade com o lance mínimo, e a aba Pesquisados dos detalhes também.
- **Aviso por preço (21/09):** a janela "Salvar busca" tem "só avisar se o preço for de até … TCC" (aceita "5k"), além do lucro mínimo.
- **Detalhes (21/09):** "De onde vem o valor" foi para o fim do painel, depois dos itens e dos botões.
- **Lista alinhada (21/09):** o preço por unidade virou a coluna Por un., e a soma e cada item pesquisado ganharam colunas próprias. Os números de cada coluna têm as mesmas casas decimais, e cada título fica alinhado com os seus valores.
- **Busca por parte do nome (21/09):** o "Tem item" aceita parte do nome, inclusive de itens ainda não vistos nas contas lidas. Exemplo: "pedra do dem" no começo da carga, quando só as contas baratas foram lidas. Outro exemplo: "relíquia maravilha", que soma as três relíquias.

**Testes:**
- **Automáticos:** 138, com páginas reais do site salvas. A sincronia é testada com git de verdade: um "GitHub" numa pasta e dois clones. Todos passam.
- **Interface:** o `tests/interface/testar_interface.mjs` clica nos elementos num Edge invisível e salva prints. Rodou sem erros na primeira versão. Depois das melhorias, as telas foram conferidas num Edge invisível com um script avulso, porque o PC onde foram feitas não tem Node. Esse script cobriu os passos do teste antigo e os novos, sem erros. Em 22/09 o teste rodou de novo, com Node, e passou sem erros.
- **Com o site de verdade:** leu 1.523 anúncios. Depois que cadastrei o Cosmos na tabela, as contas com Cosmos foram lidas primeiro e mostraram valor e lucro.
- **Janela real:** abre, e ao fechar o programa encerra em ~2 s.

**Situação dos dados:** a tabela de valores, as buscas e as configurações estão no `meus-dados.json`, no git. O `mercado.db` fica fora do git: cada PC tem o seu, e num PC novo o programa começa a ler as contas do zero.

## O que falta

**Conferir na prática** (nunca foi confirmado visualmente):
1. **Notificação do Windows e bipes:** abra ⚙ Configurações → **Testar avisos**.
2. **Carga inicial completa (~2 h):** já rodou até o fim no PC NOT-LAB04: em 23/09 eram 1.791 contas lidas e um `mercado.db` de 112 MB (605 mil itens). Falta ver se a busca e a lista continuam rápidas com tudo lido.
3. **Aviso de verdade:** até agora só foi testado com anúncios simulados. Falta ver acontecer com uma conta nova real no site, depois de salvar uma busca com "me avisar".
4. **Telegram e Discord:** nunca foram testados com um token ou webhook de verdade.
5. **Dados em outro PC:** depois do `git pull`, abrir o programa no outro PC e ver a tabela, as buscas e as configurações chegarem.
6. **Fechamento sozinho:** com a versão nova, ver se o programa ainda fecha sozinho. Se fechar, o `mercado.log` diz o motivo.

**Seu trabalho no programa:**
7. Cadastrar os valores reais na Tabela de valores (ex.: Cosmos +10 = 3 bi) e ajustar a cotação do bi e do TCC.

**Ideias para depois** (nada começado; conversar antes):
- Usar o histórico de vendas do site (`/history`) para sugerir valores e preços típicos.
- Avisar com a janela fechada, por um ícone perto do relógio. Foi a opção C no brainstorming e ficou de fora.
- Gerar um `.exe` para não depender do Python instalado.
- Apagar o `helper.py`, o `filtros.toml` e o `iniciar.bat` (a versão antiga de linha de comando) quando o programa novo estiver validado.

## Como retomar em outro PC

```
git clone https://github.com/fecortezini/Classic187AccountMonitor.git
cd Classic187AccountMonitor
```

- **Requisitos:** Python 3.11+ e Microsoft Edge. Node 22+ só é necessário para o teste de interface.
- **Abrir o programa:** dois cliques em `Mercado PW.bat`.
- **Rodar os testes:**
  - automáticos: `py -m unittest discover -s tests -t .`
  - interface: `py -m mercado --sem-janela --porta 8765` e, em outro terminal, `node tests/interface/testar_interface.mjs`
- **Dados:** a tabela de valores, as buscas, os grupos e as configurações vão e vêm pelo botão **Sincronizar**, no topo. Ou pelo git: `git pull`, e `git add meus-dados.json`, `git commit` e `git push`. As contas o programa lê sozinho em cada PC (o `mercado.db`, fora do git).

## Mapa do código

| Arquivo | Responsabilidade |
|---|---|
| `mercado/site.py` | Lê o HTML e o JSON do marketplace. |
| `mercado/banco.py` | SQLite: gravação, busca com filtros, tabela de valores, buscas e avisos. Sincroniza o `meus-dados.json`. |
| `mercado/valor.py` | Regras do cálculo de valor e lucro. |
| `mercado/coletor.py` | Consultas periódicas, fila de leitura e disparo dos avisos. |
| `mercado/avisos.py` | Canais de aviso. |
| `mercado/servidor.py` | API local usada pela interface. |
| `mercado/sincronia.py` | Botão Sincronizar: o `meus-dados.json` com o GitHub, juntando os dados item a item. |
| `mercado/ui/` | Interface (`index.html`, `app.css`, `app.js`). |
| `mercado/__main__.py` | Abre tudo e a janela do Edge. |
| `tests/` | Testes automáticos, páginas reais salvas e o teste de interface. |
