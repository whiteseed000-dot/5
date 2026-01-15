import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# --- 1. 頁面設定 ---
st.set_page_config(page_title="康波週期 x 台股分析儀", layout="wide")

st.title("🌊 康波週期與台股加權指數疊加模型")
st.markdown("""
本工具將**康波週期（Kondratiev Wave）**理論與**台股實時數據**結合。
目前我們正處於第五波資訊技術週期的尾端，即將進入第六波 AI 與生技革命。
""")

# --- 2. 數據抓取函式 ---
@st.cache_data
def get_historical_data():
    # 抓取台股加權指數 (^TWII)
    # 起始時間設為 1990 年以涵蓋第五波週期
    df = yf.download("^TWII", start="1990-01-01")
    return df

try:
    twii_df = get_historical_data()
    # 確保索引為 Datetime 格式，避免 Plotly 繪圖錯誤
    twii_df.index = pd.to_datetime(twii_df.index)
except Exception as e:
    st.error(f"數據抓取失敗: {e}")
    twii_df = pd.DataFrame()

# --- 3. 定義康波週期數據 (根據上傳圖片數據) ---
waves = [
    {"name": "第五波：資訊技術", "start": 1991, "peak": 2009, "end": 2026, "color": "#00CCFF"},
    {"name": "第六波：AI 與 生物科技", "start": 2026, "peak": 2035, "end": 2050, "color": "#FF3300"},
]

# --- 4. 建立繪圖 ---
# 使用雙 Y 軸：左軸為台股點位，右軸為週期強度
fig = make_subplots(specs=[[{"secondary_y": True}]])

# A. 繪製台股加權指數 (左軸)
if not twii_df.empty:
    fig.add_trace(
        go.Scatter(
            x=twii_df.index, 
            y=twii_df['Close'], 
            name="台股加權指數", 
            line=dict(color='rgba(255, 255, 255, 0.5)', width=1.5)
        ),
        secondary_y=False,
    )

# B. 繪製康波週期模擬曲線 (右軸)
for w in waves:
    # 產生年份數據
    years = np.linspace(w['start'], w['end'], 100)
    # 將年份轉換為 DateTime 物件，確保與台股數據對齊
    dates = [pd.Timestamp(year=int(y), month=1, day=1) + pd.Timedelta(days=(y % 1) * 365.25) for y in years]
    # 模擬波形 (Sine Wave)
    y_values = np.sin((years - w['start']) / (w['end'] - w['start']) * np.pi)
    
    fig.add_trace(
        go.Scatter(
            x=dates, 
            y=y_values, 
            name=w['name'], 
            line=dict(color=w['color'], width=4, dash='dot')
        ),
        secondary_y=True,
    )

# C. 修正垂直線錯誤：使用 pd.Timestamp 確保類型匹配
transition_date = pd.Timestamp("2026-01-01")
fig.add_vline(
    x=transition_date, 
    line_dash="dash", 
    line_color="yellow",
    annotation_text="2026 週期轉折點",
    annotation_position="top left"
)

# --- 5. 圖表樣式美化 ---
fig.update_layout(
    template="plotly_dark",
    hovermode="x unified",
    height=700,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=50, r=50, t=80, b=50)
)

fig.update_yaxes(title_text="台股指數 (Points)", secondary_y=False, showgrid=False)
fig.update_yaxes(title_text="週期階段 (模擬強度)", secondary_y=True, showgrid=True, gridcolor="rgba(255,255,255,0.1)")

# --- 6. Streamlit 顯示 ---
st.plotly_chart(fig, use_container_width=True)

# 底部數據面板
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("當前年份", "2026")
with col2:
    current_price = twii_df['Close'].iloc[-1] if not twii_df.empty else "N/A"
    st.metric("台股最新收盤", f"{current_price:,.0f}")
with col3:
    st.metric("目前週期階段", "第五波末端 / 第六波起點")

st.info("💡 註：康波週期為長達 50-60 年的經濟理論，本圖表之曲線為理想化模擬，僅供學術研究參考。")
