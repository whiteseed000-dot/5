import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os

# --- 1. 自動儲存邏輯 ---
DB_FILE = "watchlist_db.json"

def load_watchlist():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return ["2330.TW", "0050.TW", "AAPL", "NVDA"]

def save_watchlist(watchlist):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(list(watchlist), f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"存檔失敗: {e}")

# --- 2. 數據下載 (強化穩定性) ---
@st.cache_data(ttl=600)
def get_lohas_data(ticker, years):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(years * 365))
        # 修正 2330.TW 讀取失敗的關鍵：multi_level_download=False
        df = yf.download(ticker, start=start_date, end=end_date, progress=False, multi_level_download=False)
        
        if df is None or df.empty:
            return None
        
        # 確保欄位名稱正確
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        df['x'] = np.arange(len(df))
        
        # 線性回歸與五線譜計算
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

# --- 3. 頁面配置與初始化 ---
st.set_page_config(page_title="股市樂活五線譜 Pro", layout="wide")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# --- 4. 側邊欄設計 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    # 使用選單作為「快速捷徑」，選中後會提示用戶輸入
    st.info("💡 點擊下方選單可快速獲得代號")
    quick_pick = st.selectbox("快速切換收藏", options=["-- 手動輸入 --"] + st.session_state.watchlist)
    
    st.divider()
    st.header("⚙️ 搜尋與設定")
    
    # 改回上版本的搜尋模式：獨立的 text_input
    # 如果選單有選，則填入選單內容
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    
    if st.button("🧹 清除快取重新整理"):
        st.cache_data.clear()
        st.rerun()

# --- 5. 主畫面功能按鈕 ---
col_t, col_b = st.columns([4, 1])
with col_t:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_b:
    # 判斷是否在追蹤清單中
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist.append(ticker_input)
            save_watchlist(st.session_state.watchlist)
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
            if len(st.session_state.watchlist) > 1:
                st.session_state.watchlist.remove(ticker_input)
                save_watchlist(st.session_state.watchlist)
                st.rerun()

# --- 6. 渲染圖表與數據 ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        
        # 狀態判定
        if current_price > last_p2sd:
            status, status_color = "⚠️ 過熱 (昂貴區)", "red"
        elif current_price < last_m2sd:
            status, status_color = "💎 特價區 (便宜)", "green"
        else:
            status, status_color = "✅ 穩定範圍", "lightgreen"

        # 顯示指標
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("中心線 (TL)", f"{last_tl:.2f}", f"{((current_price-last_tl)/last_tl)*100:+.2f}%")
        m3.metric("目前狀態", status)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # Plotly 圖表
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='#2D5E3F', width=2)))
        lines = [('TL+2SD', 'red', '昂貴'), ('TL', 'gray', '中心線'), ('TL-2SD', 'green', '便宜')]
        for col, color, label in lines:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], name=label, line=dict(color=color, dash='dash' if 'SD' in col else 'solid')))
        
        fig.update_layout(height=500, template="plotly_white", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        
        # 概覽掃描功能
        st.divider()
        if st.button("🔄 掃描全清單最新位階"):
            summary = []
            for t in st.session_state.watchlist:
                res = get_lohas_data(t, years_input)
                if res:
                    t_df, _, _ = res
                    p = t_df['Close'].iloc[-1]
                    t_tl = t_df['TL'].iloc[-1]
                    summary.append({"代號": t, "價格": f"{p:.2f}", "狀態": "💎 特價" if p < t_df['TL-2SD'].iloc[-1] else ("⚠️ 過熱" if p > t_df['TL+2SD'].iloc[-1] else "✅ 正常")})
            st.table(pd.DataFrame(summary))
    else:
        st.error(f"數據抓取失敗：{ticker_input}。請確認代號正確，或點擊左側『清除快取』再試一次。")
