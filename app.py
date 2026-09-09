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

import io
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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

REQUEST_TIMEOUT = 25   # segundos por requisição HTTP
TAMANHO_PAGINA = 500    # máximo permitido pela API — reduz nº de chamadas

# "Sem limite de busca" na prática: a API do PNCP não tem busca textual nem
# um jeito de trazer tudo de uma vez, então percorremos página a página até
# a própria API dizer que acabou. Estes dois valores são só uma rede de
# segurança para o app não travar (ex.: bug ou resposta inesperada da API) —
# 300 páginas x 500 registros = até 150.000 registros por combinação de
# UF/modalidade, um teto muito acima do que qualquer filtro real produz.
MAX_PAGINAS_SEGURANCA = 300
MAX_SEGUNDOS_POR_COMBINACAO = 60

CACHE_TTL_SEGUNDOS = 300  # 5 minutos — resultados "frescos" para detectar mudanças

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


@st.cache_data(show_spinner=False, ttl=CACHE_TTL_SEGUNDOS)
def buscar_contratacoes_abertas(uf: str, modalidade_id: int, data_final: str,
                                 _cache_bucket: int) -> list:
    """
    Consulta o endpoint público /v1/contratacoes/proposta — contratações com
    o período de recebimento de PROPOSTA ainda em aberto (foco explícito do
    sistema: apresentação de proposta/projeto/serviço em aberto, não editais
    já encerrados). Gratuito, sem chave de acesso.

    Percorre TODAS as páginas disponíveis (sem limite definido pelo usuário),
    respeitando apenas uma rede de segurança interna contra travamentos
    (MAX_PAGINAS_SEGURANCA / MAX_SEGUNDOS_POR_COMBINACAO).

    _cache_bucket força a expiração do cache quando queremos dados
    garantidamente novos (ex.: ciclo de atualização automática).
    """
    registros = []
    pagina = 1
    inicio = time.monotonic()

    while pagina <= MAX_PAGINAS_SEGURANCA:
        if time.monotonic() - inicio > MAX_SEGUNDOS_POR_COMBINACAO:
            st.session_state.setdefault("erros_api", []).append(
                f"UF={uf} modalidade={modalidade_id}: busca interrompida por "
                f"tempo limite ({MAX_SEGUNDOS_POR_COMBINACAO}s) — resultados "
                f"parciais desta combinação foram mantidos."
            )
            break

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


