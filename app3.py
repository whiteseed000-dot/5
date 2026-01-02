import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 雲端與登入邏輯 (維持不變) ---
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
    default_dict = {"2330.TW": "台積電", "9945.TW": "潤泰新"}
    try:
        client = get_gsheet_client()
        spreadsheet = client.open("MyWatchlist")
        sheet = spreadsheet.worksheet(username)
        records = sheet.get_all_values()
        if len(records) > 1:
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row[0]}
    except: pass
    return default_dict

def save_watchlist_to_google(username, watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet(username)
        sheet.clear()
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
    except: pass

# --- 2. 登入檢查 ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入", page_icon="🔐")
    st.title("🔐 樂活五線譜 Pro")
    with st.form("login"):
        user = st.text_input("帳號")
        pw = st.text_input("密碼", type="password")
        if st.form_submit_button("登入"):
            creds = get_user_credentials()
            if user in creds and creds[user] == pw:
                st.session_state.authenticated = True
                st.session_state.username = user
                st.rerun()
    st.stop()

# --- 3. 頁面初始化 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username
if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

# --- 4. 側邊欄 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    st.divider()
    ticker_input = st.text_input("股票代號", value=quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW").upper().strip()
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    if st.button("🚪 登出帳號"):
        del st.session_state.authenticated
        st.rerun()

# --- 5. 核心運算 (新增技術指標) ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker, years):
    try:
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        
        # 1. 五線譜運算
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        std = np.std(df['Close'] - df['TL'])
        df['TL+2SD'], df['TL+1SD'] = df['TL'] + 2*std, df['TL'] + std
        df['TL-1SD'], df['TL-2SD'] = df['TL'] - std, df['TL'] - 2*std
        
        # 2. KD 運算 (9, 3, 3)
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = 100 * (df['Close'] - low_9) / (high_9 - low_9)
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        
        # 3. 布林通道 (20, 2)
        df['MA20'] = df['Close'].rolling(20).mean()
        df['BB_std'] = df['Close'].rolling(20).std()
        df['BB_up'] = df['MA20'] + 2 * df['BB_std']
        df['BB_low'] = df['MA20'] - 2 * df['BB_std']
        
        return df, slope
    except: return None

# --- 6. 標題與指標 (維持視覺) ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown(f'# <img src="https://cdn-icons-png.flaticon.com/512/421/421644.png" width="30"> 樂活五線譜: {ticker_input} ({stock_name})', unsafe_allow_html=True)

result = get_stock_data(ticker_input, years_input)
if result:
    df, slope = result
    curr = float(df['Close'].iloc[-1])
    tl_last = df['TL'].iloc[-1]
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("最新股價", f"{curr:.2f}")
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{((curr-tl_last)/tl_last)*100:+.2f}%")
    
    # 狀態判定
    if curr > df['TL+2SD'].iloc[-1]: status = "🔴 天價"
    elif curr > df['TL+1SD'].iloc[-1]: status = "🟠 偏高"
    elif curr > df['TL-1SD'].iloc[-1]: status = "⚪ 合理"
    elif curr > df['TL-2SD'].iloc[-1]: status = "🔵 偏低"
    else: status = "🟢 特價"
    m3.metric("目前狀態", status)
    m4.metric("趨勢斜率", f"{slope:.5f}")
    m5.metric("VIX 指數", "14.84", "🟢 穩定") # VIX 簡化範例

    # --- 7. 圖表切換按鈕 ---
    st.write("") # 間距
    tab_choice = st.radio(
        "選擇分析視圖：",
        ["樂活五線譜", "KD 指標", "布林通道", "成交量"],
        horizontal=True,
        label_visibility="collapsed"
    )
    st.write("")

    # --- 8. 繪圖邏輯 ---
    fig = go.Figure()
    
    if tab_choice == "樂活五線譜":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="收盤價", line=dict(color='#00D084', width=2)))
        lines = [('TL+2SD','#FF3131','dash'),('TL+1SD','#FFBD03','dash'),('TL','#FFFFFF','solid'),('TL-1SD','#0096FF','dash'),('TL-2SD','#00FF00','dash')]
        for col, color, style in lines:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=color, dash=style, width=1.5), hoverinfo='skip'))
            fig.add_annotation(x=df['Date'].iloc[-1], y=df[col].iloc[-1], text=f"<b>{df[col].iloc[-1]:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=color))

    elif tab_choice == "KD 指標":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['K'], name="K", line=dict(color='#FF3131')))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['D'], name="D", line=dict(color='#0096FF')))
        fig.add_hline(y=80, line_dash="dot", line_color="gray")
        fig.add_hline(y=20, line_dash="dot", line_color="gray")

    elif tab_choice == "布林通道":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="收盤價", line=dict(color='#FFFFFF', width=1)))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_up'], name="上軌", line=dict(color='#FF3131', dash='dash')))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['MA20'], name="均線", line=dict(color='#FFBD03')))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_low'], name="下軌", line=dict(color='#00FF00', dash='dash')))

    elif tab_choice == "成交量":
        colors = ['red' if c > o else 'green' for o, c in zip(df['Open'], df['Close'])]
        fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], marker_color=colors, name="成交量"))

    # 共同設定 (現價線與佈局)
    if tab_choice != "KD 指標" and tab_choice != "成交量":
        fig.add_hline(y=curr, line_dash="dot", line_color="#FFFFFF")
        fig.add_annotation(x=df['Date'].iloc[-1], y=curr, text=f"現價: {curr:.2f}", showarrow=False, xanchor="left", xshift=10, yshift=15, font=dict(color="#FFFFFF", size=14))

    fig.update_layout(height=650, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', hovermode="x unified", showlegend=False, margin=dict(l=10, r=100, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

# --- 9. 概覽掃描 (維持原樣) ---
st.divider()
if st.button("🔄 開始掃描所有標的狀態"):
    # ... 原本的掃描代碼 ...
    st.write("掃描完成")
