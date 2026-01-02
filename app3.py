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

# --- 定義顏色與標籤設定 (全域使用) ---
lines_config = [
    ('TL+2SD', '#E53935', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FB8C00', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#1E88E5', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#43A047', '-2SD (特價)', 'dash')
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

    # --- 調整重點：在紅框位置自定義圖例 ---
    st.divider()
    st.subheader("📌 線段說明")
    # 顯示收盤價
    st.markdown(f'<span style="color:#2E7D32;">●</span> 每日收盤價', unsafe_allow_html=True)
    # 循環顯示五線譜
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "───" if line_style == 'solid' else "- - -"
        st.markdown(f'<span style="color:{hex_color};">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)

# --- 4. 核心演算法 ---
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
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 指標顯示
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        
        status_label = "✅ 相對便宜"
        if current_price > last_p2sd: status_label = "⚠️ 過熱 (高於 +2SD)"
        elif current_price > last_tl: status_label = "📊 相對偏高"
        elif current_price < last_m2sd: status_label = "💎 特價區 (低於 -2SD)"
        
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # --- 繪圖邏輯 ---
        fig = go.Figure()
        
        # 每日收盤價
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            line=dict(color='#2E7D32', width=1.5),
            hovertemplate='每日收盤價: %{y:.1f}<extra></extra>'
        ))
        
        # 五線譜線段
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                line=dict(color=hex_color, dash=line_style, width=1),
                hovertemplate=f'{name_tag}: %{{y:.1f}}<extra></extra>'
            ))
            
            # 右側末端文字標籤 (比照照片：無底色)
            last_val = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1], y=last_val,
                text=f"<b>{last_val:.1f}</b>",
                showarrow=False, xanchor="left", xshift=10,
                font=dict(color=hex_color, size=12),
                bgcolor="rgba(0,0,0,0)"
            )

        # 現價虛線
        fig.add_hline(y=current_price, line_dash="dot", line_color="white", line_width=1.5)
        fig.add_annotation(
            x=df['Date'].iloc[-1], y=current_price,
            text=f"現價: {current_price:.2f}",
            showarrow=False, xanchor="left", xshift=10, yshift=15,
            font=dict(color="white", size=13),
            bgcolor="rgba(0,0,0,0)"
        )

        # --- 佈局調整：隱藏原本圖表的 Legend，座標移到左邊 ---
        fig.update_layout(
            height=650, 
            template="plotly_dark",
            hovermode="x unified",
            showlegend=False, # 重點：隱藏圖表內原本的說明
            margin=dict(l=10, r=100, t=50, b=10),
            yaxis=dict(showgrid=True, gridcolor='#262626', side="left"), # 座標移至左側
            xaxis=dict(showgrid=True, gridcolor='#262626')
        )

        st.plotly_chart(fig, use_container_width=True)

        # 下方位階掃描表... (代碼同前)
