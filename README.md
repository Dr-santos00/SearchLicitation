# GOVIA — Inteligência em Contratações Públicas

Sistema funcional de prospecção comercial baseado nos dados abertos do
**PNCP** (Portal Nacional de Contratações Públicas). Encontra licitações,
prioriza as que são **serviços** (sem necessidade de estoque) e calcula um
**GOV SCORE** de aderência para cada oportunidade.

**Custo de operação: R$ 0,00.**

| Peça | Serviço usado | Custo |
|---|---|---|
| Fonte de dados | API pública `pncp.gov.br/api/consulta` | Gratuita, sem chave/cadastro |
| Classificação | Regras por palavra-chave (Python puro) | Gratuita, sem IA paga |
| Interface | Streamlit (framework open-source) | Gratuita |
| Atualização automática | `streamlit-autorefresh` (open-source) | Gratuita |
| Exportação Excel | `openpyxl` (open-source) | Gratuita |
| Hospedagem | Streamlit Community Cloud | Gratuita (plano free) |

## Funcionalidades

- **Busca sem limite de profundidade:** percorre automaticamente todas as
  páginas disponíveis no PNCP para os filtros escolhidos (há apenas um teto
  de segurança interno contra travamentos, muito acima de qualquer volume
  real de resultados).
- **Foco em propostas com prazo em aberto:** consulta o endpoint do PNCP que
  traz especificamente contratações com o **período de apresentação de
  proposta ainda aberto** — não editais já encerrados.
- **Atualização automática:** com o interruptor "Atualização automática"
  ligado, o app repete a busca sozinho no intervalo escolhido (5 a 60 min),
  usando os mesmos parâmetros da última busca manual.
- **Notificação de mudanças:** a cada atualização (manual ou automática), o
  GOVIA compara com o resultado anterior e destaca oportunidades **novas**
  (🆕) e **alteradas** (✏️ — mudança de valor, situação, prazo ou score),
  com um aviso no topo da tela e uma notificação (toast).
- **Exportação em CSV e Excel:** os resultados podem ser baixados tanto em
  `.csv` quanto em `.xlsx` (abre diretamente no Excel/LibreOffice/Google
  Sheets).

---

## 1. Rodando localmente (para testar antes de publicar)

Pré-requisitos: Python 3.10+ instalado.

```bash
# 1. Entre na pasta do projeto
cd govia

# 2. (Recomendado) crie um ambiente virtual
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Instale as dependências (todas gratuitas/open-source)
pip install -r requirements.txt

# 4. Rode o app
streamlit run app.py
```

O navegador abrirá automaticamente em `http://localhost:8501`.

---

## 2. Publicando de graça na internet (Streamlit Community Cloud)

Isso deixa o GOVIA acessível por um link público, sem pagar nada.

