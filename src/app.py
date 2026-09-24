"""Dashboard de análise dos contratos de transporte de gás natural da TBG (fonte: ANP)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
from data import (  # noqa: E402
    DEFAULT_DATA_PATH,
    DISPLAY_LABELS,
    POC_COL_COMERCIAL,
    POC_COL_CONTRATADA,
    POC_COL_DISPONIVEL,
    POC_COL_TARIFA,
    POC_COL_TECNICA,
    capacity_timeline,
    load_data,
    load_poc_pontos,
    top_n_with_other,
    weighted_avg,
)

st.set_page_config(page_title="Contratos de Transporte de Gás Natural", page_icon="🔷", layout="wide")

# ---------------------------------------------------------------------------
# Identidade visual — Pacífico Energia
# Paleta extraída do logo e validada (contraste + daltonismo) com o script do
# skill de dataviz antes de ser aplicada aqui.
# ---------------------------------------------------------------------------
BRAND_BLUE = "#2E5FA3"        # azul principal (logo / "Energia")
BRAND_BLUE_DARK = "#1B3E68"   # azul escuro (gradiente do ícone, hover)
BRAND_BLUE_LIGHT = "#DCE7F5"  # azul claro (fundos e realces)
BRAND_SLATE = "#3D3D49"       # cinza-chumbo ("Pacífico")
BRAND_ORANGE = "#EB6834"      # cor complementar (2º slot categórico)
BRAND_GREEN = "#0CA30C"       # status "Ativo"

PALETTE = [BRAND_BLUE, BRAND_ORANGE, "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
COLOR_STATUS = {"Ativo": BRAND_GREEN, "Concluído": BRAND_BLUE}
COLOR_FLUXO = {"Entrada": BRAND_BLUE, "Saída": BRAND_ORANGE}
OTHER_COLOR = "#A9AFBC"  # cinza neutro para o balde "Outros" (agregado, não é uma série de identidade)
BLUE_SCALE = [[0, BRAND_BLUE_LIGHT], [1, BRAND_BLUE_DARK]]  # escala sequencial (magnitude) para heatmaps


def color_map_for(order: list[str]) -> dict[str, str]:
    """Mapeia uma lista ordenada (Top N + 'Outros') para cores fixas da paleta da marca."""
    mapping = {}
    for i, label in enumerate(order):
        mapping[label] = OTHER_COLOR if label == "Outros" else PALETTE[i % len(PALETTE)]
    return mapping


def _dedup(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for c in seq:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Paleta estendida (marca + paletas qualitativas do Plotly) para casos onde TODAS as categorias
# devem aparecer individualmente (ex: carregadores), sem agrupar em "Outros". Com muitas dezenas
# de categorias não é mais possível garantir 8 tons distinguíveis por daltonismo — aqui prioriza-se
# ver cada série, não a validação estrita de contraste usada na paleta categórica principal.
EXTENDED_PALETTE = _dedup(
    PALETTE + px.colors.qualitative.Dark24 + px.colors.qualitative.Light24 + px.colors.qualitative.Alphabet
)


def color_map_all(categories: list[str]) -> dict[str, str]:
    """Mapeia todas as categorias (na ordem informada) para cores, ciclando pela paleta estendida."""
    return {cat: EXTENDED_PALETTE[i % len(EXTENDED_PALETTE)] for i, cat in enumerate(categories)}

st.markdown(
    f"""
    <style>
        .stTabs [aria-selected="true"] {{ color: {BRAND_BLUE} !important; font-weight: 700; }}
        div[data-testid="stMetric"] {{
            background: {BRAND_BLUE_LIGHT};
            border-left: 4px solid {BRAND_BLUE};
            border-radius: 6px;
            padding: 10px 14px 8px 14px;
        }}
        div[data-testid="stMetricValue"] {{ color: {BRAND_BLUE_DARK}; }}
        h1, h2, h3 {{ color: {BRAND_SLATE}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_num(x: float, casas: int = 0) -> str:
    if pd.isna(x):
        return "-"
    s = f"{x:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


# ---------------------------------------------------------------------------
# Sidebar: fonte de dados + filtros
# ---------------------------------------------------------------------------
st.sidebar.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
      <svg width="36" height="36" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="pacGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="{BRAND_BLUE}"/>
            <stop offset="100%" stop-color="{BRAND_BLUE_DARK}"/>
          </linearGradient>
        </defs>
        <circle cx="18" cy="18" r="13.5" fill="none" stroke="url(#pacGrad)" stroke-width="4.5"
                stroke-linecap="round" stroke-dasharray="64 21" transform="rotate(-40 18 18)"/>
      </svg>
      <div style="line-height:1.1;">
        <div style="font-size:1.15rem;font-weight:800;color:{BRAND_SLATE};">Pacífico<span style="color:{BRAND_BLUE};"> Energia</span></div>
        <div style="font-size:0.7rem;color:{BRAND_SLATE};opacity:.7;">Contratos de Transporte</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

upload = st.sidebar.file_uploader(
    "Atualizar planilha (opcional)", type=["xls", "xlsx"],
    help="Envie uma nova exportação da ANP para substituir a base padrão nesta sessão.",
)

if st.sidebar.button("🔄 Recarregar base padrão"):
    load_data.clear()

try:
    df = load_data(file_bytes=upload.getvalue()) if upload else load_data(DEFAULT_DATA_PATH)
except Exception as exc:  # noqa: BLE001
    st.sidebar.error(f"Erro ao ler a planilha: {exc}")
    st.stop()

st.sidebar.caption(f"Base: {upload.name if upload else DEFAULT_DATA_PATH.name} · {len(df):,} registros".replace(",", "."))

st.sidebar.header("Filtros")

transportadora_sel = st.sidebar.multiselect(
    "Transportadora", sorted(df["transportadora"].dropna().unique()), default=list(df["transportadora"].dropna().unique())
)
status_sel = st.sidebar.multiselect("Status", sorted(df["status"].dropna().unique()), default=list(df["status"].dropna().unique()))
fluxo_sel = st.sidebar.multiselect("Fluxo", sorted(df["fluxo"].dropna().unique()), default=list(df["fluxo"].dropna().unique()))
produto_sel = st.sidebar.multiselect("Produto", sorted(df["produto"].dropna().unique()), default=list(df["produto"].dropna().unique()))
carregador_sel = st.sidebar.multiselect("Carregador", sorted(df["carregador"].dropna().unique()))
ponto_sel = st.sidebar.multiselect("Ponto de Entrada/Saída", sorted(df["ponto"].dropna().unique()))

min_data = df["data_inicio"].min()
max_data = df["data_fim"].max()
date_range = st.sidebar.date_input(
    "Contratos com início entre",
    value=(min_data.date(), max_data.date()),
    min_value=min_data.date(),
    max_value=max_data.date(),
)

mask = (
    df["transportadora"].isin(transportadora_sel)
    & df["status"].isin(status_sel)
    & df["fluxo"].isin(fluxo_sel)
    & df["produto"].isin(produto_sel)
)
if carregador_sel:
    mask &= df["carregador"].isin(carregador_sel)
if ponto_sel:
    mask &= df["ponto"].isin(ponto_sel)
if isinstance(date_range, tuple) and len(date_range) == 2:
    ini, fim = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    mask &= df["data_inicio"].between(ini, fim)

fdf = df[mask].copy()

st.title("Contratos de Transporte de Gás Natural")
st.caption(f"Dados públicos da ANP · Transportadoras: {', '.join(sorted(transportadora_sel)) if transportadora_sel else '—'}")

if fdf.empty:
    st.warning("Nenhum contrato encontrado com os filtros selecionados.")
    st.stop()

tabs = st.tabs([
    "📊 Visão Geral",
    "🏢 Carregadores",
    "📍 Pontos de Entrada/Saída",
    "📈 Evolução Temporal",
    "💰 Tarifas",
    "🗺️ Rede (dados ANP/POC)",
    "📋 Tabela Detalhada",
])

# ---------------------------------------------------------------------------
# Tab 1: Visão Geral
# ---------------------------------------------------------------------------
with tabs[0]:
    ativos = fdf[fdf["status"] == "Ativo"]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Contratos (filtro)", fmt_num(len(fdf)))
    c2.metric("Contratos Ativos", fmt_num(len(ativos)))
    c3.metric("Capacidade Ativa (mil m³/dia)", fmt_num(ativos["capacidade"].sum(), 1))
    c4.metric("Tarifa Média Ponderada (R$/MMBTU)", fmt_num(weighted_avg(ativos, "tarifa", "capacidade"), 2))
    c5.metric("Carregadores Únicos", fmt_num(fdf["carregador"].nunique()))
    c6.metric("Transportadoras", fmt_num(fdf["transportadora"].nunique()))

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Status")
        fig = px.pie(fdf, names="status", color="status", hole=0.5, color_discrete_map=COLOR_STATUS)
        fig.update_traces(textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("Fluxo")
        fig = px.pie(fdf, names="fluxo", color="fluxo", hole=0.5, color_discrete_map=COLOR_FLUXO)
        fig.update_traces(textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)
    with col3:
        st.subheader("Produto")
        contagem = fdf["produto"].value_counts().reset_index()
        contagem.columns = ["produto", "contratos"]
        fig = px.bar(contagem, x="contratos", y="produto", orientation="h", color_discrete_sequence=[BRAND_BLUE])
        fig.update_layout(yaxis_title="", xaxis_title="Nº de contratos", yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("⏰ Contratos ativos vencendo nos próximos 90 dias")
    vencendo = ativos[(ativos["dias_para_vencer"] >= 0) & (ativos["dias_para_vencer"] <= 90)].sort_values("dias_para_vencer")
    if vencendo.empty:
        st.info("Nenhum contrato ativo vence nos próximos 90 dias, dentro do filtro atual.")
    else:
        cols = ["contrato", "carregador", "ponto", "fluxo", "data_fim", "dias_para_vencer", "capacidade"]
        show = vencendo[cols].rename(columns=DISPLAY_LABELS)
        st.dataframe(show, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Tab 2: Carregadores
# ---------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Capacidade contratada ativa por carregador")
    ativos = fdf[fdf["status"] == "Ativo"]
    por_carregador = (
        ativos.groupby("carregador", as_index=False)
        .agg(capacidade=("capacidade", "sum"), contratos=("contrato", "count"))
        .sort_values("capacidade", ascending=False)
    )
    top_n = st.slider("Top N carregadores", 5, max(5, len(por_carregador)), min(15, len(por_carregador)))
    top = por_carregador.head(top_n)

    col1, col2 = st.columns([1, 1.6])
    with col1:
        fig = px.bar(top, x="capacidade", y="carregador", orientation="h", color_discrete_sequence=[BRAND_BLUE],
                     labels={"capacidade": "Capacidade (mil m³/dia)", "carregador": ""})
        fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(420, 24 * len(top)))
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.dataframe(
            top.rename(columns={"carregador": "Carregador", "capacidade": "Capacidade (mil m³/dia)", "contratos": "Contratos"}),
            use_container_width=True, hide_index=True, height=max(420, 24 * len(top)),
        )

    st.subheader("Todos os carregadores (contratos ativos + concluídos, dentro do filtro)")
    todos = (
        fdf.groupby(["carregador", "status"], as_index=False)["contrato"].count()
        .rename(columns={"contrato": "contratos"})
    )
    fig2 = px.bar(
        todos, x="contratos", y="carregador", color="status", orientation="h",
        color_discrete_map=COLOR_STATUS, labels={"contratos": "Nº de contratos", "carregador": ""},
    )
    fig2.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 22 * fdf["carregador"].nunique()))
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Volume de contratos por carregador x ponto/zona")
    st.caption("Nº de contratos de cada carregador em cada ponto de entrada/zona de saída, dentro do filtro atual.")

    def _heatmap_carregador_ponto(base: pd.DataFrame, titulo: str) -> None:
        if base.empty:
            st.info(f"Sem dados de '{titulo}' no filtro atual.")
            return
        carreg_order = base.groupby("carregador")["capacidade"].sum().sort_values(ascending=False).index.tolist()
        ponto_grp, ponto_order = top_n_with_other(base, "ponto", "capacidade", n=12)
        tmp = base.assign(_ponto=ponto_grp)
        pivot = (
            tmp.pivot_table(index="carregador", columns="_ponto", values="contrato", aggfunc="count", fill_value=0)
            .reindex(index=carreg_order, columns=ponto_order, fill_value=0)
        )
        fig = px.imshow(
            pivot, aspect="auto", color_continuous_scale=BLUE_SCALE,
            labels={"x": "Ponto", "y": "Carregador", "color": "Contratos"},
        )
        fig.update_layout(title=titulo, height=max(360, 24 * len(pivot.index)))
        st.plotly_chart(fig, use_container_width=True)

    hcol1, hcol2 = st.columns(2)
    with hcol1:
        _heatmap_carregador_ponto(fdf[fdf["status"] == "Concluído"], "Contratos Concluídos")
    with hcol2:
        _heatmap_carregador_ponto(fdf[fdf["status"] == "Ativo"], "Contratos Ativos")

# ---------------------------------------------------------------------------
# Tab 3: Pontos de Entrada/Saída
# ---------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Capacidade contratada ativa por ponto")
    ativos = fdf[fdf["status"] == "Ativo"]
    por_ponto = (
        ativos.groupby(["ponto", "fluxo"], as_index=False)["capacidade"].sum()
        .sort_values("capacidade", ascending=False)
    )
    fig = px.bar(
        por_ponto, x="capacidade", y="ponto", color="fluxo", orientation="h",
        color_discrete_map=COLOR_FLUXO, barmode="group",
        labels={"capacidade": "Capacidade (mil m³/dia)", "ponto": "", "fluxo": "Fluxo"},
    )
    fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 26 * por_ponto["ponto"].nunique()))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Detalhe por ponto")
    resumo_ponto = (
        ativos.groupby("ponto", as_index=False)
        .agg(capacidade_total=("capacidade", "sum"), contratos=("contrato", "count"), carregadores=("carregador", "nunique"))
        .sort_values("capacidade_total", ascending=False)
    )
    st.dataframe(
        resumo_ponto.rename(columns={
            "ponto": "Ponto", "capacidade_total": "Capacidade (mil m³/dia)",
            "contratos": "Contratos", "carregadores": "Carregadores Únicos",
        }),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Breakdown da capacidade ativa por ponto, por carregador")
    carreg_order = ativos.groupby("carregador")["capacidade"].sum().sort_values(ascending=False).index.tolist()
    breakdown = ativos.groupby(["ponto", "carregador"], as_index=False)["capacidade"].sum()
    ordem_pontos = ativos.groupby("ponto")["capacidade"].sum().sort_values(ascending=False).index.tolist()
    fig_bd = px.bar(
        breakdown, x="ponto", y="capacidade", color="carregador",
        category_orders={"ponto": ordem_pontos, "carregador": carreg_order},
        color_discrete_map=color_map_all(carreg_order),
        labels={"ponto": "", "capacidade": "Capacidade (mil m³/dia)", "carregador": "Carregador"},
    )
    fig_bd.update_layout(height=560)
    st.plotly_chart(fig_bd, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 4: Evolução Temporal
# ---------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Capacidade contratada vigente ao longo do tempo, por ponto/zona")
    st.caption("Considera todos os contratos do filtro (ativos e concluídos) vigentes em cada data, pelo intervalo Início–Término.")

    def _evolucao_por_ponto(fluxo: str) -> None:
        sub = fdf[fdf["fluxo"] == fluxo]
        if sub.empty:
            st.info(f"Sem contratos de {fluxo.lower()} no filtro atual.")
            return
        ponto_grp, ponto_order = top_n_with_other(sub, "ponto", "capacidade", n=7)
        sub = sub.assign(ponto_grp=ponto_grp)
        serie = capacity_timeline(sub, group_col="ponto_grp")
        if serie.empty:
            st.info(f"Sem dados suficientes para a série de {fluxo.lower()}.")
            return
        fig = px.area(
            serie, x="data", y="capacidade", color="ponto_grp",
            category_orders={"ponto_grp": ponto_order},
            color_discrete_map=color_map_for(ponto_order),
            labels={"data": "", "capacidade": "Capacidade vigente (mil m³/dia)", "ponto_grp": "Ponto"},
        )
        fig.update_traces(line_shape="hv")
        fig.update_layout(title=fluxo)
        st.plotly_chart(fig, use_container_width=True)

    col_e, col_s = st.columns(2)
    with col_e:
        _evolucao_por_ponto("Entrada")
    with col_s:
        _evolucao_por_ponto("Saída")

    st.divider()
    st.subheader("Capacidade contratada vigente ao longo do tempo, por carregador")
    st.caption("Considera os contratos do filtro atual (Status conforme selecionado na barra lateral), agregando todos os pontos/zonas selecionados.")

    def _evolucao_por_carregador(fluxo: str) -> None:
        sub = fdf[fdf["fluxo"] == fluxo]
        if sub.empty:
            st.info(f"Sem contratos de {fluxo.lower()} no filtro atual.")
            return
        carreg_order = sub.groupby("carregador")["capacidade"].sum().sort_values(ascending=False).index.tolist()
        serie = capacity_timeline(sub, group_col="carregador")
        if serie.empty:
            st.info(f"Sem dados suficientes para a série de {fluxo.lower()}.")
            return
        fig = px.area(
            serie, x="data", y="capacidade", color="carregador",
            category_orders={"carregador": carreg_order},
            color_discrete_map=color_map_all(carreg_order),
            labels={"data": "", "capacidade": "Capacidade vigente (mil m³/dia)", "carregador": "Carregador"},
        )
        fig.update_traces(line_shape="hv")
        fig.update_layout(title=fluxo)
        st.plotly_chart(fig, use_container_width=True)

    col_e2, col_s2 = st.columns(2)
    with col_e2:
        _evolucao_por_carregador("Entrada")
    with col_s2:
        _evolucao_por_carregador("Saída")

    st.divider()
    st.subheader("Novos contratos por mês de início")
    por_mes = fdf.groupby(["mes_inicio", "status"], as_index=False)["contrato"].count().rename(columns={"contrato": "contratos"})
    fig2 = px.bar(por_mes, x="mes_inicio", y="contratos", color="status", color_discrete_map=COLOR_STATUS,
                  labels={"mes_inicio": "", "contratos": "Nº de contratos", "status": "Status"})
    st.plotly_chart(fig2, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 5: Tarifas
# ---------------------------------------------------------------------------
with tabs[4]:
    ativos = fdf[fdf["status"] == "Ativo"]
    media_geral = weighted_avg(ativos, "tarifa", "capacidade")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tarifa Média Ponderada (ativos)", fmt_num(media_geral, 2))
    c2.metric("Tarifa Mínima (ativos)", fmt_num(ativos["tarifa"].min(), 2))
    c3.metric("Tarifa Máxima (ativos)", fmt_num(ativos["tarifa"].max(), 2))
    c4.metric("Desvio Padrão (ativos)", fmt_num(ativos["tarifa"].std(), 2))

    st.divider()
    st.subheader("Tarifa por Transportadora")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Média ponderada pela capacidade contratada (ativos)")
        tarifa_transp = (
            ativos.groupby("transportadora")
            .apply(lambda g: pd.Series({"tarifa": weighted_avg(g, "tarifa", "capacidade")}), include_groups=False)
            .reset_index()
            .sort_values("tarifa", ascending=False)
        )
        fig = px.bar(tarifa_transp, x="tarifa", y="transportadora", orientation="h", color_discrete_sequence=[BRAND_BLUE],
                     labels={"tarifa": "Tarifa média ponderada (R$/MMBTU)", "transportadora": ""})
        fig.update_layout(yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.caption("Dispersão das tarifas praticadas (todos os contratos do filtro)")
        fig = px.box(fdf, x="transportadora", y="tarifa", color="fluxo", color_discrete_map=COLOR_FLUXO,
                     labels={"transportadora": "", "tarifa": "Tarifa (R$/MMBTU)", "fluxo": "Fluxo"})
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Tarifa média por Transportadora x Produto (ativos)")
    st.caption("Média ponderada pela capacidade contratada. Células em branco = combinação sem contratos ativos no filtro.")
    pivot_tarifa = (
        ativos.groupby(["transportadora", "produto"])
        .apply(lambda g: weighted_avg(g, "tarifa", "capacidade"), include_groups=False)
        .unstack("produto")
    )
    if pivot_tarifa.empty:
        st.info("Sem contratos ativos suficientes para montar essa comparação.")
    else:
        fig = px.imshow(pivot_tarifa, aspect="auto", color_continuous_scale=BLUE_SCALE,
                         labels={"x": "Produto", "y": "Transportadora", "color": "Tarifa Média"})
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Evolução da tarifa contratada por ponto/zona")
    st.caption("Tarifa de cada novo contrato ao longo do tempo (pela data de início), para os pontos selecionados.")
    pontos_por_volume = fdf["ponto"].value_counts().index.tolist()
    pontos_sel_tarifa = st.multiselect(
        "Pontos para comparar", sorted(fdf["ponto"].dropna().unique()), default=pontos_por_volume[:5], key="tarifa_pontos_evolucao"
    )
    sub_evol = fdf[fdf["ponto"].isin(pontos_sel_tarifa)].sort_values("data_inicio")
    if sub_evol.empty:
        st.info("Selecione ao menos um ponto para ver a evolução da tarifa.")
    else:
        ponto_grp, ponto_order = top_n_with_other(sub_evol, "ponto", "capacidade", n=7)
        sub_evol = sub_evol.assign(ponto_grp=ponto_grp)
        fig = px.line(
            sub_evol, x="data_inicio", y="tarifa", color="ponto_grp", markers=True,
            category_orders={"ponto_grp": ponto_order}, color_discrete_map=color_map_for(ponto_order),
            hover_data=["carregador", "contrato", "transportadora"],
            labels={"data_inicio": "Data de Início", "tarifa": "Tarifa (R$/MMBTU)", "ponto_grp": "Ponto"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Evolução da tarifa média mensal")
    st.caption("Tarifa média ponderada pela capacidade, agregando todos os contratos com início em cada mês (dentro do filtro atual).")
    tarifa_mensal = (
        fdf.groupby("mes_inicio")
        .apply(lambda g: pd.Series({"tarifa": weighted_avg(g, "tarifa", "capacidade"), "contratos": len(g)}), include_groups=False)
        .reset_index()
    )
    if tarifa_mensal.empty:
        st.info("Sem dados suficientes para montar a série mensal.")
    else:
        fig = px.line(
            tarifa_mensal, x="mes_inicio", y="tarifa", markers=True, color_discrete_sequence=[BRAND_BLUE],
            hover_data={"contratos": True},
            labels={"mes_inicio": "Mês de Início", "tarifa": "Tarifa Média Ponderada (R$/MMBTU)"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Evolução da tarifa média mensal por ponto/zona")
    st.caption("Tarifa média ponderada pela capacidade, por mês de início, para os pontos selecionados acima em 'Pontos para comparar'.")
    if sub_evol.empty:
        st.info("Selecione ao menos um ponto (no filtro 'Pontos para comparar' acima) para ver essa série.")
    else:
        ponto_grp_mensal, ponto_order_mensal = top_n_with_other(sub_evol, "ponto", "capacidade", n=7)
        tarifa_mensal_ponto = (
            sub_evol.assign(ponto_grp=ponto_grp_mensal)
            .groupby(["mes_inicio", "ponto_grp"])
            .apply(lambda g: pd.Series({"tarifa": weighted_avg(g, "tarifa", "capacidade")}), include_groups=False)
            .reset_index()
        )
        fig = px.line(
            tarifa_mensal_ponto, x="mes_inicio", y="tarifa", color="ponto_grp", markers=True,
            category_orders={"ponto_grp": ponto_order_mensal}, color_discrete_map=color_map_for(ponto_order_mensal),
            labels={"mes_inicio": "Mês de Início", "tarifa": "Tarifa Média Ponderada (R$/MMBTU)", "ponto_grp": "Ponto"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Distribuição de tarifas por produto")
    fig = px.box(fdf, x="produto", y="tarifa", color="fluxo", color_discrete_map=COLOR_FLUXO,
                 labels={"produto": "", "tarifa": "Tarifa (R$/MMBTU)", "fluxo": "Fluxo"})
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Tarifa média por carregador vs. média geral (ativos)")
    cap_por_carregador = ativos.groupby("carregador")["capacidade"].sum().sort_values(ascending=False)
    n_carr = st.slider(
        "Top N carregadores (por capacidade ativa)", 5, max(5, len(cap_por_carregador)), min(15, len(cap_por_carregador)),
        key="tarifa_topn_carregador",
    )
    sub_carr = ativos[ativos["carregador"].isin(cap_por_carregador.head(n_carr).index)]
    if sub_carr.empty:
        st.info("Sem contratos ativos suficientes para essa comparação.")
    else:
        tarifa_carreg = (
            sub_carr.groupby("carregador")
            .apply(lambda g: pd.Series({"tarifa": weighted_avg(g, "tarifa", "capacidade")}), include_groups=False)
            .reset_index()
            .sort_values("tarifa")
        )
        tarifa_carreg["posicao"] = tarifa_carreg["tarifa"].apply(
            lambda v: "Abaixo da média geral" if v <= media_geral else "Acima da média geral"
        )
        fig = px.bar(
            tarifa_carreg, x="tarifa", y="carregador", orientation="h", color="posicao",
            color_discrete_map={"Abaixo da média geral": BRAND_BLUE, "Acima da média geral": BRAND_ORANGE},
            labels={"tarifa": "Tarifa média ponderada (R$/MMBTU)", "carregador": "", "posicao": ""},
        )
        fig.add_vline(x=media_geral, line_dash="dash", line_color=BRAND_SLATE)
        fig.add_annotation(x=media_geral, y=1.05, yref="paper", showarrow=False,
                            text=f"Média geral: {fmt_num(media_geral, 2)}", font=dict(color=BRAND_SLATE))
        fig.update_layout(height=max(420, 24 * len(tarifa_carreg)))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Tarifa x Capacidade Contratada")
        fig = px.scatter(fdf, x="capacidade", y="tarifa", color="fluxo", hover_data=["carregador", "ponto", "contrato"],
                          color_discrete_map=COLOR_FLUXO,
                          labels={"capacidade": "Capacidade (mil m³/dia)", "tarifa": "Tarifa (R$/MMBTU)", "fluxo": "Fluxo"})
        st.plotly_chart(fig, use_container_width=True)
    with col4:
        st.subheader("Tarifa x Duração do Contrato")
        fig = px.scatter(fdf, x="duracao_dias", y="tarifa", color="fluxo", hover_data=["carregador", "ponto", "contrato"],
                          color_discrete_map=COLOR_FLUXO,
                          labels={"duracao_dias": "Duração (dias)", "tarifa": "Tarifa (R$/MMBTU)", "fluxo": "Fluxo"})
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Distribuição geral das tarifas (ativos)")
    fig = px.histogram(ativos, x="tarifa", nbins=40, color_discrete_sequence=[BRAND_BLUE],
                        labels={"tarifa": "Tarifa (R$/MMBTU)"})
    fig.add_vline(x=media_geral, line_dash="dash", line_color=BRAND_ORANGE)
    fig.add_annotation(x=media_geral, y=1.05, yref="paper", showarrow=False,
                        text=f"Média ponderada: {fmt_num(media_geral, 2)}", font=dict(color=BRAND_SLATE))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 6: Rede (dados ANP/POC)
# ---------------------------------------------------------------------------
with tabs[5]:
    poc = load_poc_pontos()
    st.caption(
        "Fonte: Portal de Oferta de Capacidade (ANP) — dados oficiais por ponto de entrada/zona de "
        "saída de TBG, TAG e NTS, extraídos do mapa da rede de transporte."
    )
    st.warning(
        "⚠️ O ponto 'Paulínia' (NTS, entrada) traz Capacidade Técnica = 1.250.000 mil m³/dia na fonte "
        "original — cerca de 30x maior que qualquer outro ponto da base (o segundo maior é 40.000). "
        "Isso parece um erro de digitação da própria ANP/POC e distorce totais e comparações de "
        "Capacidade Técnica. O valor foi mantido como veio da fonte (nenhum dado foi alterado), mas "
        "desconsidere-o ao interpretar os gráficos de Capacidade Técnica abaixo.",
        icon="⚠️",
    )

    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        transp_poc = st.multiselect(
            "Transportadora", sorted(poc["Transportadora"].unique()), default=list(poc["Transportadora"].unique()), key="poc_transp"
        )
    with fcol2:
        fluxo_poc = st.multiselect(
            "Fluxo", sorted(poc["Fluxo"].unique()), default=list(poc["Fluxo"].unique()), key="poc_fluxo"
        )
    with fcol3:
        uf_poc = st.multiselect("UF", sorted(poc["UF"].unique()), key="poc_uf")

    pmask = poc["Transportadora"].isin(transp_poc) & poc["Fluxo"].isin(fluxo_poc)
    if uf_poc:
        pmask &= poc["UF"].isin(uf_poc)
    pdf = poc[pmask].copy()

    if pdf.empty:
        st.warning("Nenhum ponto encontrado com os filtros selecionados.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pontos", fmt_num(len(pdf)))
        c2.metric("Capacidade Técnica Total", fmt_num(pdf[POC_COL_TECNICA].sum(), 1))
        c3.metric("Capacidade Comercial Total", fmt_num(pdf[POC_COL_COMERCIAL].sum(), 1))
        c4.metric("Capacidade Contratada Total", fmt_num(pdf[POC_COL_CONTRATADA].sum(), 1))

        st.divider()
        st.subheader("Capacidade em uma cidade específica")
        cidade = st.selectbox("Município", sorted(pdf["Município"].unique()), key="poc_cidade")
        cdf = pdf[pdf["Município"] == cidade]
        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("Capacidade Técnica", fmt_num(cdf[POC_COL_TECNICA].sum(), 1))
        cc2.metric("Capacidade Comercial", fmt_num(cdf[POC_COL_COMERCIAL].sum(), 1))
        cc3.metric("Capacidade Disponível", fmt_num(cdf[POC_COL_DISPONIVEL].sum(), 1))
        cc4.metric("Capacidade Contratada", fmt_num(cdf[POC_COL_CONTRATADA].sum(), 1))
        st.dataframe(
            cdf[["Transportadora", "Localidade", "Ponto Zona (sigla)", "Fluxo", POC_COL_TECNICA, POC_COL_COMERCIAL, POC_COL_DISPONIVEL, POC_COL_CONTRATADA, POC_COL_TARIFA]],
            use_container_width=True, hide_index=True,
        )

        st.divider()
        st.subheader("Top N cidades por capacidade")
        metrica_cidade = st.selectbox(
            "Métrica", [POC_COL_COMERCIAL, POC_COL_TECNICA, POC_COL_DISPONIVEL, POC_COL_CONTRATADA], key="poc_metrica_cidade"
        )
        n_cidades = pdf["Município"].nunique()
        top_n_cidade = st.slider("Top N cidades", 5, max(5, n_cidades), min(15, n_cidades), key="poc_topn_cidade")
        por_cidade = (
            pdf.groupby("Município", as_index=False)[metrica_cidade].sum()
            .sort_values(metrica_cidade, ascending=False).head(top_n_cidade)
        )
        fig = px.bar(por_cidade, x=metrica_cidade, y="Município", orientation="h", color_discrete_sequence=[BRAND_BLUE])
        fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 26 * len(por_cidade)))
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Capacidade Técnica x Comercial por ponto")
        st.caption(
            "Pontos abaixo da linha tracejada têm capacidade comercial menor que a técnica (o mais comum); acima dela, o "
            "inverso. Eixos em escala logarítmica devido à grande amplitude de valores (inclusive o outlier de Paulínia)."
        )
        scatter_df = pdf[(pdf[POC_COL_TECNICA] > 0) & (pdf[POC_COL_COMERCIAL] > 0)]
        fig = px.scatter(
            scatter_df, x=POC_COL_TECNICA, y=POC_COL_COMERCIAL, color="Fluxo", color_discrete_map=COLOR_FLUXO,
            log_x=True, log_y=True,
            hover_data=["Localidade", "Município", "Transportadora"],
            labels={POC_COL_TECNICA: "Capacidade Técnica", POC_COL_COMERCIAL: "Capacidade Comercial"},
        )
        min_val = float(min(scatter_df[POC_COL_TECNICA].min(), scatter_df[POC_COL_COMERCIAL].min()))
        max_val = float(max(scatter_df[POC_COL_TECNICA].max(), scatter_df[POC_COL_COMERCIAL].max()))
        fig.add_shape(type="line", x0=min_val, y0=min_val, x1=max_val, y1=max_val, line=dict(color=BRAND_SLATE, dash="dash"))
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Top N pontos/zonas por Capacidade Comercial")
            n1 = st.slider("Top N", 5, 30, 15, key="poc_topn_comercial")
            top = pdf.nlargest(n1, POC_COL_COMERCIAL)
            fig = px.bar(top, x=POC_COL_COMERCIAL, y="Localidade", orientation="h", color_discrete_sequence=[BRAND_BLUE])
            fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 26 * len(top)))
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            st.subheader("Top N pontos/zonas por Capacidade Disponível")
            n2 = st.slider("Top N", 5, 30, 15, key="poc_topn_disp_max")
            top = pdf.nlargest(n2, POC_COL_DISPONIVEL)
            fig = px.bar(top, x=POC_COL_DISPONIVEL, y="Localidade", orientation="h", color_discrete_sequence=[BRAND_GREEN])
            fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 26 * len(top)))
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Pontos/zonas mais saturados (menor Capacidade Disponível da Zona)")
        st.caption(
            "Saturação medida pela Capacidade Disponível da Zona: quanto menor, mais saturado. "
            "Valores negativos indicam zonas já contratadas além da capacidade comercial registrada."
        )
        n3 = st.slider("Top N", 5, 30, 15, key="poc_topn_disp_min")
        bottom = pdf[pdf[POC_COL_DISPONIVEL].notna()].nsmallest(n3, POC_COL_DISPONIVEL)
        fig = px.bar(bottom, x=POC_COL_DISPONIVEL, y="Localidade", orientation="h", color_discrete_sequence=[BRAND_ORANGE])
        fig.update_layout(yaxis=dict(categoryorder="total descending"), height=max(400, 26 * len(bottom)))
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        col_c, col_d = st.columns(2)
        with col_c:
            st.subheader("Capacidade por Transportadora")
            por_transp = (
                pdf.groupby("Transportadora", as_index=False)[[POC_COL_TECNICA, POC_COL_COMERCIAL, POC_COL_CONTRATADA]].sum()
                .melt(id_vars="Transportadora", var_name="Métrica", value_name="Capacidade")
            )
            fig = px.bar(por_transp, x="Transportadora", y="Capacidade", color="Métrica", barmode="group",
                         color_discrete_sequence=PALETTE)
            st.plotly_chart(fig, use_container_width=True)
        with col_d:
            st.subheader("Capacidade Comercial por UF")
            por_uf = pdf.groupby("UF", as_index=False)[POC_COL_COMERCIAL].sum().sort_values(POC_COL_COMERCIAL, ascending=False)
            fig = px.bar(por_uf, x=POC_COL_COMERCIAL, y="UF", orientation="h", color_discrete_sequence=[BRAND_BLUE])
            fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 22 * len(por_uf)))
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Nossa capacidade contratada (contratos ANP) vs. Capacidade Contratada oficial (POC)")
        st.caption(
            "Cruza a 'Ponto Zona (sigla)' do POC com o campo 'Ponto' dos nossos contratos. Só aparecem pontos "
            "com correspondência exata de sigla — pontos com nomenclaturas diferentes entre as duas fontes não entram aqui."
        )
        nossa = (
            fdf[fdf["status"] == "Ativo"].groupby("ponto", as_index=False)["capacidade"].sum()
            .rename(columns={"ponto": "Ponto Zona (sigla)", "capacidade": "Nossa Base (contratos ANP)"})
        )
        oficial = (
            pdf.groupby("Ponto Zona (sigla)", as_index=False)[POC_COL_CONTRATADA].sum()
            .rename(columns={POC_COL_CONTRATADA: "POC (oficial)"})
        )
        comp = oficial.merge(nossa, on="Ponto Zona (sigla)", how="inner").sort_values("POC (oficial)", ascending=False).head(20)
        if comp.empty:
            st.info("Nenhuma correspondência de sigla encontrada entre as duas bases, dentro do filtro atual.")
        else:
            comp_long = comp.melt(id_vars="Ponto Zona (sigla)", var_name="Fonte", value_name="Capacidade")
            fig = px.bar(
                comp_long, x="Capacidade", y="Ponto Zona (sigla)", color="Fonte", orientation="h", barmode="group",
                color_discrete_map={"Nossa Base (contratos ANP)": BRAND_BLUE, "POC (oficial)": BRAND_ORANGE},
            )
            fig.update_layout(yaxis=dict(categoryorder="total ascending"), height=max(400, 26 * len(comp)))
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Tabela completa")
        st.dataframe(pdf.sort_values(POC_COL_COMERCIAL, ascending=False), use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Baixar CSV (pontos POC filtrados)",
            pdf.to_csv(index=False).encode("utf-8-sig"),
            file_name="pontos_rede_transporte_poc_filtrado.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
# Tab 7: Tabela Detalhada
# ---------------------------------------------------------------------------
with tabs[6]:
    st.subheader("Dados detalhados (com filtros do menu lateral aplicados)")
    cols_show = [
        "transportadora", "contrato", "status", "subtipo", "carregador", "produto", "ponto", "fluxo",
        "data_inicio", "data_fim", "duracao_dias", "tarifa", "multiplicador", "capacidade", "dias_para_vencer",
    ]
    display_df = fdf[cols_show].rename(columns=DISPLAY_LABELS).sort_values(DISPLAY_LABELS["data_inicio"], ascending=False)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Baixar CSV filtrado",
        display_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="contratos_transporte_filtrado.csv",
        mime="text/csv",
    )
