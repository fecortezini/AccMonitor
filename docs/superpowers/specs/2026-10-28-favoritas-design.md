# Favoritas: desenho

**Data:** 2026-10-28
**Status:** aprovado (28/10), em implementação
**Base:** o desenho do programa em `2026-09-21-mercado-pw-design.md`

## 1. Objetivo

Marcar contas como **favoritas** e deixar o programa acompanhando cada uma. Ele avisa quando uma favorita:

1. **sai do mercado**, na hora, e depois diz o motivo: **vendida** (com o preço final) ou **retirada** pelo vendedor;
2. **baixa de preço**;
3. **recebe um lance novo**;
4. **volta ao mercado** depois de retirada.

**Uma conta vendida é esquecida** *(pedido do usuário, 28/10)*: depois do aviso de vendida, ela deixa de ser favorita (nos dois PCs, pelo Sincronizar), e a situação e os itens guardados dela são apagados. Só o aviso fica nos "Últimos avisos". Se o comprador anunciar a conta de novo, ela aparece na lista como qualquer outra, e não como favorita.

### Critérios de sucesso

- Marcar ou desmarcar com um clique, na lista de contas ou nos detalhes.
- O aviso "saiu do mercado" chega na consulta da lista seguinte à saída (até "intervalo de consulta + ~5 s").
- Uma venda é confirmada em ~1 a 2 min depois de a conta sumir. Uma retirada é confirmada em 10 min.
- Nenhuma favorita vira "retirada" por falha de conexão ou bloqueio do site.
- As favoritas valem nos dois PCs (pelo Sincronizar), e os detalhes de uma favorita retirada continuam abrindo com os itens.
- O acompanhamento acrescenta no máximo 1 ou 2 páginas por favorita que some. Os lances não aumentam o total de acessos.

### Fora do escopo

- Guardar o histórico de vendas de todas as contas, ou sugerir valores a partir dele. Continua como ideia para depois no ESTADO.md.
- Avisar quando o preço sobe.
- Anotações em cada favorita.
- Descobrir uma venda feita enquanto este PC estava fechado se, quando ele abre, a conta já foi anunciada de novo (ver seção 8).

## 2. O que o site mostra (conferido em 28/10/2026)

| Fonte | Endereço | O que traz |
|---|---|---|
| Histórico por nome | `GET /history?game=pw187&q={nome}&period=90&sort=recent` (HTML ~280 KB; ~27 KB compactado) | Na parte "Contas vendidas" (`id="mkh-panel-contas"`), uma linha `article.mkh-row--link` por venda: link `/pw187/vendida/{venda}`, nome (`.mkh-row__name`), preço (`.mkh-row__price`, ex.: "1.739 TCC") e data (`.mkh-row__date`, "dd/mm/aaaa hh:mm", horário de Brasília). O `q` filtra pelo nome. |
| Venda | `GET /pw187/vendida/{venda}` (HTML ~850 KB) | A conta como estava na venda. No cabeçalho: `<li class="power"><span>ID</span><strong>{roleid}</strong>`. No texto: "Vendida em dd/mm/aaaa hh:mm", o preço e "foi anunciada por N TCC e fechada por lance aceito". |

**O número da venda não é o id da conta.** A venda 47855 é da conta 344032. O id só aparece na página da venda.

**Comparação com o banco (40 vendas mais recentes):**
- 39 batem pelo nome com contas que o programa viu na lista.
- A conta sai da lista ~1 min antes de a venda aparecer no histórico (ex.: vista pela última vez às 13:41:32, vendida às 13:42).
- O preço final costuma ser menor que o anunciado, porque muitas vendas fecham por lance.
- Várias contas vendidas voltam ao mercado pelo comprador, mais caras. A TriGorda foi vendida por 42 e anunciada de novo por 100. A Bruxinha foi vendida duas vezes em 14 h.

## 3. Dados

### 3.1 No `meus-dados.json` (vai para os outros PCs)

Uma nova lista `favoritas`, uma linha por conta:

