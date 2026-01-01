import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 網站設定 ---
st.set_page_config(page_title="股市樂活五線譜", layout="wide")

# --- 核心演算法 (有快取功能，避免重複下載) ---
@st.cache_data(ttl=3600)  # 數據快取 1 小時
def get_lohas_data(ticker, years):
    # 1. 計算日期範圍
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(years * 365))
    
    # 2. 下載數據
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty:
            return None
            
        # 處理 MultiIndex (Yahoo Finance 新版格式問題)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        
        # 3. 線性回歸計算
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        
        df['TL'] = slope * df['x'] + intercept
        
        # 4. 標準差計算
        residuals = df['Close'] - df['TL']
        std_dev = np.std(residuals)
        
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope
        
    except Exception as e:
        st.error(f"數據下載失敗: {e}")
        return None

# --- 介面設計 ---
st.title("📈 股市樂活五線譜 (Lohas Channel)")
st.markdown("輸入股票代號，自動計算趨勢線與標準差通道，判斷股價位階。")

# 側邊欄：輸入區
with st.sidebar:
    st.header("參數設定")
    ticker_input = st.text_input("股票代號", value="2330.TW", help="台股請加 .TW (如 0050.TW)，美股直接輸入代號 (如 AAPL)")
    years_input = st.slider("回測年數 (趨勢長度)", min_value=1.0, max_value=10.0, value=3.5, step=0.5)
    
    st.info("💡 說明：\n- **+2SD (紅線)**: 樂觀/昂貴\n- **TL (灰線)**: 趨勢中心\n- **-2SD (綠線)**: 悲觀/便宜")

# 主程式邏輯
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope = result
        current_price = df['Close'].iloc[-1]
        current_date = df['Date'].iloc[-1].strftime('%Y-%m-%d')
        
        # 判斷目前位階
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        dist_from_tl = ((current_price - last_tl) / last_tl) * 100
        # 顯示關鍵指標 (KPI Card)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("最新股價", f"{current_price:.2f}", f"{current_date}")
        col2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_from_tl:+.2f}%")
        
        # 狀態判斷與顏色
        if current_price > last_p2sd:
            status = "⚠️ 過熱 (高於 +2SD)"
            status_color = "red"
        elif current_price > last_tl:
            status = "📊 相對偏高"
            status_color = "orange"
        elif current_price < last_m2sd:
            status = "💎 特價區 (低於 -2SD)"
            status_color = "green"
        else:
            status = "✅ 相對便宜"
            status_color = "lightgreen"
            
        col3.metric("目前狀態", status)
        col4.metric("趨勢斜率", f"{slope:.4f}", help="正值代表長期趨勢向上")

        # --- 繪製互動式圖表 (Plotly) ---
        fig = go.Figure()

        # 1. 畫股價
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], mode='lines', name='收盤價', line=dict(color='#2D5E3F', width=2)))

        # 2. 畫五線譜
        # +2SD
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL+2SD'], mode='lines', name='+2 SD (昂貴)', line=dict(color='red', width=1, dash='dash')))
        # +1SD
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL+1SD'], mode='lines', name='+1 SD', line=dict(color='orange', width=1, dash='dash')))
        # TL (趨勢線)
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL'], mode='lines', name='趨勢中心線', line=dict(color='gray', width=2)))
        # -1SD
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL-1SD'], mode='lines', name='-1 SD', line=dict(color='lightgreen', width=1, dash='dash')))
        # -2SD
        fig.add_trace(go.Scatter(x=df['Date'], y=df['TL-2SD'], mode='lines', name='-2 SD (便宜)', line=dict(color='green', width=1, dash='dash')))

        
        # 新增：目前股價的橫向指示線
        fig.add_hline(y=current_price, line_dash="dot", line_color="cyan", 
                      annotation_text=f"目前現價: {current_price:.2f}", 
                      annotation_position="bottom right")

        fig.update_layout(height=600, template="plotly_white", hovermode="x unified",
                          xaxis_title="日期", yaxis_title="價格")

        st.plotly_chart(fig, use_container_width=True)
        
        # 設定圖表樣式
        fig.update_layout(
            title=f"{ticker_input} 樂活五線譜 ({years_input}年)",
            xaxis_title="日期",
            yaxis_title="價格",
            hovermode="x unified", # 滑鼠移動時顯示所有數值
            height=600,
            template="plotly_white"
        )

        st.plotly_chart(fig, use_container_width=True)

        # 顯示最近 5 天數據表格
        with st.expander("查看詳細數據 (最近 5 天)"):
            st.dataframe(df.tail(5).sort_values('Date', ascending=False))

    else:
        st.warning("找不到股票數據，請確認代號是否正確 (例如台股需加 .TW)。")





