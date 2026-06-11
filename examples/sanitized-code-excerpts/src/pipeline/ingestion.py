#!/usr/bin/env python3
import argparse
import pandas as pd
import logging
import datetime
import os
import requests
from concurrent.futures import ThreadPoolExecutor
import urllib3
import time

# For database interactions via SQLAlchemy:
from sqlalchemy import create_engine

# Disable SSL warnings (for development use only)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Define ANSI escape codes for colors (Blue for INFO logs)
BLUE = "\033[94m"
RESET = "\033[0m"

# Remove existing logging handlers to prevent duplicates
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format=f"{BLUE}%(asctime)s - %(levelname)s - %(message)s{RESET}",
    handlers=[logging.StreamHandler()]
)

# ========================================================================
# Database Setup via SQLAlchemy
# ========================================================================
# Get the absolute path to the project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "market_data.db")
DATABASE_URI = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URI, echo=False)

# ========================================================================
# Schwab OAuth & API Configuration
# ========================================================================
SCHWAB_APP_KEY = os.getenv("SCHWAB_APP_KEY")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
SCHWAB_CALLBACK_URL = "https://127.0.0.1:8182/callback"  # Must match your developer portal
SCHWAB_TOKEN_PATH = os.getenv("SCHWAB_TOKEN_PATH", "./.local/schwab_token.json")
SCHWAB_RESOURCE_VERSION = "1"

from schwab.auth import easy_client


