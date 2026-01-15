import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# --- 1. 頁面配置 ---
st.set_page_config(page_title="康波週期分析", layout="wide")
st.title("📈 康波週期 x 台股加權指數")

# --- 2. 數據抓取 ---
@st.cache_data
def get_data():
    # 抓取台股數據
    df = yf.download("^TWII", start="1990-01-01")
    # 重要修正：移除所有時區資訊，轉換索引為單純的日期物件
    df.index = pd.to_datetime(df.index).date
    return df

try:
    tw_df = get_data()
except Exception as e:
    st.error(f"數據抓取出錯: {e}")
    tw_df = pd.DataFrame()

# --- 3. 康波週期波形計算 ---
waves = [
    {"name": "第五波：資訊技術", "start": 1991, "peak": 2009, "end": 2026, "color": "#00CCFF"},
    {"name": "第六波：AI與生技", "start": 2026, "peak": 2035, "end": 2050, "color": "#FF3300"},
]

# --- 4. 繪圖 ---
fig = make_subplots(specs=[[{"secondary_y": True}]])

# A. 繪製台股走勢 (左軸)
if not tw_df.empty:
    fig.add_trace(
        go.Scatter(
            x=tw_df.index, 
            y=tw_df['Close'], 
            name="台股指數", 
            line=dict(color='white', width=1.5),
            opacity=0.7
        ),
        secondary_y=False
    )

# B. 繪製週期曲線 (右軸)
for w in waves:
    # 產生年份數值
    years = np.linspace(w['start'], w['end'], 100)
    # 關鍵修正：將年份精確轉換為 date 物件，確保與台股 X 軸完全對齊
    dates = [datetime(int(y), 1, 1).date() for y in years]
    # 波形模擬
    y_wave = np.sin((years - w['start']) / (w['end'] - w['start']) * np.pi)
    
    fig.add_trace(
        go.Scatter(
            x=dates, 
            y=y_wave, 
            name=w['name'], 
            line=dict(color=w['color'], width=4, dash='dot')
        ),
        secondary_y=True
    )

# C. 修正垂直線：使用字串直接傳遞給 X 軸，避開 Timestamp 加法錯誤
fig.add_shape(
    type="line",
    x0="2026-01-01", x1="2026-01-01",
    y0=0, y1=1,
    xref="x", yref="paper",
    line=dict(color="Yellow", width=2, dash="dash")
)

# 新增垂直線的文字標註 (避開 add_vline)
fig.add_annotation(
    x="2026-01-01",
    y=1,
    yref="paper",
    text="2026 週期轉折點",
    showarrow=False,
    font=dict(color="Yellow")
)

# --- 5. 樣式調整 ---
fig.update_layout(
    template="plotly_dark",
    height=650,
    hovermode="x unified",
    xaxis=dict(type='date'), # 強制指定 X 軸為日期類型
)

fig.update_yaxes(title_text="台股點位", secondary_y=False)
fig.update_yaxes(title_text="週期強度", secondary_y=True, showgrid=False)

st.plotly_chart(fig, use_container_width=True)