1. Crie uma conta gratuita no [GitHub](https://github.com) (se ainda não tiver).
2. Crie um repositório novo (pode ser público ou privado) e envie os 3
   arquivos deste projeto: `app.py`, `requirements.txt`, `README.md`.
   - Pelo site do GitHub: "Add file" → "Upload files" → arraste os arquivos.
3. Acesse [streamlit.io/cloud](https://streamlit.io/cloud) e crie uma conta
   gratuita (pode entrar com o próprio GitHub).
4. Clique em **"New app"**, selecione o repositório que você criou, o branch
   (`main`) e o arquivo principal (`app.py`).
5. Clique em **Deploy**. Em 1–2 minutos o sistema estará no ar, em um link
   como `https://seu-usuario-govia.streamlit.app`.

Pronto: sistema completo, funcional, com link público, sem custo.

### Alternativas gratuitas de hospedagem (caso prefira)
- **Hugging Face Spaces** (suporta Streamlit no plano gratuito)
- **Render** (free tier de web service, com "sleep" após inatividade)
- Rodar localmente na sua própria máquina, sem publicar (uso interno)

---

## 3. Como o sistema consulta o PNCP

Usa o endpoint público **"Consultar Contratações com Período de Recebimento
de Propostas em Aberto"**:

```
GET https://pncp.gov.br/api/consulta/v1/contratacoes/proposta
    ?dataFinal=AAAAMMDD
    &codigoModalidadeContratacao={1-14}
    &uf={SIGLA}
    &pagina={n}
    &tamanhoPagina={até 500}
```

Não exige chave de API, login ou cadastro — é dado público, conforme a Lei
14.133/2021. O app varre cada combinação de UF × modalidade selecionada,
pagina os resultados e remove duplicados pelo `numeroControlePNCP`.

---

## 4. Como funciona o GOV SCORE (0–100)

Calculado **localmente, sem IA paga**, a partir de 5 componentes:

| Componente | Peso | Lógica |
|---|---|---|
| É serviço | 30 | Proporção de termos de serviço vs. produto encontrados no objeto da contratação |
| Não exige estoque | 25 | Penaliza a presença de termos típicos de fornecimento de produto físico |
| Valor dentro da faixa | 15 | Se o valor estimado está entre o mínimo/máximo definidos no perfil |
| Prazo disponível | 10 | Dias restantes até o encerramento do recebimento de propostas |
| Aderência ao perfil da empresa | 20 | Correspondência com as palavras-chave descritas pelo usuário |

Classificação: 🟢 80–100 alta prioridade · 🟡 60–79 média · 🔴 abaixo de 60
baixa prioridade.

### Personalizando a classificação

As listas `PALAVRAS_SERVICO` e `PALAVRAS_PRODUTO`, no topo de `app.py`, são
simples listas de texto — edite-as livremente para refletir o vocabulário do
seu segmento (ex.: adicionar termos técnicos específicos da sua área).

---

## 5. Limitações desta versão (e como evoluir)

- **Classificação por palavra-chave, não por IA semântica.** É gratuita e
  funciona bem para o objetivo de priorização, mas não interpreta contexto
  como um modelo de linguagem faria. Se quiser IA semântica no futuro, dá
  para plugar a API da Anthropic/OpenAI só na etapa de classificação
  (mantendo a busca e o restante do sistema gratuitos) — mas isso deixa de
  ser 100% gratuito.
- **Uma única UF/modalidade por chamada à API.** O PNCP não permite busca
  textual livre nem múltiplos filtros combinados numa única chamada; por
  isso o app faz várias chamadas (uma por combinação de UF × modalidade) e
  agrega os resultados, percorrendo todas as páginas de cada combinação.
  Para muitos estados + muitas modalidades a busca fica mais lenta — não há
  como evitar isso sem mudar a própria API do PNCP.
  Nota: caso a API mude parâmetros ou passe a exigir campos adicionais no
  futuro, será necessário ajustar `buscar_contratacoes_abertas()` em `app.py`
  de acordo com a documentação vigente do PNCP.
- **Atualização automática depende da aba estar aberta.** O mecanismo usado
  (`streamlit-autorefresh`) faz o navegador pedir uma nova execução do
  script periodicamente — funciona muito bem enquanto alguém está com o
  GOVIA aberto no navegador, mas **não** roda em segundo plano com a aba
  fechada, e não envia e-mail/SMS/push. Para monitoramento 24h mesmo com o
  app fechado, seria necessário um serviço adicional (ex.: GitHub Actions
  agendado consultando o PNCP direto + envio por SMTP gratuito) — não
  incluído nesta versão, pois muda a arquitetura de "app único" para
  "app + job agendado".
- **Sem persistência entre sessões.** O histórico de "novas/alteradas" existe
  apenas durante a sessão do navegador aberta; ao fechar a aba, a próxima
  visita começa do zero (sem base de comparação).
- **Sem cadastro de múltiplos clientes/consultorias.** A versão atual
  atende a um único perfil de prospecção por vez.

Esses pontos são exatamente os "próximos passos" caso você queira evoluir o
GOVIA para os planos Profissional/Intelligence/Enterprise descritos no
plano de negócio.
# GOVIA — Inteligência em Contratações Públicas

Sistema funcional de prospecção comercial baseado nos dados abertos do
**PNCP** (Portal Nacional de Contratações Públicas). Encontra licitações,
prioriza as que são **serviços** (sem necessidade de estoque) e calcula um
**GOV SCORE** de aderência para cada oportunidade.

**Custo de operação: R$ 0,00.**

| Peça | Serviço usado | Custo |
|---|---|---|
| Fonte de dados | API pública `pncp.gov.br/api/consulta` | Gratuita, sem chave/cadastro |
| Classificação | Regras por palavra-chave (Python puro) | Gratuita, sem IA paga |
| Interface | Streamlit (framework open-source) | Gratuita |
| Hospedagem | Streamlit Community Cloud | Gratuita (plano free) |

---

## 1. Rodando localmente (para testar antes de publicar)

Pré-requisitos: Python 3.10+ instalado.

```bash
# 1. Entre na pasta do projeto
cd govia

# 2. (Recomendado) crie um ambiente virtual
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Instale as dependências (todas gratuitas/open-source)
pip install -r requirements.txt

# 4. Rode o app
streamlit run app.py
```

O navegador abrirá automaticamente em `http://localhost:8501`.

---

## 2. Publicando de graça na internet (Streamlit Community Cloud)

Isso deixa o GOVIA acessível por um link público, sem pagar nada.

1. Crie uma conta gratuita no [GitHub](https://github.com) (se ainda não tiver).
2. Crie um repositório novo (pode ser público ou privado) e envie os 3
   arquivos deste projeto: `app.py`, `requirements.txt`, `README.md`.
   - Pelo site do GitHub: "Add file" → "Upload files" → arraste os arquivos.
3. Acesse [streamlit.io/cloud](https://streamlit.io/cloud) e crie uma conta
   gratuita (pode entrar com o próprio GitHub).
4. Clique em **"New app"**, selecione o repositório que você criou, o branch
   (`main`) e o arquivo principal (`app.py`).
5. Clique em **Deploy**. Em 1–2 minutos o sistema estará no ar, em um link
   como `https://seu-usuario-govia.streamlit.app`.

Pronto: sistema completo, funcional, com link público, sem custo.

### Alternativas gratuitas de hospedagem (caso prefira)
- **Hugging Face Spaces** (suporta Streamlit no plano gratuito)
- **Render** (free tier de web service, com "sleep" após inatividade)
- Rodar localmente na sua própria máquina, sem publicar (uso interno)

---

## 3. Como o sistema consulta o PNCP

Usa o endpoint público **"Consultar Contratações com Período de Recebimento
de Propostas em Aberto"**:

```
GET https://pncp.gov.br/api/consulta/v1/contratacoes/proposta
    ?dataFinal=AAAAMMDD
    &codigoModalidadeContratacao={1-14}
    &uf={SIGLA}
    &pagina={n}
    &tamanhoPagina={até 500}
```

Não exige chave de API, login ou cadastro — é dado público, conforme a Lei
14.133/2021. O app varre cada combinação de UF × modalidade selecionada,
pagina os resultados e remove duplicados pelo `numeroControlePNCP`.

---

## 4. Como funciona o GOV SCORE (0–100)

Calculado **localmente, sem IA paga**, a partir de 5 componentes:

| Componente | Peso | Lógica |
|---|---|---|
| É serviço | 30 | Proporção de termos de serviço vs. produto encontrados no objeto da contratação |
| Não exige estoque | 25 | Penaliza a presença de termos típicos de fornecimento de produto físico |
| Valor dentro da faixa | 15 | Se o valor estimado está entre o mínimo/máximo definidos no perfil |
| Prazo disponível | 10 | Dias restantes até o encerramento do recebimento de propostas |
| Aderência ao perfil da empresa | 20 | Correspondência com as palavras-chave descritas pelo usuário |

Classificação: 🟢 80–100 alta prioridade · 🟡 60–79 média · 🔴 abaixo de 60
baixa prioridade.

### Personalizando a classificação

As listas `PALAVRAS_SERVICO` e `PALAVRAS_PRODUTO`, no topo de `app.py`, são
simples listas de texto — edite-as livremente para refletir o vocabulário do
seu segmento (ex.: adicionar termos técnicos específicos da sua área).

---

## 5. Limitações desta versão (e como evoluir)

- **Classificação por palavra-chave, não por IA semântica.** É gratuita e
  funciona bem para o objetivo de priorização, mas não interpreta contexto
  como um modelo de linguagem faria. Se quiser IA semântica no futuro, dá
  para plugar a API da Anthropic/OpenAI só na etapa de classificação
  (mantendo a busca e o restante do sistema gratuitos) — mas isso deixa de
  ser 100% gratuito.
- **Uma única UF/modalidade por chamada à API.** O PNCP não permite busca
  textual livre nem múltiplos filtros combinados numa única chamada; por
  isso o app faz várias chamadas (uma por combinação de UF × modalidade) e
  agrega os resultados. Para muitos estados + muitas modalidades a busca
  fica mais lenta — ajuste "Profundidade da busca" na barra lateral.
  Nota: caso a API mude parâmetros ou passe a exigir campos adicionais no
  futuro, será necessário ajustar `buscar_contratacoes_abertas()` em `app.py`
  de acordo com a documentação vigente do PNCP.
- **Sem persistência entre sessões.** Cada busca é feita "ao vivo"; não há
  histórico salvo nem alertas automáticos por e-mail (isso exigiria um
  serviço de agendamento/e-mail, que tem opções gratuitas como GitHub
  Actions + SMTP gratuito, mas não está incluído nesta versão inicial).
- **Sem cadastro de múltiplos clientes/consultorias.** A versão atual
  atende a um único perfil de prospecção por vez.

Esses pontos são exatamente os "próximos passos" caso você queira evoluir o
GOVIA para os planos Profissional/Intelligence/Enterprise descritos no
plano de negócio.
