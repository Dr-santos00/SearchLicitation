# -*- coding: utf-8 -*-
"""
GOVIA — Inteligência em Contratações Públicas
Sistema 100% gratuito de prospecção comercial baseado na API pública do PNCP.

Como funciona:
    PNCP (API pública, sem custo) -> filtros objetivos -> classificação por
    regras (GOV SCORE, sem IA paga) -> ranking de oportunidades

Custo de operação: R$ 0,00
    - API do PNCP: pública, gratuita, sem autenticação
    - Streamlit: framework open-source
    - Hospedagem sugerida: Streamlit Community Cloud (plano gratuito)
"""

import re
import time
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

# --------------------------------------------------------------------------
# CONFIGURAÇÃO GERAL
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="GOVIA — Inteligência em Contratações Públicas",
    page_icon="🏛️",
    layout="wide",
)

BASE_URL = "https://pncp.gov.br/api/consulta"
PORTAL_EDITAL_URL = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"

REQUEST_TIMEOUT = 20  # segundos
TAMANHO_PAGINA = 50   # registros por página (máx. permitido pela API: 500)

# Tabela de domínio oficial (Manual de Consultas do PNCP)
MODALIDADES = {
    1: "Leilão - Eletrônico",
    2: "Diálogo Competitivo",
    3: "Concurso",
    4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",
    8: "Dispensa de Licitação",
    9: "Inexigibilidade",
    10: "Manifestação de Interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão - Presencial",
    14: "Inaplicabilidade da Licitação",
}

# Pré-seleção sugerida: modalidades mais relevantes para contratação de
# serviços (exclui leilões de bens, que são para venda de ativos)
MODALIDADES_SERVICO_PADRAO = [4, 5, 6, 7, 8, 9, 10, 11, 12]

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]

# --------------------------------------------------------------------------
# DICIONÁRIOS DE CLASSIFICAÇÃO (heurística por palavra-chave, 100% local,
# sem custo de IA — pode ser editada livremente para o seu segmento)
# --------------------------------------------------------------------------

PALAVRAS_SERVICO = [
    "serviço", "serviços", "prestação de serviço", "prestação de serviços",
    "mão de obra", "mao de obra", "limpeza", "conservação", "manutenção",
    "vigilância", "segurança patrimonial", "administrativ", "consultoria",
    "treinamento", "capacitação", "tecnologia da informação", "software",
    "desenvolvimento de sistema", "suporte técnico", "engenharia",
    "publicidade", "comunicação", "organização de evento", "locação de",
    "gráfico", "ambiental", "contáb", "jurídic", "saúde", "especializad",
    "apoio operacional", "recepção", "copeiragem", "jardinagem",
    "dedetização", "call center", "telefonia", "hospedagem de sistema",
    "auditoria", "assessoria", "monitoramento", "transporte de pessoal",
    "gestão de", "operação de", "fiscalização", "elaboração de projeto",
]

PALAVRAS_PRODUTO = [
    "aquisição de", "fornecimento de", "compra de", "material de",
    "material hospitalar", "medicamento", "gênero aliment", "alimento",
    "merenda", "uniforme", "combustível", "veículo", "computador",
    "notebook", "mobiliário", "móveis", "equipamento", "material de "
    "construção", "material de expediente", "insumo", "peça", "pneu",
    "material elétrico", "material de limpeza (fornecimento)", "cimento",
    "vergalhão", "colchão", "medicamentos", "reagente", "fármaco",
]

# --------------------------------------------------------------------------
# CLIENTE DA API PÚBLICA DO PNCP
# --------------------------------------------------------------------------


