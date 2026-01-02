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
        search_ticker = f"{ticker}.TW" if ticker.isdigit() and len(ticker) >= 4 else ticker

        tk = yf.Ticker(search_ticker)
        df = tk.history(start=start_date, end=end_date)
        
        if df.empty: return None
        
        stock_name = tk.info.get('longName', search_ticker)
        
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        
        # 線性回歸計算
        df['x'] = np.arange(len(df))
        slope, intercept, r_value, _, _ = stats.linregress(df['x'], df['Close'])
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
        st.error(f"數據下載失敗: {e}")
        return None

# --- UI 介面 ---
st.title("📈 股市樂活五線譜")

with st.sidebar:
    st.header("搜尋設定")
    ticker_input = st.text_input("輸入股票代碼", value="2330")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    st.divider()
    st.markdown("### 價格標籤說明")
    st.info("圖表右側已加上彩色價格標籤，方便快速查看位階價位。")

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope, r_squared, final_ticker, stock_name = result
        current_price = float(df['Close'].iloc[-1])
        last_date = df['Date'].iloc[-1]
        
        st.subheader(f"{final_ticker} ({stock_name})")

        # KPI 顯示區
        col1, col2, col3 = st.columns(3)
        col1.metric("最新收盤價", f"{current_price:.2f}")
        col2.metric("趨勢中心 (TL)", f"{df['TL'].iloc[-1]:.2f}")
        col3.metric("趨勢強度 (R²)", f"{r_squared:.2f}")

        # --- Plotly 圖表 ---
        fig = go.Figure()

        # 五線譜顏色設定
        line_configs = {
            'TL+2SD': {'name': '+2SD (天價)', 'color': '#FF4B4B'}, # 紅
            'TL+1SD': {'name': '+1SD (偏高)', 'color': '#FFA500'}, # 橘
            'TL':      {'name': '趨勢線 (合理)', 'color': '#FFFFFF'}, # 白
            'TL-1SD': {'name': '-1SD (偏低)', 'color': '#1E90FF'}, # 藍
            'TL-2SD': {'name': '-2SD (特價)', 'color': '#00FF00'}  # 綠
        }
        
        for key, config in line_configs.items():
            last_val = df[key].iloc[-1]
            # 畫線
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[key], 
                name=config['name'],
                line=dict(color=config['color'], width=1.5, dash='dash' if 'SD' in key else 'solid'),
                opacity=0.6,
                showlegend=True
            ))
            # 新增：右側價格標籤 (比照參考圖)
            fig.add_trace(go.Scatter(
                x=[last_date],
                y=[last_val],
                mode='text+markers',
                text=[f"<b> {last_val:.1f} </b>"],
                textposition="middle right",
                textfont=dict(color="white", size=12),
                marker=dict(color=config['color'], size=10, symbol='square'),
                showlegend=False,
                hoverinfo='skip'
            ))

        # 收盤價線 (深墨綠色)
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            name='每日收盤價', 
            line=dict(color='#2D5E3F', width=2.5) 
        ))

        # 白色現價指示水平線
        fig.add_hline(
            y=current_price, 
            line_dash="dot", 
            line_color="white", 
            annotation_text=f"現價: {current_price:.2f}", 
            annotation_position="top right",
            annotation_font=dict(color="white", size=14)
        )

        fig.update_layout(
            height=700, 
            template="plotly_dark", 
            hovermode="x unified",
            paper_bgcolor="#121212",
            plot_bgcolor="#121212",
            margin=dict(r=80), # 留出右側空間放標籤
            xaxis=dict(showgrid=True, gridcolor='#333333'),
            yaxis=dict(showgrid=True, gridcolor='#333333', side="left")
        )

        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.error("無法取得數據，請確認代號。")
