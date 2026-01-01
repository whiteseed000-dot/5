import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 網站設定 ---
st.set_page_config(page_title="股市樂活五線譜", layout="wide")

# --- 1. 初始化追蹤清單 (Session State) ---
if 'watchlist' not in st.session_state:
    # 預設一些初始股票
    st.session_state.watchlist = ["2330.TW", "0050.TW", "AAPL", "NVDA"]

# --- 核心演算法 ---
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

# --- 2. 側邊欄：追蹤清單功能 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    
    # 讓使用者從清單中點選
    # index=0 表示預設選中第一個
    selected_ticker = st.selectbox(
        "快速切換股票", 
        options=st.session_state.watchlist,
        index=0
    )
    
    st.divider()
    
    st.header("⚙️ 參數設定")
    # 輸入框的預設值會跟隨選取的清單內容
    ticker_input = st.text_input("手動輸入代號", value=selected_ticker).upper()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

# --- 3. 主畫面：加入/移除按鈕 ---
col_head, col_btn = st.columns([4, 1])
with col_head:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
    # 判斷是否已在清單內
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入清單"):
            st.session_state.watchlist.append(ticker_input)
            st.rerun()
    else:
        if st.button("➖ 移除清單"):
            st.session_state.watchlist.remove(ticker_input)
            st.rerun()

# --- 數據抓取與繪圖 (同原邏輯) ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    if result:
        df, std_dev, slope = result
        current_price = df['Close'].iloc[-1]
        
        # 指標顯示
        last_tl = df['TL'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100
        
        m1, m2, m3 = st.columns(3)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("中心線 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("斜率", f"{slope:.4f}")

        # Plotly 圖表
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='#2D5E3F', width=2)))
        for sd, color, name in zip(['TL+2SD', 'TL+1SD', 'TL', 'TL-1SD', 'TL-2SD'], 
                                   ['red', 'orange', 'gray', 'lightgreen', 'green'],
                                   ['+2SD 昂貴', '+1SD', 'TL 中心線', '-1SD', '-2SD 便宜']):
            fig.add_trace(go.Scatter(x=df['Date'], y=df[sd], name=name, line=dict(color=color, dash='dash' if 'SD' in sd else 'solid')))
        
        fig.update_layout(height=600, template="plotly_white", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("找不到該股票數據，請檢查代號（例如台股需加 .TW）。")
