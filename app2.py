import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 連線邏輯 ---
def get_gsheet_client():
    # 從 Streamlit Secrets 讀取憑證
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # 假設您在 Secrets 中設定了名為 "gcp_service_account" 的區塊
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_watchlist_from_google():
    try:
        client = get_gsheet_client()
        # 開啟試算表 (請替換成您的試算表名稱或 URL)
        sheet = client.open("MyWatchlist").sheet1
        # 讀取 A 欄所有資料並去掉標題
        records = sheet.get_all_values()
        if len(records) > 1:
            return [row[0] for row in records[1:] if row[0]]
    except Exception as e:
        st.error(f"Google 讀取失敗: {e}")
    return ["2330.TW", "0050.TW"]

def save_watchlist_to_google(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        # 清空並重新寫入
        sheet.clear()
        data = [["ticker"]] + [[t] for t in watchlist]
        sheet.update("A1", data)
    except Exception as e:
        st.error(f"Google 儲存失敗: {e}")

# --- 2. 初始化 Session State ---
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist_from_google()

# --- (其餘數據計算與圖表邏輯保持不變) ---
# ... (您的 get_lohas_data 函式與 UI 程式碼) ...

# 修改按鈕觸發部分：
with col_btn:
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist.append(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist) # 改成存到 Google
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
            st.session_state.watchlist.remove(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist) # 改成存到 Google
            st.rerun()
