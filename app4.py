import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 網站設定 ---
st.set_page_config(page_title="股市樂活五線譜 Pro", layout="wide")

# --- 核心演算法 ---
@st.cache_data(ttl=3600)
def get_lohas_data(ticker, years):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(years * 365))
    
    try:
        # 自動處理台股格式
        if ticker.isdigit() and len(ticker) >= 4:
            search_ticker = f"{ticker}.TW"
        else:
            search_ticker = ticker

        # 下載數據與股票資訊
        tk = yf.Ticker(search_ticker)
        df = tk.history(start=start_date, end=end_date)
        
        if df.empty: return None
        
        # 取得中文/英文名稱
        stock_name = tk.info.get('longName', search_ticker)
        
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        
        # 線性回歸計算
        df['x'] = np.arange(len(df))
        slope, intercept, r_value, p_value, std_err = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        
        # 標準差計算
        residuals = df['Close'] - df['TL']
        std_dev = np.std(residuals)
        
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope, r_value**2, search_ticker, stock_name
        
    except Exception as e:
        st.error(f"錯誤: {e}")
        return None

# --- UI 介面 ---
st.title("📈 股市樂活五線譜")

with st.sidebar:
    st.header("搜尋設定")
    ticker_input = st.text_input("輸入股票代碼", value="2330")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    st.divider()
    st.markdown("### 顏色說明")
    st.write("🔴 +2SD: 天價區")
    st.write("⚪ TL: 趨勢線")
    st.write("🟢 -2SD: 特價區")

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope, r_squared, final_ticker, stock_name = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = float(df['TL'].iloc[-1])
        dist_from_tl = ((current_price - last_tl) / last_tl) * 100

        # 在上方標題顯示：代號 + 中文名稱
        display_title = f"{final_ticker} ({stock_name})"
        st.subheader(display_title)

        # KPI 顯示區
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("最新收盤價", f"{current_price:.2f}")
        with col2:
            st.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_from_tl:+.2f}%")
        with col3:
            st.metric("趨勢強度 (R²)", f"{r_squared:.2f}")

        # --- Plotly 圖表 ---
        fig = go.Figure()

        # 軌道線顏色
        colors = {'+2SD': 'red', '+1SD': 'orange', 'TL': 'white', '-1SD': 'royalblue', '-2SD': 'green'}
        
        for line in ['TL+2SD', 'TL+1SD', 'TL', 'TL-1SD', 'TL-2SD']:
            line_color = colors.get(line.replace('TL', '').replace('+', '+').replace('-', '-') or 'TL')
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[line], 
                name=line.replace('TL', '趨勢線'),
                line=dict(color=line_color, width=1, dash='dash' if 'SD' in line else 'solid'),
                opacity=0.5
            ))

        # 收盤價線 (深綠色)
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            name='收盤價', 
            line=dict(color='#2D5E3F', width=2.5) 
        ))

        # 白色現價指示線
        fig.add_hline(
            y=current_price, 
            line_dash="dot", 
            line_color="white", 
            annotation_text=f"目前現價: {current_price:.2f}", 
            annotation_position="bottom right",
            annotation_font_color="white"
        )

        fig.update_layout(
            height=600, 
            template="plotly_dark", 
            hovermode="x unified",
            paper_bgcolor="#121212",
            plot_bgcolor="#121212"
        )

        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.error("無法取得數據，請檢查代號。")
