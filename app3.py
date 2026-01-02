import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (維持不變) ---
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
        st.warning("目前暫時使用預設清單。")
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

# --- 顏色配置 ---
lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 3. 介面佈局 (側邊欄) ---
with st.sidebar:
    st.header("📋 追蹤清單")
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + st.session_state.watchlist)
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    st.divider()
    st.subheader("📌 線段說明")
    st.markdown(f'<span style="color:#00D084; font-size:18px;">●</span> 每日收盤價', unsafe_allow_html=True)
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "━━━━" if line_style == 'solid' else "----"
        st.markdown(f'<span style="color:{hex_color}; font-weight:bold;">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)

# --- 4. 核心演算法 ---
@st.cache_data(ttl=3600)
def get_vix_index():
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        return float(vix_data['Close'].iloc[-1])
    except:
        return 0.0

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
        
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        
        std_dev = np.std(df['Close'] - df['TL'])
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope
    except:
        return None

# --- 5. 數據分析與繪圖 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
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

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    vix_val = get_vix_index()
    
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2 = df['TL+2SD'].iloc[-1]
        last_p1 = df['TL+1SD'].iloc[-1]
        last_m1 = df['TL-1SD'].iloc[-1]
        last_m2 = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 五級判定 (個股)
        if current_price > last_p2: status_label = "🔴 天價"
        elif current_price > last_p1: status_label = "🟠 偏高"
        elif current_price > last_m1: status_label = "⚪ 合理"
        elif current_price > last_m2: status_label = "🔵 偏低"
        else: status_label = "🟢 特價"

        # VIX 判定邏輯 (與個股反向：VIX越高越紅)
        if vix_val >= 30: vix_status = "🔴 恐慌"
        elif vix_val > 15: vix_status = "🟠 警戒"
        elif round(vix_val) == 15: vix_status = "⚪ 穩定"
        elif vix_val > 0: vix_status = "🔵 樂觀"
        else: vix_status = "🟢 極致樂觀"

        # --- 顯示 5 個關鍵指標 ---
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.4f}")
        m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status)

        # --- 繪圖邏輯 (維持亮度優化版) ---
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            line=dict(color='#00D084', width=2),
            hovertemplate='收盤價: %{y:.1f}<extra></extra>'
        ))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                line=dict(color=hex_color, dash=line_style, width=1.5),
                hovertemplate=f'{name_tag}: %{{y:.1f}}<extra></extra>'
            ))
            last_val = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1], y=last_val,
                text=f"<b>{last_val:.1f}</b>",
                showarrow=False, xanchor="left", xshift=10,
                font=dict(color=hex_color, size=13),
                bgcolor="rgba(0,0,0,0)"
            )
        fig.add_hline(y=current_price, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(
            x=df['Date'].iloc[-1], y=current_price,
            text=f"現價: {current_price:.2f}",
            showarrow=False, xanchor="left", xshift=10, yshift=15,
            font=dict(color="#FFFFFF", size=14, family="Arial Black"),
            bgcolor="rgba(0,0,0,0)"
        )
        fig.update_layout(
            height=650, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
            hovermode="x unified", showlegend=False,
            margin=dict(l=10, r=100, t=50, b=10),
            yaxis=dict(showgrid=True, gridcolor='#333333', side="left"),
            xaxis=dict(showgrid=True, gridcolor='#333333')
        )
        st.plotly_chart(fig, use_container_width=True)
