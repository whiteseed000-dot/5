import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 核心雲端邏輯 ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def get_user_credentials():
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet("users")
        records = sheet.get_all_records()
        return {str(row['username']): str(row['password']) for row in records}
    except: return {"admin": "1234"}

def load_watchlist_from_google(username):
    default_dict = {"2330.TW": "台積電"}
    try:
        client = get_gsheet_client()
        spreadsheet = client.open("MyWatchlist")
        worksheet_list = [sh.title for sh in spreadsheet.worksheets()]
        
        if username not in worksheet_list:
            sheet = spreadsheet.add_worksheet(title=username, rows="100", cols="20")
            header_and_default = [["ticker", "name"], ["2330.TW", "台積電"]]
            sheet.update("A1", header_and_default)
            return default_dict
        else:
            sheet = spreadsheet.worksheet(username)
            records = sheet.get_all_values()
            if len(records) > 1:
                return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row and row[0]}
            else: return default_dict
    except: return default_dict

def save_watchlist_to_google(username, watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet(username)
        sheet.clear()
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
    except: pass

# --- 2. 登入系統 ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入 - 股市五線譜")
    st.title("🔐 樂活五線譜 Pro")
    with st.form("login"):
        user = st.text_input("帳號")
        pw = st.text_input("密碼", type="password")
        if st.form_submit_button("登入"):
            creds = get_user_credentials()
            if user in creds and creds[user] == pw:
                st.cache_data.clear() 
                st.session_state.authenticated = True
                st.session_state.username = user
                st.rerun()
            else: st.error("帳號或密碼錯誤")
    st.stop()

# --- 3. 初始化與技術指標 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username
if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

def get_technical_indicators(df):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['BIAS'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    df['MA60'] = df['Close'].rolling(window=60).mean()
    return df

# --- 4. 核心運算 (修正回傳 R2) ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker, years):
    try:
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))
        # 自動判斷上市櫃 (.TW / .TWO)
        search_list = [f"{ticker}.TW", f"{ticker}.TWO"] if ticker.isdigit() else [ticker]
        
        df = pd.DataFrame()
        for t in search_list:
            df = yf.download(t, start=start, end=end, progress=False)
            if not df.empty: break
            
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df['x'] = np.arange(len(df))
        
        slope, intercept, r_val, _, _ = stats.linregress(df['x'], df['Close'])
        r_squared = r_val ** 2
        df['TL'] = slope * df['x'] + intercept
        std = np.std(df['Close'] - df['TL'])
        df['TL+2SD'], df['TL+1SD'] = df['TL'] + 2*std, df['TL'] + std
        df['TL-1SD'], df['TL-2SD'] = df['TL'] - std, df['TL'] - 2*std
        
        df = get_technical_indicators(df)
        # KD 指標
        low_9 = df['Low'].rolling(9).min(); high_9 = df['High'].rolling(9).max()
        rsv = 100 * (df['Close'] - low_9) / (high_9 - low_9)
        df['K'] = rsv.ewm(com=2).mean(); df['D'] = df['K'].ewm(com=2).mean()
        df['BB_up'] = df['MA20'] + 2 * df['Close'].rolling(20).std()
        df['BB_low'] = df['MA20'] - 2 * df['Close'].rolling(20).std()
        return df, slope, r_squared
    except: return None

# --- 5. 側邊欄 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    ticker_input = st.text_input("股票代號", value=quick_pick.split(".")[0] if quick_pick != "-- 手動輸入 --" else "2330").upper().strip()
    stock_name = st.session_state.watchlist_dict.get(quick_pick if quick_pick != "-- 手動輸入 --" else ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    if st.button("🚪 登出帳號"):
        st.cache_data.clear()
        st.session_state.clear()
        st.rerun()

# --- 6. 主要介面 ---
st.markdown(f'# 📈 樂活五線譜: {ticker_input} {stock_name}')

result = get_stock_data(ticker_input, years_input)
if result:
    df, slope, r_squared = result
    curr = float(df['Close'].iloc[-1]); tl_last = df['TL'].iloc[-1]
    
    # KPI 儀表板
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最新股價", f"{curr:.2f}")
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{((curr-tl_last)/tl_last)*100:+.2f}%")
    m3.metric("趨勢斜率", f"{slope:.2f}")
    m4.metric("趨勢強度 (R²)", f"{r_squared:.2f}")

    # 技術指標儀表板 (I1-I5)
    st.divider()
    i1, i2, i3, i4, i5 = st.columns(5)
    c_rsi = df['RSI'].iloc[-1]; c_macd = df['MACD'].iloc[-1]
    i1.metric("RSI (14)", f"{c_rsi:.1f}", "🔥 超買" if c_rsi > 70 else ("❄️ 超跌" if c_rsi < 30 else "⚖️ 中性"))
    i2.metric("MACD 趨勢", f"{c_macd:.2f}", "📈 金叉" if c_macd > df['Signal'].iloc[-1] else "📉 死叉")
    i3.metric("月線乖離", f"{df['BIAS'].iloc[-1]:+.2f}%")
    i4.metric("季線位置", f"{df['MA60'].iloc[-1]:.1f}", "🚀 站上" if curr > df['MA60'].iloc[-1] else "🩸 跌破")
    i5.metric("強度評級", f"{r_squared:.2f}", "💎 極穩" if r_squared > 0.8 else "📈 穩定" if r_squared > 0.5 else "☁️ 隨機")

    # --- 7. 圖表展示 ---
    view_mode = st.radio("模式", ["五線譜", "K線", "成交量"], horizontal=True, label_visibility="collapsed")
    fig = go.Figure()
    
    if view_mode == "五線譜":
        # 收盤價線 (深綠色)
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#2D5E3F', width=2.5), name="收盤價"))
        # 五線譜與右側標籤
        lines = [('TL+2SD', 'red', '+2SD'), ('TL+1SD', 'orange', '+1SD'), ('TL', 'white', 'TL'), ('TL-1SD', 'royalblue', '-1SD'), ('TL-2SD', 'green', '-2SD')]
        for col, color, name in lines:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=color, width=1, dash='solid' if name=='TL' else 'dash'), name=name))
            # 右側價格標籤
            fig.add_annotation(x=df['Date'].iloc[-1], y=df[col].iloc[-1], text=f"<b>{df[col].iloc[-1]:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=color))

    # 白色現價指示線
    fig.add_hline(y=curr, line_dash="dot", line_color="white", annotation_text=f"現價:{curr}", annotation_position="bottom right")
    
    fig.update_layout(height=600, template="plotly_dark", paper_bgcolor='#0E1117', plot_bgcolor='#0E1117', margin=dict(r=80))
    st.plotly_chart(fig, use_container_width=True)

# --- 8. 掃描功能 (修正解構) ---
if st.button("🔄 執行全清單掃描"):
    summary = []
    for t, name in st.session_state.watchlist_dict.items():
        res = get_stock_data(t.split(".")[0], years_input)
        if res:
            tdf, _, tr2 = res
            p = float(tdf['Close'].iloc[-1])
            summary.append({"代號": t, "名稱": name, "現價": p, "R²": f"{tr2:.2f}"})
    st.table(pd.DataFrame(summary))
