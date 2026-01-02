import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 核心雲端邏輯 (含自動建表功能) ---
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
            sheet.update("A1", [["ticker", "name"], ["2330.TW", "台積電"]])
            return default_dict
        
        sheet = spreadsheet.worksheet(username)
        records = sheet.get_all_values()
        if len(records) > 1:
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row and row[0]}
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

# --- 2. 登入系統 (含快取清理) ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入 - 股市五線譜", page_icon="🔐")
    st.title("🔐 樂活五線譜 Pro")
    with st.form("login"):
        user = st.text_input("帳號")
        pw = st.text_input("密碼", type="password")
        if st.form_submit_button("登入"):
            creds = get_user_credentials()
            if user in creds and str(creds[user]) == pw:
                st.cache_data.clear() # 登入立即清理舊快取
                st.session_state.authenticated = True
                st.session_state.username = user
                if 'watchlist_dict' in st.session_state: del st.session_state.watchlist_dict
                st.rerun()
            else: st.error("帳號或密碼錯誤")
    st.stop()

# --- 3. 初始化設定 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username
if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 4. 技術指標運算 (RSI/MACD/MA/BIAS) ---
def get_advanced_analysis(df):
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    # MA/BIAS
    df['MA60'] = df['Close'].rolling(60).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['BIAS'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    curr, prev = df.iloc[-1], df.iloc[-2]
    sigs = []
    if curr['RSI'] < 30: sigs.append("RSI低檔")
    elif curr['RSI'] > 70: sigs.append("RSI高檔")
    if prev['MACD'] < prev['Signal'] and curr['MACD'] > curr['Signal']: sigs.append("MACD金叉")
    elif prev['MACD'] > prev['Signal'] and curr['MACD'] < curr['Signal']: sigs.append("MACD死叉")
    sigs.append("季線上" if curr['Close'] > curr['MA60'] else "季線下")
    if curr['BIAS'] < -10: sigs.append("乖離過大")
    return sigs

# --- 5. 側邊欄 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    st.divider()
    st.header("⚙️ 搜尋設定")
    ticker_input = st.text_input("股票代號", value=quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW").upper().strip()
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    if st.button("🚪 登出帳號"):
        st.cache_data.clear()
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# --- 6. 核心數據抓取 ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker, years):
    try:
        df = yf.download(ticker, start=datetime.now()-timedelta(days=int(years*365)), end=datetime.now(), progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        std = np.std(df['Close'] - df['TL'])
        for i, mult in enumerate([2, 1, -1, -2]): df[lines_config[i if i<2 else i+1][0]] = df['TL'] + mult*std
        # 額外計算 KD
        low_9 = df['Low'].rolling(9).min(); high_9 = df['High'].rolling(9).max()
        df['K'] = (100 * (df['Close'] - low_9) / (high_9 - low_9)).ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df, slope
    except: return None

vix_val = yf.download("^VIX", period="1d", progress=False)['Close'].iloc[-1]

# --- 7. UI 渲染 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown(f'# <img src="https://cdn-icons-png.flaticon.com/512/421/421644.png" width="30"> 樂活五線譜: {ticker_input} ({stock_name})', unsafe_allow_html=True)

with col_btn:
    if ticker_input in st.session_state.watchlist_dict:
        if st.button("➖ 移除追蹤"):
            del st.session_state.watchlist_dict[ticker_input]; save_watchlist_to_google(username, st.session_state.watchlist_dict); st.rerun()
    else:
        new_name = st.text_input("股票名稱")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = new_name; save_watchlist_to_google(username, st.session_state.watchlist_dict); st.rerun()

result = get_stock_data(ticker_input, years_input)
if result:
    df, slope = result
    curr = df['Close'].iloc[-1]; tl_last = df['TL'].iloc[-1]
    
    # 狀態判定
    if curr > df['TL+2SD'].iloc[-1]: status_label = "🔴 天價"
    elif curr > df['TL+1SD'].iloc[-1]: status_label = "🟠 偏高"
    elif curr > df['TL-1SD'].iloc[-1]: status_label = "⚪ 合理"
    elif curr > df['TL-2SD'].iloc[-1]: status_label = "🔵 偏低"
    else: status_label = "🟢 特價"

vix_val = get_vix_index()

# 修正判斷邏輯，使用 float 確保穩定
if vix_val >= 30:
    vix_s = "🔴 恐慌"
elif vix_val > 15:
    vix_s = "🟠 警戒"
elif 14.5 <= vix_val <= 15.5: # 用範圍取代精確的 round(vix_val) == 15 避免浮點數誤差
    vix_s = "⚪ 穩定"
elif vix_val > 0:
    vix_s = "🔵 樂觀"
else:
    vix_s = "🟢 極致樂觀"
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("最新股價", f"{curr:.2f}")
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{((curr-tl_last)/tl_last)*100:+.2f}%")
    m3.metric("目前狀態", status_label)
    m4.metric("趨勢斜率", f"{slope:.5f}")
    m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_s)

    # --- 紅框評估區 ---
    st.write("")
    analysis_sigs = get_advanced_analysis(df)
    bg = "rgba(0, 208, 132, 0.1)" if "金叉" in str(analysis_sigs) else "rgba(255, 255, 255, 0.05)"
    st.markdown(f'<div style="background-color:{bg};padding:12px;border-radius:10px;border-left:5px solid #00D084;margin-bottom:10px;"><span style="color:#888;font-size:0.85em;">🔍 多指標綜合評估 (RSI/MACD/MA/BIAS)：</span><br><span style="color:white;font-size:1.1em;font-weight:bold;">{" | ".join(analysis_sigs)}</span></div>', unsafe_allow_html=True)

    view_mode = st.radio("View", ["樂活五線譜", "KD指標", "布林通道", "成交量"], horizontal=True, label_visibility="collapsed")
    
    # --- 圖表 ---
    fig = go.Figure()
    if view_mode == "樂活五線譜":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="收盤價", line=dict(color='#00D084', width=2), hovertemplate='%{y:.1f}'))
        for col, color, name, style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], name=name, line=dict(color=color, dash=style, width=1.2), hovertemplate='%{y:.1f}'))
            fig.add_annotation(x=df['Date'].iloc[-1], y=df[col].iloc[-1], text=f"<b>{df[col].iloc[-1]:.1f}</b>", showarrow=False, xanchor="left", xshift=8, font=dict(color=color, size=12))
    elif view_mode == "KD指標":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['K'], name="K", line=dict(color='#FF3131'), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['D'], name="D", line=dict(color='#0096FF'), hovertemplate='%{y:.1f}'))
    
    if view_mode not in ["成交量", "KD指標"]:
        fig.add_hline(y=curr, line_dash="dot", line_color="white")
        fig.add_annotation(x=df['Date'].iloc[-1], y=curr, text=f"現價: {curr:.2f}", showarrow=False, xanchor="left", xshift=8, yshift=12, font=dict(color="white", size=14))

    fig.update_layout(height=600, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', hovermode="x unified", showlegend=False, margin=dict(l=10, r=80, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

# --- 8. 全域掃描 ---
st.divider()
if st.button("🔄 執行清單全自動雷達掃描"):
    sum_data = []
    for t, n in st.session_state.watchlist_dict.items():
        d = get_stock_data(t, years_input)
        if d:
            df_s, _ = d; p = df_s['Close'].iloc[-1]; tl = df_s['TL'].iloc[-1]
            pos = "🔴 天價" if p > df_s['TL+2SD'].iloc[-1] else "🟢 特價" if p < df_s['TL-2SD'].iloc[-1] else "⚪ 合理"
            sigs = get_advanced_analysis(df_s)
            sum_data.append({"代號": t, "名稱": n, "價格": p, "位階": pos, "技術面": " | ".join(sigs)})
    st.table(pd.DataFrame(sum_data))
