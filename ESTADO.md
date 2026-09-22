# Estado do projeto

*Atualizado em 21/09/2026.*

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
- **Lance mínimo (22/09):** embaixo do preço, na lista e nos detalhes, aparece pequeno o lance mínimo: 70% do preço pedido, fixo e arredondado para cima.
- **Aviso por preço (21/09):** a janela "Salvar busca" tem "só avisar se o preço for de até … TCC" (aceita "5k"), além do lucro mínimo.
- **Detalhes (21/09):** "De onde vem o valor" foi para o fim do painel, depois dos itens e dos botões.
- **Lista alinhada (21/09):** o preço por unidade virou a coluna Por un., e a soma e cada item pesquisado ganharam colunas próprias. Os números de cada coluna têm as mesmas casas decimais, e cada título fica alinhado com os seus valores.
- **Busca por parte do nome (21/09):** o "Tem item" aceita parte do nome, inclusive de itens ainda não vistos nas contas lidas. Exemplo: "pedra do dem" no começo da carga, quando só as contas baratas foram lidas. Outro exemplo: "relíquia maravilha", que soma as três relíquias.

**Testes:**
- **Automáticos:** 81, com páginas reais do site salvas. Todos passam.
- **Interface:** o `tests/interface/testar_interface.mjs` clica nos elementos num Edge invisível e salva prints. Rodou sem erros na primeira versão. Depois das melhorias, as telas foram conferidas num Edge invisível com um script avulso, porque o PC onde foram feitas não tem Node. Esse script cobriu os passos do teste antigo e os novos, sem erros. Em 22/09 o teste rodou de novo, com Node, e passou sem erros.
- **Com o site de verdade:** leu 1.523 anúncios. Depois que cadastrei o Cosmos na tabela, as contas com Cosmos foram lidas primeiro e mostraram valor e lucro.
- **Janela real:** abre, e ao fechar o programa encerra em ~2 s.

**Situação dos dados:** o `mercado.db` fica fora do git e foi apagado depois dos testes. Na primeira abertura o programa começa do zero.

## O que falta

**Conferir na prática** (nunca foi confirmado visualmente):
1. **Notificação do Windows e bipes:** abra ⚙ Configurações → **Testar avisos**.
2. **Carga inicial completa (~2 h):** nunca rodou até o fim. Vale ver como a busca, a lista e o tamanho do `mercado.db` se comportam com as ~1.500 contas lidas.
3. **Aviso de verdade:** até agora só foi testado com anúncios simulados. Falta ver acontecer com uma conta nova real no site, depois de salvar uma busca com "me avisar".
4. **Telegram e Discord:** nunca foram testados com um token ou webhook de verdade.

**Seu trabalho no programa:**
5. Cadastrar os valores reais na Tabela de valores (ex.: Cosmos +10 = 3 bi) e ajustar a cotação do bi e do TCC.

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
- **Dados:** cada PC tem o próprio `mercado.db`, com as contas lidas, a tabela de valores e as buscas. Para levar os dados de um PC para outro, copie esse arquivo com o programa fechado.

## Mapa do código

| Arquivo | Responsabilidade |
|---|---|
| `mercado/site.py` | Lê o HTML e o JSON do marketplace. |
| `mercado/banco.py` | SQLite: gravação, busca com filtros, tabela de valores, buscas e avisos. |
| `mercado/valor.py` | Regras do cálculo de valor e lucro. |
| `mercado/coletor.py` | Consultas periódicas, fila de leitura e disparo dos avisos. |
| `mercado/avisos.py` | Canais de aviso. |
| `mercado/servidor.py` | API local usada pela interface. |
| `mercado/ui/` | Interface (`index.html`, `app.css`, `app.js`). |
| `mercado/__main__.py` | Abre tudo e a janela do Edge. |
| `tests/` | Testes automáticos, páginas reais salvas e o teste de interface. |
