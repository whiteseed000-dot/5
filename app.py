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
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty: return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        
        # 線性回歸
        df['x'] = np.arange(len(df))
        slope, intercept, r_value, p_value, std_err = stats.linregress(df['x'], df['Close'])
        
        df['TL'] = slope * df['x'] + intercept
        
        # 標準差
        residuals = df['Close'] - df['TL']
        std_dev = np.std(residuals)
        
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope, r_value**2
        
    except Exception as e:
        st.error(f"錯誤: {e}")
        return None

# --- UI 介面 ---
st.title("📈 股市樂活五線譜")

with st.sidebar:
    st.header("參數設定")
    ticker_input = st.text_input("股票代號", value="2330.TW")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    st.divider()
    st.write("🔴 +2SD: 天價區")
    st.write("🟡 +1SD: 偏高區")
    st.write("⚪ TL: 趨勢線(回歸線)")
    st.write("🔵 -1SD: 偏低區")
    st.write("🟢 -2SD: 特價區")

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope, r_squared = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = float(df['TL'].iloc[-1])
        
        # 計算偏離度
        dist_from_tl = ((current_price - last_tl) / last_tl) * 100

        # 顯示頂部資訊
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("最新收盤價", f"{current_price:.2f}")
        with col2:
            st.metric("趨勢線位階 (TL)", f"{last_tl:.2f}", f"{dist_from_tl:+.2f}%")
        with col3:
            st.metric("線性相關係數 (R²)", f"{r_squared:.2f}", help="越接近 1 代表趨勢越明顯")

        # --- Plotly 圖表 ---
        fig = go.Figure()

        # 繪製五線
        colors = {'+2SD': 'red', '+1SD': 'orange', 'TL': 'gray', '-1SD': 'royalblue', '-2SD': 'green'}
        
        for line in ['TL+2SD', 'TL+1SD', 'TL', 'TL-1SD', 'TL-2SD']:
            display_name = line.replace('TL', '趨勢線')
            color = colors.get(line.replace('TL', '').replace('+', '+').replace('-', '-') or 'TL')
            fig.add_trace(go.Scatter(x=df['Date'], y=df[line], name=display_name, 
                                     line=dict(color=color, width=1, dash='dash' if 'SD' in line else 'solid')))

        # 繪製股價
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='black', width=2)))

        # 新增：目前股價的橫向指示線
        fig.add_hline(y=current_price, line_dash="dot", line_color="black", 
                      annotation_text=f"目前現價: {current_price:.2f}", 
                      annotation_position="bottom right")

        fig.update_layout(height=600, template="plotly_white", hovermode="x unified",
                          xaxis_title="日期", yaxis_title="價格")

        st.plotly_chart(fig, use_container_width=True)
        
        # 額外分析
        st.subheader("📊 樂活投資建議")
        if current_price < df['TL-2SD'].iloc[-1]:
            st.success(f"🔥 **特價標籤**：目前價格低於 -2SD，處於極端低估區，適合分批布局。")
        elif current_price > df['TL+2SD'].iloc[-1]:
            st.error(f"🚫 **過熱標籤**：目前價格高於 +2SD，處於極端高估區，追高風險大。")
        else:
            st.info(f"ℹ️ **常態波動**：目前股價在正常通道內運行。")

    else:
        st.error("無法取得數據，請檢查代號是否有誤。")