def validate_schwab_config():
    missing = [
        name
        for name, value in {
            "SCHWAB_APP_KEY": SCHWAB_APP_KEY,
            "SCHWAB_APP_SECRET": SCHWAB_APP_SECRET,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required Schwab OAuth environment variables: "
            + ", ".join(missing)
        )


# ========================================================================
# Helper Functions for Date Ranges and Intervals
# ========================================================================
def get_interval_offset(interval):
    try:
        if interval.endswith("d"):
            return pd.DateOffset(days=int(interval[:-1]))
        elif interval.endswith("wk"):
            return pd.DateOffset(weeks=int(interval[:-2]))
        elif interval.endswith("mo"):
            return pd.DateOffset(months=int(interval[:-2]))
        else:
            return pd.DateOffset(days=1)
    except Exception as e:
        logging.error(f"Error parsing interval '{interval}': {e}")
        return pd.DateOffset(days=1)

# ========================================================================
# Aggregation Helpers (Using "Datetime" as index)
# ========================================================================
def aggregate_to_1h(df_30m):
    df = df_30m.copy()
    df.set_index("Datetime", inplace=True)
    df_1h = df.resample("1h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna().reset_index()
    df_1h["Ticker"] = df["Ticker"].iloc[0]
    return df_1h

# ========================================================================
# Database Query Helper
# ========================================================================
def get_last_datetime_db(ticker, engine):
    """
    Queries the SQLite database for the latest datetime for the given ticker.
    Returns a Timestamp (or None if no data exists).
    """
    query = "SELECT MAX(datetime) as last_dt FROM historical_data WHERE ticker = ?"
    try:
        df = pd.read_sql_query(query, engine, params=(ticker,))
        if pd.notnull(df['last_dt'].iloc[0]):
            return pd.to_datetime(df['last_dt'].iloc[0])
        else:
            return None
    except Exception as e:
        # Table might not exist yet
        return None

# ========================================================================
# Historical Data Retrieval via Schwab API
# ========================================================================
def fetch_data_via_schwab(ticker, period, interval, start_date=None, end_date=None, client=None):
    """
    Fetches historical price data for a given ticker and interval.
    For 1h intervals, data is aggregated from 30-minute bars.
    API timestamps are assumed to be in epoch milliseconds.
    """
    try:
        if interval == "1d":
            resp = client.get_price_history_every_day(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval == "1wk":
            resp = client.get_price_history_every_week(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval == "1mo":
            # Request monthly data directly via the API using period_type "year"
            resp = client.get_price_history(
                ticker,
                period_type="year",     # pass as string
                period="20",            # Up to 20 years of data
                frequency_type="monthly",  # pass as string
                frequency="1",
                start_datetime=start_date,
                end_datetime=end_date
            )
        elif interval == "1m":
            resp = client.get_price_history_every_minute(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval == "5m":
            resp = client.get_price_history_every_five_minutes(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval == "15m":
            resp = client.get_price_history_every_fifteen_minutes(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval == "30m":
            resp = client.get_price_history_every_thirty_minutes(ticker, start_datetime=start_date, end_datetime=end_date)
        elif interval in ["60m", "1h"]:
            # For 1h, retrieve 30-minute data and aggregate
            resp = client.get_price_history_every_thirty_minutes(ticker, start_datetime=start_date, end_datetime=end_date)
            resp.raise_for_status()
            history = resp.json()
            candles = history.get("candles", [])
            if not candles:
                logging.error(f"No 30-minute data returned for {ticker} needed for 1h aggregation")
                return pd.DataFrame()
            df_30m = pd.DataFrame(candles)
            if "date" in df_30m.columns:
                df_30m["Datetime"] = pd.to_datetime(df_30m["date"])
            elif "timestamp" in df_30m.columns:
                df_30m["Datetime"] = pd.to_datetime(df_30m["timestamp"], unit="ms")
            elif "time" in df_30m.columns:
                df_30m["Datetime"] = pd.to_datetime(df_30m["time"], unit="ms")
            elif "datetime" in df_30m.columns:
                df_30m["Datetime"] = pd.to_datetime(df_30m["datetime"], unit="ms")
            else:
                logging.error(f"Timestamp column not found in 30m data for {ticker}")
                return pd.DataFrame()
            df_30m.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume"
            }, inplace=True)
            df_30m["Ticker"] = ticker
            df_30m.sort_values("Datetime", inplace=True)
            return aggregate_to_1h(df_30m)
        else:
            # Default: assume daily data
            resp = client.get_price_history_every_day(ticker, start_datetime=start_date, end_datetime=end_date)
        resp.raise_for_status()
        history = resp.json()
        candles = history.get("candles", [])
        if not candles:
            logging.error(f"No historical data returned for {ticker}")
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        if "date" in df.columns:
            df["Datetime"] = pd.to_datetime(df["date"])
        elif "timestamp" in df.columns:
            df["Datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        elif "time" in df.columns:
            df["Datetime"] = pd.to_datetime(df["time"], unit="ms")
        elif "datetime" in df.columns:
            df["Datetime"] = pd.to_datetime(df["datetime"], unit="ms")
        else:
            logging.error(f"Timestamp column not found in data for {ticker}")
            return pd.DataFrame()
        df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume"
        }, inplace=True)
        df["Ticker"] = ticker
        df.sort_values("Datetime", inplace=True)
        return df
    except Exception as e:
        logging.error(f"Error fetching data for {ticker} via Schwab API: {e}")
        return pd.DataFrame()

# ========================================================================
# Wrapper Function: fetch_ticker_data
# ========================================================================
def fetch_ticker_data(ticker, interval, client):
    """
    For each ticker, this function queries the database for the latest datetime,
    then fetches new data from the Schwab API (only new rows). It also adds the
    current interval to the data.
    """
    try:
        last_dt = get_last_datetime_db(ticker, engine)
        if last_dt is None:
            period_val = "max"
            start_dt, end_dt = None, None
        else:
            period_val = None
            offset = get_interval_offset(interval)
            start_dt = last_dt + offset
            end_dt = pd.Timestamp.today() + pd.DateOffset(1)
        df_new = fetch_data_via_schwab(ticker, period_val, interval, start_dt, end_dt, client=client)
        if not df_new.empty:
            logging.info(f"Fetched {len(df_new)} new rows for {ticker} in {interval}.")
            df_new = df_new.sort_values("Datetime")
            df_new['candle_pct_change'] = df_new.groupby("Ticker")["Close"].pct_change() * 100
            df_new["Interval"] = interval
            return df_new
        else:
            logging.info(f"No new data for {ticker} in {interval}.")
            return None
    except Exception as e:
        logging.error(f"Error fetching data for {ticker}: {e}")
        return None

# ========================================================================
# Main Historical Update Function
# ========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Download historical stock data via Charles Schwab API and update the local SQLite database."
    )
    parser.add_argument("--file", type=str,
                        default="examples/sample_watchlist.xlsx",
                        help="Path to the Excel file that contains the ticker list.")
    parser.add_argument("--ticker_column", type=str, default="Ticker",
                        help="Column name in the Excel file that contains ticker symbols.")
    parser.add_argument("--sheet", type=str, default="Tickers",
                        help="Sheet name that contains ticker symbols (watchlist).")
    parser.add_argument("--start", type=str,
                        help="Start date (YYYY-MM-DD); (optional, used by the API if needed).")
    parser.add_argument("--end", type=str,
                        help="End date (YYYY-MM-DD); (optional, used by the API if needed).")
    parser.add_argument("--interval", type=str, default="1d",
                        help="Default data interval (e.g., '1d', '1wk', '1mo', '1m', etc.).")
    parser.add_argument("--timeframes", type=str, default="1d,1wk,1mo,1m,5m,15m,30m,60m",
                        help="Comma-separated list of intervals to fetch.")
    args = parser.parse_args()

    intervals = [x.strip() for x in args.timeframes.split(",")]
    file_path = args.file
    watchlist_sheet_name = args.sheet

    # Read ticker list from the Excel file using pandas
    try:
        tickers_df = pd.read_excel(file_path, sheet_name=watchlist_sheet_name)
        tickers = tickers_df[args.ticker_column].dropna().tolist()
        if not tickers:
            logging.error("No tickers found in the watchlist!")
            return
    except Exception as e:
        logging.error(f"Failed to load tickers: {e}")
        return

    # Create Schwab client with enum enforcement disabled
    try:
        validate_schwab_config()
        client = easy_client(
            api_key=SCHWAB_APP_KEY,
            app_secret=SCHWAB_APP_SECRET,
            callback_url=SCHWAB_CALLBACK_URL,
            token_path=SCHWAB_TOKEN_PATH,
            interactive=True,
            callback_timeout=300.0,
            enforce_enums=False   # disable enum enforcement so we can pass strings
        )
    except Exception as e:
        logging.error(f"Failed to create Schwab client: {e}")
        return

    total_new_rows = 0
    for interval in intervals:
        new_data_list = []
        logging.info(f"Processing interval: {interval}")
        MAX_WORKERS = 5
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = executor.map(lambda t: fetch_ticker_data(t, interval, client), tickers)
            for res in results:
                if res is not None and not res.empty:
                    new_data_list.append(res)
        if new_data_list:
            new_data_df = pd.concat(new_data_list, ignore_index=True)
            # Drop any duplicate rows based on our unique key:
            new_data_df.drop_duplicates(subset=["Ticker", "Datetime", "Interval"], inplace=True)
            new_data_df.to_sql('historical_data', engine, if_exists='append', index=False)
            rows_added = len(new_data_df)
            total_new_rows += rows_added
            logging.info(f"Appended {rows_added} new rows for interval {interval} to the database.")
        else:
            logging.info(f"No new data to append for interval {interval}.")

    logging.info(f"Total new rows added to the database: {total_new_rows}")

if __name__ == "__main__":
    main()