@st.cache_data(show_spinner=False, ttl=1800)
def buscar_contratacoes_abertas(uf: str, modalidade_id: int, data_final: str,
                                 max_paginas: int) -> list:
    """
    Consulta o endpoint público /v1/contratacoes/proposta (contratações com
    período de recebimento de propostas em aberto). Gratuito, sem chave.
    """
    registros = []
    pagina = 1
    while pagina <= max_paginas:
        params = {
            "dataFinal": data_final,
            "codigoModalidadeContratacao": modalidade_id,
            "uf": uf,
            "pagina": pagina,
            "tamanhoPagina": TAMANHO_PAGINA,
        }
        try:
            resp = requests.get(
                f"{BASE_URL}/v1/contratacoes/proposta",
                params=params,
                headers={"accept": "*/*"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            st.session_state.setdefault("erros_api", []).append(
                f"UF={uf} modalidade={modalidade_id} pág={pagina}: {exc}"
            )
            break

        if resp.status_code == 204:
            break  # sem conteúdo para esse filtro
        if resp.status_code != 200:
            st.session_state.setdefault("erros_api", []).append(
                f"UF={uf} modalidade={modalidade_id} pág={pagina}: "
                f"HTTP {resp.status_code}"
            )
            break

        payload = resp.json()
        dados = payload.get("data", [])
        if not dados:
            break
        registros.extend(dados)

        total_paginas = payload.get("totalPaginas", 1)
        if pagina >= total_paginas:
            break
        pagina += 1
        time.sleep(0.05)  # gentileza com a API pública

    return registros


def coletar_oportunidades(ufs, modalidades, dias_janela, max_paginas):
    """Varre UF x Modalidade, deduplica por numeroControlePNCP."""
    st.session_state["erros_api"] = []
    data_final = (date.today() + timedelta(days=dias_janela)).strftime("%Y%m%d")

    brutos = {}
    combinacoes = [(uf, mid) for uf in ufs for mid in modalidades]
    progresso = st.progress(0.0, text="Consultando PNCP...")

    for i, (uf, mid) in enumerate(combinacoes, start=1):
        registros = buscar_contratacoes_abertas(uf, mid, data_final, max_paginas)
        for r in registros:
            chave = r.get("numeroControlePNCP")
            if chave:
                brutos[chave] = r
        progresso.progress(
            i / len(combinacoes),
            text=f"Consultando PNCP... {uf} / {MODALIDADES.get(mid, mid)}",
        )

    progresso.empty()
    return list(brutos.values())


# --------------------------------------------------------------------------
# CLASSIFICAÇÃO / GOV SCORE (heurística local, sem custo de IA)
# --------------------------------------------------------------------------


def _contar_ocorrencias(texto: str, termos: list) -> int:
    texto = texto.lower()
    return sum(1 for termo in termos if termo.lower() in texto)


def classificar_oportunidade(item: dict, valor_min: float, valor_max: float,
                              prazo_min_dias: int, palavras_empresa: list,
                              excluir_termos: list) -> dict:
    objeto = (item.get("objetoCompra") or "")
    info_extra = (item.get("informacaoComplementar") or "")
    texto = f"{objeto} {info_extra}"

    if excluir_termos and _contar_ocorrencias(texto, excluir_termos) > 0:
        return None  # exclusão explícita do usuário

    hits_servico = _contar_ocorrencias(texto, PALAVRAS_SERVICO)
    hits_produto = _contar_ocorrencias(texto, PALAVRAS_PRODUTO)

    # --- Componente 1: é serviço? (peso 30) ---
    if hits_servico == 0 and hits_produto == 0:
        score_servico = 15.0  # texto genérico, não classificável com certeza
    else:
        proporcao = hits_servico / max(1, (hits_servico + hits_produto))
        score_servico = 30.0 * proporcao

    # --- Componente 2: exige estoque/fornecimento de produto? (peso 25) ---
    score_estoque = 25.0 if hits_produto == 0 else max(0.0, 25.0 - hits_produto * 8)

    # --- Componente 3: valor dentro da faixa desejada? (peso 15) ---
    valor = item.get("valorTotalEstimado") or 0
    if valor_min <= valor <= valor_max:
        score_valor = 15.0
    elif valor == 0:
        score_valor = 7.5  # valor sigiloso/não informado — neutro
    else:
        score_valor = 0.0

    # --- Componente 4: prazo até encerramento da proposta (peso 10) ---
    dias_restantes = None
    data_enc = item.get("dataEncerramentoProposta")
    if data_enc:
        try:
            data_enc_dt = pd.to_datetime(data_enc).date()
            dias_restantes = (data_enc_dt - date.today()).days
        except Exception:
            dias_restantes = None
    if dias_restantes is None:
        score_prazo = 5.0
    elif dias_restantes >= prazo_min_dias:
        score_prazo = 10.0
    elif dias_restantes >= 0:
        score_prazo = 10.0 * (dias_restantes / max(1, prazo_min_dias))
    else:
        score_prazo = 0.0

    # --- Componente 5: aderência ao perfil da empresa (peso 20, bônus) ---
    if palavras_empresa:
        hits_empresa = _contar_ocorrencias(texto, palavras_empresa)
        score_empresa = min(20.0, hits_empresa * 7.0)
    else:
        score_empresa = 10.0  # neutro quando o usuário não descreveu a empresa

    score_total = (
        score_servico + score_estoque + score_valor + score_prazo + score_empresa
    )
    score_total = round(min(100.0, max(0.0, score_total)), 1)

    if score_total >= 80:
        prioridade = "🟢 Alta"
    elif score_total >= 60:
        prioridade = "🟡 Média"
    else:
        prioridade = "🔴 Baixa"

    orgao = item.get("orgaoEntidade", {}) or {}
    unidade = item.get("unidadeOrgao", {}) or {}

    return {
        "score": score_total,
        "prioridade": prioridade,
        "numeroControlePNCP": item.get("numeroControlePNCP"),
        "objeto": objeto.strip(),
        "orgao": orgao.get("razaoSocial", "—"),
        "municipio": unidade.get("municipioNome", "—"),
        "uf": unidade.get("ufSigla", "—"),
        "modalidade": item.get("modalidadeNome", "—"),
        "valorEstimado": valor,
        "dataEncerramentoProposta": data_enc,
        "diasRestantes": dias_restantes,
        "situacao": item.get("situacaoCompraNome", "—"),
        "linkEdital": PORTAL_EDITAL_URL.format(
            cnpj=orgao.get("cnpj", ""),
            ano=item.get("anoCompra", ""),
            sequencial=item.get("sequencialCompra", ""),
        ) if orgao.get("cnpj") else None,
        "cnpjOrgao": orgao.get("cnpj", "—"),
        "hitsServico": hits_servico,
        "hitsProduto": hits_produto,
    }


# --------------------------------------------------------------------------
# INTERFACE
# --------------------------------------------------------------------------

st.title("🏛️ GOVIA")
st.caption(
    "Inteligência em contratações públicas — encontre licitações de "
    "**serviços**, sem necessidade de estoque, com base nos dados abertos "
    "do PNCP. 100% gratuito para operar."
)

with st.sidebar:
    st.header("Perfil de prospecção")

    ufs_selecionadas = st.multiselect(
        "Estado(s) (UF)", options=UFS, default=["MG"],
        help="Selecione um ou mais estados. Quanto mais estados, mais lenta a consulta.",
    )

    modalidades_selecionadas = st.multiselect(
        "Modalidades",
        options=list(MODALIDADES.keys()),
        default=MODALIDADES_SERVICO_PADRAO,
        format_func=lambda k: f"{k} — {MODALIDADES[k]}",
    )

    dias_janela = st.slider(
        "Buscar propostas com encerramento em até (dias)", 1, 180, 60,
        help="Janela de tempo à frente para localizar oportunidades ainda abertas.",
    )

    col1, col2 = st.columns(2)
    with col1:
        valor_min = st.number_input("Valor mínimo (R$)", min_value=0, value=20000, step=1000)
    with col2:
        valor_max = st.number_input("Valor máximo (R$)", min_value=0, value=1000000, step=10000)

    prazo_min_dias = st.slider("Prazo mínimo desejado até a proposta (dias)", 0, 60, 10)

    st.divider()
    st.subheader("Minha empresa (opcional)")
    st.caption("Descreva seu segmento/experiência para aumentar a aderência no GOV SCORE.")
    perfil_empresa = st.text_area(
        "Palavras-chave da empresa (separadas por vírgula)",
        placeholder="ex: tecnologia, suporte técnico, desenvolvimento de software, help desk",
    )

    excluir_texto = st.text_area(
        "Excluir oportunidades que contenham (separadas por vírgula)",
        placeholder="ex: obras, construção civil, merenda",
    )

    st.divider()
    max_paginas = st.slider(
        "Profundidade da busca (páginas por UF/modalidade)", 1, 20, 5,
        help="Cada página traz até 50 registros. Valores maiores = busca mais completa e mais lenta.",
    )

    buscar = st.button("🔎 Buscar oportunidades", type="primary", use_container_width=True)

# --------------------------------------------------------------------------
# EXECUÇÃO DA BUSCA
# --------------------------------------------------------------------------

if buscar:
    if not ufs_selecionadas:
        st.warning("Selecione ao menos um estado (UF).")
        st.stop()
    if not modalidades_selecionadas:
        st.warning("Selecione ao menos uma modalidade.")
        st.stop()

    with st.spinner("Consultando a API pública do PNCP..."):
        brutos = coletar_oportunidades(
            ufs_selecionadas, modalidades_selecionadas, dias_janela, max_paginas
        )

    palavras_empresa = [p.strip() for p in perfil_empresa.split(",") if p.strip()]
    excluir_termos = [p.strip() for p in excluir_texto.split(",") if p.strip()]

    classificadas = []
    for item in brutos:
        resultado = classificar_oportunidade(
            item, valor_min, valor_max, prazo_min_dias, palavras_empresa, excluir_termos
        )
        if resultado:
            classificadas.append(resultado)

    classificadas.sort(key=lambda x: x["score"], reverse=True)
    st.session_state["resultados"] = classificadas
    st.session_state["total_bruto"] = len(brutos)

# --------------------------------------------------------------------------
# EXIBIÇÃO DOS RESULTADOS
# --------------------------------------------------------------------------

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]
    total_bruto = st.session_state.get("total_bruto", len(resultados))

    if st.session_state.get("erros_api"):
        with st.expander(f"⚠️ {len(st.session_state['erros_api'])} avisos durante a consulta"):
            for e in st.session_state["erros_api"]:
                st.text(e)

    alta = sum(1 for r in resultados if r["prioridade"].startswith("🟢"))
    media = sum(1 for r in resultados if r["prioridade"].startswith("🟡"))
    baixa = sum(1 for r in resultados if r["prioridade"].startswith("🔴"))

    st.subheader(f"{len(resultados)} oportunidades encontradas (de {total_bruto} localizadas no PNCP)")
    c1, c2, c3 = st.columns(3)
    c1.metric("🟢 Alta prioridade", alta)
    c2.metric("🟡 Média prioridade", media)
    c3.metric("🔴 Baixa prioridade", baixa)

    filtro_prioridade = st.radio(
        "Filtrar por prioridade", ["Todas", "🟢 Alta", "🟡 Média", "🔴 Baixa"],
        horizontal=True,
    )
    if filtro_prioridade != "Todas":
        exibir = [r for r in resultados if r["prioridade"] == filtro_prioridade]
    else:
        exibir = resultados

    # Exportação
    if exibir:
        df_export = pd.DataFrame(exibir)
        st.download_button(
            "⬇️ Exportar resultados (CSV)",
            data=df_export.to_csv(index=False).encode("utf-8-sig"),
            file_name="govia_oportunidades.csv",
            mime="text/csv",
        )

    st.divider()

    for r in exibir:
        with st.container(border=True):
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.markdown(f"**{r['orgao']}** — {r['municipio']}/{r['uf']}")
                st.write(r["objeto"] or "_(sem descrição)_")
            with col_b:
                st.markdown(f"### {r['score']}/100")
                st.caption(r["prioridade"])

            m1, m2, m3, m4 = st.columns(4)
            valor_fmt = (
                f"R$ {r['valorEstimado']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if r["valorEstimado"] else "Sigiloso / não informado"
            )
            m1.metric("Valor estimado", valor_fmt)
            m2.metric("Modalidade", r["modalidade"])
            m3.metric(
                "Prazo",
                f"{r['diasRestantes']} dia(s)" if r["diasRestantes"] is not None else "—",
            )
            m4.metric("Situação", r["situacao"])

            if r["linkEdital"]:
                st.link_button("Ver no Portal PNCP", r["linkEdital"])
            st.caption(f"Nº controle PNCP: {r['numeroControlePNCP']} · CNPJ órgão: {r['cnpjOrgao']}")
else:
    st.info(
        "Defina o perfil de prospecção na barra lateral e clique em "
        "**Buscar oportunidades** para consultar o PNCP."
    )

st.divider()
with st.expander("Como funciona o GOV SCORE"):
    st.markdown(
        """
O GOV SCORE (0–100) é calculado localmente, **sem depender de IA paga**,
combinando:

| Componente | Peso | O que avalia |
|---|---|---|
| É serviço | 30 | Proporção de termos de serviço vs. produto no objeto da contratação |
| Não exige estoque | 25 | Penaliza a presença de termos típicos de fornecimento de produto |
| Valor dentro da faixa | 15 | Se o valor estimado está entre o mínimo e máximo informados |
| Prazo disponível | 10 | Dias restantes até o encerramento da proposta |
| Aderência ao perfil da empresa | 20 | Correspondência com as palavras-chave da sua empresa |

🟢 80–100 alta prioridade · 🟡 60–79 média · 🔴 abaixo de 60 baixa prioridade.

As listas de palavras-chave (`PALAVRAS_SERVICO` / `PALAVRAS_PRODUTO`) ficam
no início do arquivo `app.py` e podem ser editadas livremente para o seu
segmento de atuação.
        """
    )
