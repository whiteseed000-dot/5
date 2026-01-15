import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 頁面配置
st.set_page_config(page_title="康波週期分析儀", layout="wide")

st.title("🌊 康波週期 (K-Wave) 動態分析模型")
st.write("根據技術革命週期，我們目前正處於第五波與第六波的交接期。")

# 1. 定義康波週期的關鍵時間點 (參考圖片數據)
waves = [
    {"name": "第一波：蒸汽機", "start": 1782, "peak": 1815, "end": 1845},
    {"name": "第二波：鐵路與鋼鐵", "start": 1845, "peak": 1866, "end": 1892},
    {"name": "第三波：電氣與重工業", "start": 1892, "peak": 1913, "end": 1948},
    {"name": "第四波：電子技術", "start": 1948, "peak": 1966, "end": 1991},
    {"name": "第五波：資訊技術", "start": 1991, "peak": 2009, "end": 2026},
    {"name": "第六波：AI 與 生物科技", "start": 2026, "peak": 2035, "end": 2050},
]

# 2. 生成正弦波數據模擬圖片曲線
def generate_wave_data(waves):
    x_all = []
    y_all = []
    for w in waves:
        x = np.linspace(w['start'], w['end'], 100)
        # 簡單正弦波模擬：從 0 開始，到 peak 為 1，到 end 回到 0 (或負值)
        period = w['end'] - w['start']
        y = np.sin((x - w['start']) / period * np.pi) 
        x_all.extend(x)
        y_all.extend(y)
    return x_all, y_all

x_data, y_data = generate_wave_data(waves)

# 3. 繪製圖表
fig = go.Figure()

# 繪製主波浪線
fig.add_trace(go.Scatter(x=x_data, y=y_data, mode='lines', name='經濟週期', line=dict(color='#FFD700', width=3)))

# 標註目前時間 (2026)
current_year = 2026
fig.add_vline(x=current_year, line_dash="dash", line_color="red", annotation_text="目前位置 (2026)")

# 美化佈局 (仿照圖片黑底風格)
fig.update_layout(
    template="plotly_dark",
    xaxis_title="年份",
    yaxis_showticklabels=False,
    height=500,
    margin=dict(l=20, r=20, t=50, b=20)
)

st.plotly_chart(fig, use_container_width=True)

# 4. 交互式分析面板
st.sidebar.header("週期參數設定")
selected_wave = st.sidebar.selectbox("查看特定週期詳情", [w['name'] for w in waves])

st.subheader(f"🔍 深度分析：{selected_wave}")
col1, col2 = st.columns(2)

with col1:
    st.info("**當前階段：** 蕭條期 (Depression) -> 復甦期 (Improvement)")
    st.write("根據圖片，2026 年是第五波的谷底，也是第六波的起點。")

with col2:
    st.warning("**投資建議：** 關注 AI、新能源、自動化生產。")