```json
{"id": 344032, "nome": "UP4-100ENTRADAS", "criado_em": "2026-10-28T13:30:00", "atualizado_em": "2026-10-28T13:30:00"}
```

- **`id`:** o id da conta (roleid).
- **`nome`:** usado na busca do histórico e para mostrar a favorita num PC que ainda não leu a conta. Ele é guardado ao marcar e não muda depois.
- **Formato do arquivo:** passa a ser **3** quando houver alguma favorita (`FORMATO_DADOS = 3`). Assim, um PC com o programa antigo recusa o arquivo e pede para atualizar, em vez de perder as favoritas. Sem favoritas, continua 1 ou 2 como hoje.
- **Junção do Sincronizar** (`sincronia.juntar`): as favoritas são comparadas pelo id, com as mesmas regras dos valores, das buscas e dos grupos, **com uma diferença**: se os dois PCs marcarem a mesma conta, fica uma só, com o `criado_em` mais antigo. O id é o da conta, então nunca é renumerado.
- **No banco:** tabela `favoritas (id INTEGER PRIMARY KEY, nome, criado_em, atualizado_em)`, sincronizada com o arquivo como as outras.

### 3.2 Só no banco de cada PC

Cada PC descobre sozinho a situação pelo site. Tabela `situacao_favoritas`:

| Campo | O que é |
|---|---|
| `id` | id da conta |
| `situacao` | `a_venda`, `confirmando` ou `retirada` (uma vendida é apagada, seção 4.2) |
| `desde` | quando entrou nessa situação |
| `sumiu_em` | quando o programa percebeu que ela saiu da lista |
| `visto_antes` | última vez vista na lista antes de sumir (o `ultimo_visto` do anúncio, ou o `criado_em` da favorita se este PC nunca a viu) |
| `tentativas`, `proxima_em` | buscas no histórico já feitas e quando fazer a próxima |

- **A ordem e o destaque da aba** usam o `desde`.
- **Quando ela volta ao mercado:** a situação volta a ser `a_venda`.
- **Ao desmarcar a favorita:** a linha da situação é apagada.

### 3.3 Avisos das favoritas

- **Onde ficam:** numa tabela própria, `avisos_favoritas (id, anuncio_id, evento, texto, quando)`.
- **Por que não a `avisos`:** o `UNIQUE (busca_id, anuncio_id, preco)` dela impediria dois avisos da mesma conta com o mesmo preço, como "saiu" e "vendida". Aqui, quem evita repetir um aviso é a própria mudança de situação.
- **Na interface:** os "Últimos avisos" da aba Buscas e avisos mostram as duas tabelas juntas, por data, e os das favoritas aparecem como "★ Favorita".

### 3.4 Itens guardados

- **Hoje:** o `limpar_antigos` apaga os itens das contas que saíram do ar há mais de 7 dias.
- **Com as favoritas:** ele passa a pular as favoritas, e os detalhes de uma retirada continuam abrindo com os itens.
- **Ao desmarcar:** a conta volta à regra normal.
- **Vendida:** os itens são apagados na hora, como o `limpar_antigos` faria.

## 4. Como descobrir o que aconteceu

### 4.1 Saiu da lista

- **Retorno do `atualizar_lista`:** passa a devolver os ids que sumiram, e não só quantos.
- **Para cada favorita que sumiu**, o coletor:
  1. muda a situação para `confirmando`, com `sumiu_em` = agora e `visto_antes` = o `ultimo_visto` anterior;
  2. avisa na hora: **"★ {nome} saiu do mercado, conferindo se foi vendida…"**;
  3. agenda a 1ª busca no histórico para 1 min depois. As seguintes são 3 min e 10 min depois de `sumiu_em`.

### 4.2 Busca no histórico

