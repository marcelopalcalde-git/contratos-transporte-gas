"""Carregamento e limpeza dos dados de contratos de transporte de gás natural (fonte: ANP)."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "tabela-contratos-all.xls"
POC_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "pontos_rede_transporte_poc.csv"

# Nomes de colunas (dados oficiais por ponto, extraídos do Portal de Oferta de Capacidade da ANP)
POC_COL_TECNICA = "Capacidade Técnica do Ponto (Mil m³/dia)"
POC_COL_COMERCIAL = "Capacidade Comercial da Zona (Mil m³/dia)"
POC_COL_DISPONIVEL = "Capacidade Disponível da Zona (Mil m³/dia)"
POC_COL_CONTRATADA = "Capacidade Contratada da Zona (Mil m³/dia)"
POC_COL_TARIFA = "Tarifa Referência (R$/MMBtu)"

COLUMN_MAP = {
    "Transportadora": "transportadora",
    "Status": "status",
    "Subtipo": "subtipo",
    "Contrato": "contrato",
    "Carregador": "carregador",
    "Produto": "produto",
    "Ponto de Entrada/Zona de Saída": "ponto",
    "Qualidade": "qualidade",
    "Fluxo": "fluxo",
    "Data de Início": "data_inicio",
    "Data de Término": "data_fim",
    "Tarifa (R$/MMBTU)": "tarifa",
    "Multiplicador tarifário": "multiplicador",
    "Capacidade Contratada(mil m³/dia)": "capacidade",
    "Relação Acionáriana Transportadora": "relacao_acionaria",
}

# Rótulos amigáveis para exibição (tabelas, eixos de gráfico)
DISPLAY_LABELS = {
    "transportadora": "Transportadora",
    "status": "Status",
    "subtipo": "Subtipo",
    "contrato": "Contrato",
    "carregador": "Carregador",
    "produto": "Produto",
    "ponto": "Ponto de Entrada/Zona de Saída",
    "fluxo": "Fluxo",
    "data_inicio": "Data de Início",
    "data_fim": "Data de Término",
    "tarifa": "Tarifa (R$/MMBTU)",
    "multiplicador": "Multiplicador Tarifário",
    "capacidade": "Capacidade Contratada (mil m³/dia)",
    "duracao_dias": "Duração (dias)",
    "ano_inicio": "Ano de Início",
    "dias_para_vencer": "Dias até o Vencimento",
}


def _parse_br_number(series: pd.Series) -> pd.Series:
    """Converte strings numéricas no formato BR ('3.000,00') para float."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace("%", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


@st.cache_data(show_spinner=False)
def load_data(path: str | Path | None = None, file_bytes: bytes | None = None) -> pd.DataFrame:
    """Lê a planilha de contratos da TBG e devolve um DataFrame limpo e tipado."""
    source = file_bytes if file_bytes is not None else (path or DEFAULT_DATA_PATH)
    raw = pd.read_excel(source, sheet_name="Contratos")
    raw = raw.rename(columns=COLUMN_MAP)

    df = raw.copy()
    df["data_inicio"] = pd.to_datetime(df["data_inicio"], format="%d/%m/%Y", errors="coerce")
    df["data_fim"] = pd.to_datetime(df["data_fim"], format="%d/%m/%Y", errors="coerce")

    for col in ["tarifa", "multiplicador", "capacidade"]:
        df[col] = _parse_br_number(df[col])

    df["relacao_acionaria"] = _parse_br_number(df["relacao_acionaria"])

    df["duracao_dias"] = (df["data_fim"] - df["data_inicio"]).dt.days
    df["ano_inicio"] = df["data_inicio"].dt.year
    df["mes_inicio"] = df["data_inicio"].dt.to_period("M").dt.to_timestamp()

    hoje = pd.Timestamp.today().normalize()
    df["dias_para_vencer"] = (df["data_fim"] - hoje).dt.days

    # Colunas constantes na base (mantidas apenas para referência, não usadas nas análises)
    df.attrs["colunas_constantes"] = [
        c for c in ["transportadora", "qualidade"] if df[c].nunique(dropna=False) <= 1
    ]

    return df


@st.cache_data(show_spinner=False)
def load_poc_pontos(path: str | Path | None = None) -> pd.DataFrame:
    """Lê os dados oficiais por ponto extraídos do Portal de Oferta de Capacidade (POC/ANP)."""
    poc = pd.read_csv(path or POC_DEFAULT_PATH, encoding="utf-8-sig")
    poc["Município"] = poc["Município"].str.strip().str.title()
    return poc


def capacity_timeline(df: pd.DataFrame, group_col: str | None = None) -> pd.DataFrame:
    """Série temporal (diária) da capacidade contratada vigente, via sweep-line de início/fim.

    Se group_col for informado, retorna uma coluna por categoria (ex: Fluxo) com todas as séries
    reindexadas no mesmo eixo de datas (união dos eventos de todos os grupos, com forward-fill).
    Isso é necessário para que gráficos de área empilhada (px.area) somem corretamente em cada
    ponto do eixo x — o Plotly empilha usando os pontos de cada série individualmente, então
    séries esparsas e não alinhadas (ex: um carregador só tem eventos em datas diferentes de
    outro) produzem um empilhamento incorreto ("buracos") se não forem alinhadas antes.
    """
    base = df.dropna(subset=["data_inicio", "data_fim", "capacidade"])
    if base.empty:
        return pd.DataFrame(columns=["data"] + ([group_col] if group_col else ["capacidade"]))

    groups = base[group_col].unique() if group_col else [None]
    series_by_group: dict = {}
    for g in groups:
        sub = base if g is None else base[base[group_col] == g]
        starts = sub[["data_inicio", "capacidade"]].rename(columns={"data_inicio": "data"})
        ends = sub[["data_fim", "capacidade"]].rename(columns={"data_fim": "data"})
        ends["data"] = ends["data"] + pd.Timedelta(days=1)
        ends["capacidade"] = -ends["capacidade"]
        events = pd.concat([starts, ends]).groupby("data", as_index=True)["capacidade"].sum().sort_index()
        series_by_group[g] = events.cumsum()

    if group_col is None:
        return series_by_group[None].rename("capacidade").reset_index()

    todas_datas = sorted(set().union(*(s.index for s in series_by_group.values())))
    wide = pd.DataFrame(index=pd.DatetimeIndex(todas_datas))
    for g, s in series_by_group.items():
        wide[g] = s.reindex(wide.index).ffill().fillna(0)
    wide.index.name = "data"

    return wide.reset_index().melt(id_vars="data", var_name=group_col, value_name="capacidade")


def weighted_avg(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    """Média de `value_col` ponderada por `weight_col` (ex: tarifa ponderada pela capacidade)."""
    peso = df[weight_col].sum()
    if not peso:
        return float("nan")
    return (df[value_col] * df[weight_col]).sum() / peso


def top_n_with_other(
    df: pd.DataFrame, group_col: str, weight_col: str, n: int = 7, other_label: str = "Outros"
) -> tuple[pd.Series, list[str]]:
    """Agrupa `group_col` mantendo as N categorias de maior peso e somando o resto em `other_label`.

    Evita colorir gráficos categóricos com dezenas de séries (carregadores, pontos) quando a base
    passou a cobrir várias transportadoras. Retorna a série reagrupada e a ordem (top N + Outros).
    """
    totals = df.groupby(group_col)[weight_col].sum().sort_values(ascending=False)
    top = list(totals.head(n).index)
    grouped = df[group_col].where(df[group_col].isin(top), other_label)
    order = top + ([other_label] if (grouped == other_label).any() else [])
    return grouped, order