def coletar_oportunidades(ufs, modalidades, dias_janela, cache_bucket=0):
    """Varre UF x Modalidade (todas as páginas), deduplica por numeroControlePNCP."""
    st.session_state["erros_api"] = []
    data_final = (date.today() + timedelta(days=dias_janela)).strftime("%Y%m%d")

    brutos = {}
    combinacoes = [(uf, mid) for uf in ufs for mid in modalidades]
    progresso = st.progress(0.0, text="Consultando PNCP (todas as páginas)...")

    for i, (uf, mid) in enumerate(combinacoes, start=1):
        registros = buscar_contratacoes_abertas(uf, mid, data_final, cache_bucket)
        for r in registros:
            chave = r.get("numeroControlePNCP")
            if chave:
                brutos[chave] = r
        progresso.progress(
            i / len(combinacoes),
            text=f"Consultando PNCP... {uf} / {MODALIDADES.get(mid, mid)} "
                 f"({len(brutos)} registros até agora)",
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


def executar_busca(ufs, modalidades, dias_janela, valor_min, valor_max,
                    prazo_min_dias, palavras_empresa, excluir_termos,
                    origem="manual"):
    """
    Executa uma busca completa (todas as páginas) e compara com o resultado
    anterior salvo em sessão para detectar oportunidades novas ou alteradas.
    Atualiza st.session_state com os novos resultados e a notificação.
    """
    cache_bucket = int(time.time() // CACHE_TTL_SEGUNDOS)
    with st.spinner(
        "Consultando a API pública do PNCP (todas as páginas disponíveis)..."
    ):
        brutos = coletar_oportunidades(ufs, modalidades, dias_janela, cache_bucket)

    classificadas = []
    for item in brutos:
        resultado = classificar_oportunidade(
            item, valor_min, valor_max, prazo_min_dias, palavras_empresa, excluir_termos
        )
        if resultado:
            classificadas.append(resultado)
    classificadas.sort(key=lambda x: x["score"], reverse=True)

    # --- Detecção de mudanças frente à busca anterior ---
    anteriores_por_chave = {
        r["numeroControlePNCP"]: r for r in st.session_state.get("resultados", [])
    }
    ja_existia_busca_anterior = bool(anteriores_por_chave)

    novas, alteradas = [], []
    CAMPOS_MONITORADOS = ("valorEstimado", "situacao", "diasRestantes", "score")

    for r in classificadas:
        chave = r["numeroControlePNCP"]
        anterior = anteriores_por_chave.get(chave)
        if anterior is None:
            r["status_atualizacao"] = "novo"
            novas.append(r)
        else:
            mudou = any(anterior.get(c) != r.get(c) for c in CAMPOS_MONITORADOS)
            if mudou:
                r["status_atualizacao"] = "alterado"
                alteradas.append(r)
            else:
                r["status_atualizacao"] = None

    st.session_state["resultados"] = classificadas
    st.session_state["total_bruto"] = len(brutos)
    st.session_state["ultima_busca_em"] = datetime.now()
    st.session_state["ultima_busca_origem"] = origem

    if ja_existia_busca_anterior and (novas or alteradas):
        msg = f"🔔 {len(novas)} nova(s) · {len(alteradas)} alterada(s) desde a última atualização"
        st.session_state["notificacao"] = msg
        st.toast(msg, icon="🔔")
    elif not ja_existia_busca_anterior:
        st.session_state["notificacao"] = None
    else:
        st.session_state["notificacao"] = None


# --------------------------------------------------------------------------
# INTERFACE
# --------------------------------------------------------------------------

st.title("🏛️ GOVIA")
st.caption(
    "Inteligência em contratações públicas — encontre licitações de "
    "**serviços**, sem necessidade de estoque, com base nos dados abertos "
    "do PNCP. Busca focada em contratações com **prazo de proposta em "
    "aberto**. 100% gratuito para operar."
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

    st.caption(
        "ℹ️ A busca percorre **todas as páginas** disponíveis no PNCP para "
        "os filtros acima — não há limite de profundidade configurável."
    )

    st.divider()
    st.subheader("🔄 Atualização automática")
    auto_refresh = st.toggle(
        "Ativar atualização automática",
        value=st.session_state.get("auto_refresh_ativo", False),
        help="Enquanto esta aba do navegador estiver aberta, o GOVIA refaz "
             "a busca periodicamente com os mesmos parâmetros e avisa se "
             "algo mudou. Não funciona com a aba fechada (limitação de "
             "hospedagem gratuita, sem serviço de background).",
    )
    st.session_state["auto_refresh_ativo"] = auto_refresh
    intervalo_min = st.selectbox(
        "Intervalo de atualização", options=[5, 10, 15, 30, 60], index=2,
        format_func=lambda m: f"a cada {m} minutos", disabled=not auto_refresh,
    )

    buscar = st.button("🔎 Buscar oportunidades", type="primary", use_container_width=True)

# --------------------------------------------------------------------------
# GATILHO DE ATUALIZAÇÃO AUTOMÁTICA
# --------------------------------------------------------------------------
# st_autorefresh força o Streamlit a "re-rodar" o script periodicamente
# enquanto a aba estiver aberta — é o mecanismo que permite atualização
# automática sem custo, mas só funciona com a página aberta no navegador.

if auto_refresh:
    st_autorefresh(interval=intervalo_min * 60 * 1000, key="ciclo_auto_refresh")

parametros_atuais = dict(
    ufs=ufs_selecionadas, modalidades=modalidades_selecionadas,
    dias_janela=dias_janela, valor_min=valor_min, valor_max=valor_max,
    prazo_min_dias=prazo_min_dias, perfil_empresa=perfil_empresa,
    excluir_texto=excluir_texto,
)

deve_buscar = False
origem_busca = "manual"

if buscar:
    if not ufs_selecionadas:
        st.warning("Selecione ao menos um estado (UF).")
        st.stop()
    if not modalidades_selecionadas:
        st.warning("Selecione ao menos uma modalidade.")
        st.stop()
    deve_buscar = True
    origem_busca = "manual"
    st.session_state["parametros_busca"] = parametros_atuais

elif (
    auto_refresh
    and "resultados" in st.session_state
    and st.session_state.get("parametros_busca") == parametros_atuais
    and st.session_state.get("ultima_busca_em")
    and (datetime.now() - st.session_state["ultima_busca_em"]).total_seconds()
        >= intervalo_min * 60
):
    # Ciclo automático: só dispara com os MESMOS parâmetros da última busca
    # manual, evitando buscar sozinho um perfil que o usuário ainda nem
    # confirmou.
    deve_buscar = True
    origem_busca = "automática"

# --------------------------------------------------------------------------
# EXECUÇÃO DA BUSCA
# --------------------------------------------------------------------------

if deve_buscar:
    palavras_empresa = [p.strip() for p in perfil_empresa.split(",") if p.strip()]
    excluir_termos = [p.strip() for p in excluir_texto.split(",") if p.strip()]

    executar_busca(
        ufs_selecionadas, modalidades_selecionadas, dias_janela,
        valor_min, valor_max, prazo_min_dias, palavras_empresa,
        excluir_termos, origem=origem_busca,
    )

# --------------------------------------------------------------------------
# EXIBIÇÃO DOS RESULTADOS
# --------------------------------------------------------------------------

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]
    total_bruto = st.session_state.get("total_bruto", len(resultados))
    ultima_busca_em = st.session_state.get("ultima_busca_em")
    ultima_busca_origem = st.session_state.get("ultima_busca_origem", "manual")

    status_cols = st.columns([3, 2])
    with status_cols[0]:
        if ultima_busca_em:
            origem_label = "🔄 automática" if ultima_busca_origem == "automática" else "🖱️ manual"
            st.caption(
                f"Última atualização: {ultima_busca_em.strftime('%d/%m/%Y %H:%M:%S')} ({origem_label})"
            )
    with status_cols[1]:
        if auto_refresh:
            proximo = ""
            if ultima_busca_em:
                segundos_restantes = max(
                    0, intervalo_min * 60 - (datetime.now() - ultima_busca_em).total_seconds()
                )
                proximo = f" · próxima em ~{int(segundos_restantes // 60)} min"
            st.caption(f"🔄 Atualização automática ativa (a cada {intervalo_min} min){proximo}")

    if st.session_state.get("notificacao"):
        st.success(st.session_state["notificacao"])

    if st.session_state.get("erros_api"):
        with st.expander(f"⚠️ {len(st.session_state['erros_api'])} avisos durante a consulta"):
            for e in st.session_state["erros_api"]:
                st.text(e)

    alta = sum(1 for r in resultados if r["prioridade"].startswith("🟢"))
    media = sum(1 for r in resultados if r["prioridade"].startswith("🟡"))
    baixa = sum(1 for r in resultados if r["prioridade"].startswith("🔴"))
    novas_qtd = sum(1 for r in resultados if r.get("status_atualizacao") == "novo")
    alteradas_qtd = sum(1 for r in resultados if r.get("status_atualizacao") == "alterado")

    st.subheader(f"{len(resultados)} oportunidades encontradas (de {total_bruto} localizadas no PNCP)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Alta prioridade", alta)
    c2.metric("🟡 Média prioridade", media)
    c3.metric("🔴 Baixa prioridade", baixa)
    c4.metric("🔔 Novas/alteradas", novas_qtd + alteradas_qtd)

    filtro_col1, filtro_col2 = st.columns([3, 2])
    with filtro_col1:
        filtro_prioridade = st.radio(
            "Filtrar por prioridade", ["Todas", "🟢 Alta", "🟡 Média", "🔴 Baixa"],
            horizontal=True,
        )
    with filtro_col2:
        somente_novidades = st.checkbox(
            "Mostrar apenas novas/alteradas", value=False,
            disabled=(novas_qtd + alteradas_qtd) == 0,
        )

    exibir = resultados
    if filtro_prioridade != "Todas":
        exibir = [r for r in exibir if r["prioridade"] == filtro_prioridade]
    if somente_novidades:
        exibir = [r for r in exibir if r.get("status_atualizacao")]

    # --- Exportação: CSV e Excel ---
    if exibir:
        df_export = pd.DataFrame(exibir).drop(columns=["status_atualizacao"], errors="ignore")

        buffer_excel = io.BytesIO()
        with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Oportunidades")
        buffer_excel.seek(0)

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            st.download_button(
                "⬇️ Exportar resultados (CSV)",
                data=df_export.to_csv(index=False).encode("utf-8-sig"),
                file_name="govia_oportunidades.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with exp_col2:
            st.download_button(
                "⬇️ Exportar resultados (Excel)",
                data=buffer_excel,
                file_name="govia_oportunidades.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.divider()

    for r in exibir:
        with st.container(border=True):
            col_a, col_b = st.columns([5, 1])
            with col_a:
                badge = ""
                if r.get("status_atualizacao") == "novo":
                    badge = " 🆕 **NOVO**"
                elif r.get("status_atualizacao") == "alterado":
                    badge = " ✏️ **ATUALIZADO**"
                st.markdown(f"**{r['orgao']}** — {r['municipio']}/{r['uf']}{badge}")
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
                "Prazo p/ proposta",
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

with st.expander("Sobre a atualização automática e as notificações"):
    st.markdown(
        """
- A busca consulta o endpoint `/v1/contratacoes/proposta` do PNCP, que traz
  **apenas contratações com o prazo de apresentação de proposta ainda em
  aberto** — é o foco principal do sistema.
- A busca percorre **todas as páginas** disponíveis para os filtros
  escolhidos (sem limite configurável), respeitando apenas um teto de
  segurança interno para não travar o app.
- Com **"Atualização automática"** ativada, o GOVIA repete a busca com os
  mesmos parâmetros no intervalo escolhido, compara com o resultado
  anterior e destaca oportunidades **novas** (🆕) ou **alteradas** (✏️ —
  mudança de valor, situação, prazo ou score), com um aviso no topo da tela
  e uma notificação (toast).
- **Limitação importante (hospedagem gratuita):** a atualização automática
  só funciona enquanto esta aba do navegador estiver aberta. Não há um
  processo rodando em segundo plano nem envio de e-mail/push quando a aba
  está fechada — isso exigiria um serviço adicional (ex.: agendador +
  e-mail), que não está incluído nesta versão gratuita.
        """
    )