1. O coletor baixa `history?game=pw187&q={nome}&period=90&sort=recent`.
2. **Ele só considera** as linhas com o nome **exatamente igual** (o `q` pode trazer nomes parecidos) e data maior ou igual a `visto_antes` − 5 min. A folga cobre a data do site, que vem sem segundos, e a diferença de relógio. A data também impede de confundir com uma venda antiga da mesma conta, como as duas da Bruxinha.
3. **Para cada venda considerada**, da mais recente para a mais antiga, até 3, ele abre `/pw187/vendida/{venda}` e lê o ID:
   - **ID igual ao da conta:** ele avisa **"★ {nome} vendida por {preço} (anunciada por {anunciada}, lance aceito)"**. O "lance aceito" só aparece quando for o caso, e clicar no aviso abre a página da venda. Depois **esquece a conta**: ela sai das favoritas (e do `meus-dados.json`), e a situação e os itens dela são apagados.
   - **Venda direta:** a página da venda não tem o "foi anunciada por". Nesse caso, a anunciada é o próprio preço e não houve lance.
   - **ID diferente:** passa para a próxima venda.
4. **Nenhuma venda confirmada:**
   - antes da 3ª tentativa: `tentativas` + 1 e agenda a próxima;
   - na 3ª (10 min): a situação vira `retirada` e ele avisa: **"★ {nome} saiu do mercado sem venda"**.

**Ritmo:** essas páginas respeitam a pausa configurada (`pausa_s`) e passam na frente das contas da fila, porque são poucas. O agendamento fica no banco (`proxima_em`), então fechar e abrir o programa no meio não perde as tentativas.

### 4.3 Ao abrir o programa

- **Favoritas que estavam à venda ou sem situação** e não aparecem na primeira lista lida são tratadas como se tivessem acabado de sumir: `confirmando`, com as mesmas tentativas.
- **Diferença:** aqui não sai o aviso "saiu do mercado", só o do resultado. A saída aconteceu com o programa fechado, e o resultado vem logo em seguida.
- **Por que funciona:** o histórico guarda 90 dias. Uma conta vendida há dias é encontrada na 1ª tentativa.

### 4.4 Outros acontecimentos

| Acontecimento | De onde vem | Aviso |
|---|---|---|
| Baixou de preço | `baixaram` do `atualizar_lista` | ★ {nome} baixou de {antes} para {depois} |
| Voltou ao mercado | uma favorita em `confirmando` ou `retirada` que reaparece na lista (`reativados` do `atualizar_lista`) | ★ {nome} anunciada de novo por {preço}. As tentativas pendentes são canceladas. |
| Lance novo | `gravar_lance` devolve verdadeiro (maior valor ou mais lances) | ★ {nome}: {n} lances, maior {valor} |

- **Lances das favoritas:** elas entram no grupo relido de perto (`_lance_a_ler`), logo depois da conta aberta e antes das contas da busca na tela.
- **Ritmo dos lances:** vale o mesmo de hoje, a cada 1 min, com o intervalo crescendo para não passar de `LANCES_POR_MINUTO`. Como hoje, esse grupo só é relido com a fila de contas vazia, ou seja, depois da carga inicial.

### 4.5 Canais

- Os avisos usam os mesmos canais das buscas (Windows, bipes, navegador, Telegram e Discord), conforme as ⚙ Configurações.
- O título começa com "★".
- Clicar no aviso abre o anúncio, ou a página da venda no aviso de vendida.

## 5. Interface

- **Lista de contas:** uma coluna estreita com ☆/★ antes do nome. Clicar marca ou desmarca sem abrir os detalhes. A estrela fica dourada nas favoritas.
- **Detalhes:** um botão "☆ Favoritar" / "★ Favorita" no topo.
- **Aba ★ Favoritas (N):** a 4ª aba, depois de Buscas e avisos, com a lista à esquerda e os detalhes à direita, como na aba Contas.
  - **Colunas:** ★ (desmarca), Conta (nome, classe e nível), Preço (com o lance mínimo embaixo), Lances, Situação e Desde.
  - **Situação:** "À venda", "Confirmando venda…" ou "Retirada". Uma vendida some da aba depois do aviso.
  - **Ordem:** primeiro as em `confirmando`, depois por `desde`, da mais recente para a mais antiga.
  - **Destaque:** uma linha que mudou nos últimos 30 min fica destacada, como o lance novo na lista.
  - **Sem favoritas:** a aba explica como marcar ("clique na ☆ ao lado do nome de uma conta").
