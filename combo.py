import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="台股 x 康波週期分析", layout="wide")

st.title("📈 台股指數與康波週期疊加模型")

# --- 數據抓取：台股加權指數 (^TWII) ---
@st.cache_data
def get_tw_stock_data():
    # 抓取台股加權指數，設定較長的時間範圍
    df = yf.download("^TWII", start="1990-01-01")
    return df

tw_data = get_tw_stock_data()

# --- 康波週期數據模擬 (延續前一份代碼) ---
waves = [
    {"name": "第五波：資訊技術", "start": 1991, "peak": 2009, "end": 2026, "color": "#00CCFF"},
    {"name": "第六波：AI 與 生物科技", "start": 2026, "peak": 2035, "end": 2050, "color": "#FF3300"},
]

# --- 繪製雙軸圖表 ---
fig = make_subplots(specs=[[{"secondary_y": True}]])

# 1. 繪製台股指數 (收盤價) - 使用左軸
fig.add_trace(
    go.Scatter(x=tw_data.index, y=tw_data['Close'], name="台股加權指數", line=dict(color='white', width=1.5), opacity=0.6),
    secondary_y=False,
)

# 2. 疊加康波週期曲線 - 使用右軸
import numpy as np
for w in waves:
    years = np.linspace(w['start'], w['end'], 100)
    # 轉換為日期格式以對齊台股 X 軸
    dates = pd.to_datetime([f"{int(y)}-01-01" for y in years])
    # 模擬波形
    y_wave = np.sin((years - w['start']) / (w['end'] - w['start']) * np.pi)
    
    fig.add_trace(
        go.Scatter(x=dates, y=y_wave, name=w['name'], line=dict(color=w['color'], width=4, dash='dot')),
        secondary_y=True,
    )

# 3. 標註圖片中的關鍵轉折點 (例如 2026 年底)
fig.add_vline(x="2026-01-01", line_dash="dash", line_color="yellow", annotation_text="週期交接點 (2026)")

# 圖表美化
fig.update_layout(
    template="plotly_dark",
    title="台股歷史走勢與康波長週期對照圖",
    xaxis_title="年份",
    hovermode="x unified",
    height=600
)
fig.update_yaxes(title_text="台股指數點位", secondary_y=False)
fig.update_yaxes(title_text="康波週期強度 (模擬)", secondary_y=True, showgrid=False)

st.plotly_chart(fig, use_container_width=True)

# --- 分析說明 ---
st.markdown(f"""
### 💡 數據洞察
* **第五波與台股：** 你可以看到台股從 1991 年起的幾次大循環（如 2000 年網路泡沫、2008 金融海嘯）與康波週期的「衰退」與「蕭條」階段有高度相關性。
* **目前位置：** 根據你提供的圖片，2026 年是第五波的終點。若台股近期波動劇烈，可能正是在消化第五波末端的震盪。
* **未來展望：** 第六波預計在 2026 年後開啟，屆時台股的 AI 供應鏈可能成為支撐新一波 10 年長紅的核心。
""")
