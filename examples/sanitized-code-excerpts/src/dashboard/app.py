import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import os

# =======================
# Configuration & Setup
# =======================
st.set_page_config(page_title="Institutional Market Data Engine", layout="wide")
st.title("📈 Institutional Market Data Engine")
st.markdown("""
**Data Source:** Authorized market-data provider via OAuth-style access
**Pipeline:** Python ThreadPoolExecutor -> SQLite  
**Intervals:** Minute-level to Daily  
""")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "market_data.db")

@st.cache_resource
def get_db_connection():
    # Only connect if the database exists
    if not os.path.exists(DB_PATH):
        return None
    return sqlite3.connect(DB_PATH, check_same_thread=False)

conn = get_db_connection()

if conn is None:
    st.warning("Database not found. Please run the ingestion pipeline (`src/pipeline/ingestion.py`) first to populate the local SQLite database.")
    st.stop()

# =======================
# Data Loading
# =======================
@st.cache_data(ttl=600)
def load_available_tickers():
    query = "SELECT DISTINCT Ticker FROM historical_data ORDER BY Ticker"
    try:
        df = pd.read_sql_query(query, conn)
        return df["Ticker"].tolist()
    except Exception as e:
        st.error(f"Error loading tickers: {e}")
        return []

@st.cache_data(ttl=600)
def load_data(interval="1d"):
    query = f"SELECT * FROM historical_data WHERE Interval = '{interval}'"
    try:
        df = pd.read_sql_query(query, conn)
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.sort_values(by=["Ticker", "Datetime"])
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

tickers = load_available_tickers()
if not tickers:
    st.info("Database is empty. No tickers found.")
    st.stop()

# =======================
# User Selection Section
# =======================
col1, col2, col3 = st.columns(3)
with col1:
    selected_ticker = st.selectbox("Select a Stock Ticker for Chart:", tickers)
with col2:
    interval_options = ["1m", "5m", "15m", "30m", "60m", "1d", "1wk", "1mo"]
    selected_interval = st.selectbox("Select Data Interval:", interval_options, index=5)

# Load data based on selected interval
all_data = load_data(selected_interval)
if all_data.empty:
    st.warning(f"No data available for interval {selected_interval}.")
    st.stop()

selected_df = all_data[all_data["Ticker"] == selected_ticker].copy()

# =======================
# Single Ticker View
# =======================
if not selected_df.empty:
    last_price = selected_df["Close"].iloc[-1]
    change_pct = selected_df["candle_pct_change"].iloc[-1] if "candle_pct_change" in selected_df.columns else 0
    st.metric(label=f"{selected_ticker} Last Price", value=f"${last_price:.2f}", delta=f"{change_pct:.2f}%")

    fig_single = go.Figure(data=[go.Candlestick(
        x=selected_df['Datetime'],
        open=selected_df['Open'],
        high=selected_df['High'],
        low=selected_df['Low'],
        close=selected_df['Close'],
        name=selected_ticker
    )])
    fig_single.update_layout(
        title=f"{selected_ticker} Candlestick Chart ({selected_interval} interval)",
        yaxis_title="Price ($)",
        template="plotly_dark",
        xaxis_rangeslider_visible=False
    )
    st.plotly_chart(fig_single, use_container_width=True)
else:
    st.error(f"No data found for {selected_ticker} in this interval.")

# =======================
# Aggregated Stock Performance
# =======================
st.write("---")
st.write("## Aggregated Market Performance (% Change from Open)")

selected_tickers_for_agg = st.multiselect("Select Tickers for Aggregated Chart", tickers, default=tickers[:5])
aggregated_data = all_data[all_data["Ticker"].isin(selected_tickers_for_agg)].copy()

if not aggregated_data.empty:
    # Calculate performance from the first 'Open' in the loaded dataset for each ticker
    first_opens = aggregated_data.groupby('Ticker')['Open'].transform('first')
    aggregated_data["Close_pct"] = (aggregated_data["Close"] - first_opens) / first_opens * 100

    fig_agg = px.line(aggregated_data, x="Datetime", y="Close_pct", color="Ticker",
                      title=f"Relative Performance (% Change from First Open) - Interval: {selected_interval}",
                      labels={"Close_pct": "% Change", "Datetime": "Time"})
    fig_agg.update_layout(template="plotly_dark")
    st.plotly_chart(fig_agg, use_container_width=True)

# =======================
# Alternative Visualization: Sorted Heatmap
# =======================
st.write("---")
st.write("## Market Heatmap Ranking")

if st.checkbox("Show Sorted Heatmap with Ticker Labels"):
    # Pivot the data
    heatmap_data = all_data.pivot_table(index="Datetime", columns="Ticker", values="candle_pct_change")

    if heatmap_data.empty:
        st.error("No heatmap data available.")
    else:
        # We only want to show the last 20 periods for readability
        heatmap_data = heatmap_data.tail(20)
        
        sorted_values_list = []
        sorted_tickers_list = []
        for date, row in heatmap_data.iterrows():
            sorted_row = row.sort_values(ascending=False)
            sorted_values_list.append(sorted_row.values)
            sorted_tickers_list.append(sorted_row.index.tolist())

        sorted_values = pd.DataFrame(sorted_values_list, index=heatmap_data.index)
        sorted_tickers = pd.DataFrame(sorted_tickers_list, index=heatmap_data.index)

        rank_positions = list(range(1, sorted_values.shape[1] + 1))
        custom_colorscale = [[0.0, "red"], [0.5, "black"], [1.0, "green"]]

        fig_sorted_heatmap = go.Figure(data=go.Heatmap(
            z=sorted_values.values,
            x=rank_positions,
            y=sorted_values.index.astype(str),
            colorscale=custom_colorscale,
            colorbar=dict(title="% Change"),
            text=sorted_tickers.values,
            texttemplate="%{text}",
            zauto=True
        ))

        fig_sorted_heatmap.update_layout(
            title="Periodic Ranking Heatmap (1 = Highest % Gain)",
            xaxis_title="Rank",
            yaxis_title="Datetime",
            xaxis=dict(tickmode="array", tickvals=rank_positions),
            template="plotly_dark",
            height=600
        )

        st.plotly_chart(fig_sorted_heatmap, use_container_width=True)
