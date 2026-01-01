import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (加入錯誤攔截) ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_watchlist_from_google():
    default_list = ["2330.TW", "0050.TW", "AAPL", "NVDA"]
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        records = sheet.get_all_values()
        if len(records) > 1:
            return [row[0] for row in records[1:] if row[0]]
    except Exception as e:
        st.warning(f"目前無法連線至 Google Sheets (原因: {e})，暫時使用預設清單。")
    return default_list

def save_watchlist_to_google(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        sheet.clear()
        data = [["ticker"]] + [[t] for t in watchlist]
        sheet.update("A1", data)
        st.success("成功儲存至 Google 雲端！")
    except Exception as e:
        st.error(f"儲存失敗: {e}")

# --- 2. 初始化 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist_from_google()

# --- 3. 介面佈局 (先定義變數避免 NameError) ---
with st.sidebar:
    st.header("📋 追蹤清單")
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + st.session_state.watchlist)
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

# 佈局主標題與按鈕
col_title, col_btn = st.columns([4, 1])

with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
    # 這裡現在絕對不會報 NameError 了
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist.append(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist)
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
            if len(st.session_state.watchlist) > 1:
                st.session_state.watchlist.remove(ticker_input)
                save_watchlist_to_google(st.session_state.watchlist)
                st.rerun()

# --- 4. 數據抓取 (強化 2330.TW 相容性) ---
# --- 2. 核心演算法 (五線譜計算) ---
@st.cache_data(ttl=3600)
def get_lohas_data(ticker, years):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(years * 365))
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        df['x'] = np.arange(len(df))
        
        # 線性回歸
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        
        # 標準差通道
        std_dev = np.std(df['Close'] - df['TL'])
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope
    except:
        return None

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    if result:
        df, sd, slope = result
        price = float(df['Close'].iloc[-1])
        tl = df['TL'].iloc[-1]
        
        # 顯示指標
        m1, m2, m3 = st.columns(3)
        m1.metric("最新股價", f"{price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{tl:.2f}", f"{((price-tl)/tl)*100:+.2f}%")
        status = "💎 特價" if price < df['TL-2SD'].iloc[-1] else ("⚠️ 過熱" if price > df['TL+2SD'].iloc[-1] else "✅ 正常")
        m3.metric("目前狀態", status)

        # 繪圖
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL+2SD'], name='昂貴', line=dict(dash='dash', color='red')))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL'], name='中心', line=dict(color='gray')))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL-2SD'], name='便宜', line=dict(dash='dash', color='green')))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error(f"無法抓取 {ticker_input} 的數據。")