- **Situação nos detalhes:** os detalhes de uma favorita que saiu do ar mostram a situação no topo: "Confirmando se foi vendida…" ou "Retirada em 28/10 12:44, sem venda".
- **API:**
  - `GET /api/favoritas`: as favoritas com a situação e os dados do anúncio;
  - `POST /api/favoritas/{id}`: marca;
  - `DELETE /api/favoritas/{id}`: desmarca;
  - `/api/conta/{id}`: passa a trazer `favorita` e a situação.
- **Ao marcar:** o nome vem do anúncio no banco.

## 6. Erros

- **Sem conexão, tempo esgotado ou site bloqueando** (busca no histórico ou página da venda):
  - a tentativa não conta, e a próxima é marcada para 2 min depois;
  - a favorita continua em `confirmando` pelo tempo que for preciso, sem nunca virar `retirada` por isso;
  - a 3ª tentativa válida acontece no mínimo 10 min depois de `sumiu_em`.
- **Histórico em formato diferente:** se a página não tiver a parte "Contas vendidas" (`mkh-panel-contas`), conta como erro e não como "não achei". O `mercado.log` registra "o histórico do site mudou".
- **Página da venda sem ID:** conta como erro, do mesmo jeito.
- **No `mercado.log`:** cada passo é registrado: sumiu, procurou no histórico (quantas vendas consideradas), vendida ou retirada, e os avisos.

## 7. Testes

No mesmo estilo dos atuais, com páginas reais salvas em `tests/paginas`: `historico_bruxinha.html.gz` (busca por "Bruxinha", 2 vendas), `vendida_47855.html.gz` (lance aceito) e `vendida_47847.html.gz` (venda direta).

- **`test_site`:** ler o histórico (nome, número da venda, preço e data) e a venda (ID, preço, anunciada por, lance aceito e data). Uma página sem `mkh-panel-contas` dá erro.
- **`test_banco`:**
  - marcar, desmarcar e listar favoritas;
  - situação e agendamento;
  - `limpar_antigos` sem apagar os itens das favoritas;
  - `atualizar_lista` devolvendo os ids que sumiram.
- **`test_meus_dados`:** as favoritas no arquivo, com o formato 3 só quando houver alguma, e a recusa de um formato mais novo.
- **`test_sincronia`:**
  - os dois PCs marcando a mesma conta (fica uma só, sem renumerar);
  - marcar num PC e desmarcar no outro;
  - favoritas diferentes nos dois.
- **`test_coletor`, com um site falso:**
  - some → aviso "saiu" → 1ª busca acha → aviso de vendida, e a conta sai das favoritas, sem situação e sem itens;
  - 3 tentativas sem venda → `retirada` e aviso, com os tempos de 1, 3 e 10 min;
  - falha de conexão não conta como tentativa;
  - ID diferente faz testar a próxima venda;
  - venda com data anterior a `visto_antes` − 5 min é ignorada;
  - baixou de preço, voltou ao mercado depois de retirada e lance novo;
  - ao abrir, favorita que não está na lista vai para `confirmando` sem o aviso "saiu";
  - lances: favoritas entram no grupo relido de perto.
- **`test_servidor`:** as rotas novas e `favorita` em `/api/conta`.
- **Interface (`testar_interface.mjs`):** marcar pela estrela na lista, ver a aba Favoritas com a contagem, abrir os detalhes e desmarcar.

## 8. Limitações conhecidas

- **Se o comprador trocar o nome** da conta, a venda não é encontrada no histórico e ela aparece como `retirada`.
- **Venda e novo anúncio com este PC fechado:** se, quando ele abre, a conta já tiver sido vendida e anunciada de novo, ele vê só o preço novo. A venda do meio passa despercebida e ela continua favorita.
- **Horário:** as datas do site estão no horário de Brasília. O desenho supõe que o relógio do PC também está, como hoje.

## 9. Documentação

No fim, o README ganha a seção das favoritas, e o ESTADO.md a entrada da melhoria e os testes.
