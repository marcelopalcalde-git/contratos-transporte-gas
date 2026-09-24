# Contratos de Transporte de Gás Natural (dashboard)

Dashboard Streamlit para analisar contratos de transporte de gás natural (TBG, TAG, NTS — dados da ANP)
e capacidade oficial por ponto (Portal de Oferta de Capacidade).

## Rodar em outro computador

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run src\app.py
```

## Dados (`data/raw/`)
- `tabela-contratos-all.xls`: exportação da ANP (base padrão; também pode ser enviada pela barra lateral do app).
- `pontos_rede_transporte_poc.csv`: 203 pontos extraídos do mapa do Portal de Oferta de Capacidade.
