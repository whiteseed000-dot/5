import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os
import time

# --- 1. 自動儲存與讀取邏輯 (強化版) ---
DB_FILE = "watchlist_db.json"

def load_watchlist():
    """從檔案讀取追蹤清單，確保編碼正確"""
    default_list = ["2330.TW", "0050.TW", "AAPL", "NVDA", "TSLA"]
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"讀取存檔失敗: {e}")
    return default_list

def save_watchlist(watchlist):
    """將目前的追蹤清單存入檔案"""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(list(watchlist), f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"存檔寫入失敗: {e}")

# --- 2. 核心演算法 (修正 2330 讀取與快取問題) ---
@st.cache_data(ttl=600)  # 縮短快取時間至 10 分鐘，避免錯誤鎖定
def get_lohas_data(ticker, years):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(years * 365))
        
        # 使用 retry 邏輯，並關閉 multi_level_download 解決新版 yfinance 問題
        df = yf.download(ticker, start=start_date, end=end_date, progress=False, multi_level_download=False)
        
        if df is None or df.empty:
            return None
            
        # 處理資料格式
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        
        # 計算回歸線
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        
        # 標準差通道
        std_dev = np.std(df['Close'] - df['TL'])
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

# --- 3. 介面初始化 ---
st.set_page_config(page_title="股市樂活五線譜 Pro", layout="wide")

# 確保 Session State 存在
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# --- 4. 側邊欄：管理清單 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    
    # 選單
    selected_ticker = st.selectbox("我的收藏", options=st.session_state.watchlist)
    
    st.divider()
    st.header("⚙️ 參數設定")
    # 輸入框
    ticker_input = st.text_input("輸入股票代號", value=selected_ticker).upper().strip()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    
    st.info("💡 說明：\n- **+2SD**: 昂貴區 (考慮減碼)\n- **TL**: 趨勢中心\n- **-2SD**: 特價區 (考慮加碼)")
    
    # 手動清理快取按鈕 (若遇到讀取失敗可用)
    if st.button("🧹 清除快取數據"):
        st.cache_data.clear()
        st.rerun()

# --- 5. 主畫面：加入/移除功能 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
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
            else:
                st.warning("請至少保留一個標的")

# --- 6. 數據分析與繪圖 ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 狀態判定與顏色
        if current_price > last_p2sd:
            status, color = "⚠️ 過熱 (高於 +2SD)", "red"
        elif current_price > last_tl:
            status, color = "📊 相對偏高", "orange"
        elif current_price < last_m2sd:
            status, color = "💎 特價區 (低於 -2SD)", "green"
        else:
            status, color = "✅ 相對便宜", "lightgreen"

        # KPI 卡片
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("中心線 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # 繪製 Plotly 圖表
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='#2D5E3F', width=2)))
        
        lines = [('TL+2SD', 'red', '昂貴'), ('TL+1SD', 'orange', '+1SD'), 
                 ('TL', 'gray', '中心線'), ('TL-1SD', 'lightgreen', '-1SD'), 
                 ('TL-2SD', 'green', '便宜')]
        
        for col_name, color, label in lines:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col_name], name=label, 
                                     line=dict(color=color, dash='dash' if 'SD' in col_name else 'solid')))

        fig.update_layout(height=500, template="plotly_white", hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

        # --- 7. 位階概覽掃描表 ---
        st.divider()
        st.subheader("📋 全球追蹤標的 - 位階概覽")
        
        if st.button("🔄 開始掃描所有標的狀態"):
            summary_data = []
            progress_bar = st.progress(0)
            watchlist_len = len(st.session_state.watchlist)
            
            for idx, t in enumerate(st.session_state.watchlist):
                res = get_lohas_data(t, years_input)
                if res:
                    t_df, _, _ = res
                    p = float(t_df['Close'].iloc[-1])
                    t_tl = t_df['TL'].iloc[-1]
                    t_p2 = t_df['TL+2SD'].iloc[-1]
                    t_m2 = t_df['TL-2SD'].iloc[-1]
                    
                    if p > t_p2: pos = "⚠️ 過熱"
                    elif p > t_tl: pos = "📊 偏高"
                    elif p < t_m2: pos = "💎 特價"
                    else: pos = "✅ 便宜"
                    
                    summary_data.append({
                        "代號": t,
                        "價格": f"{p:.2f}",
                        "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.2f}%",
                        "位階狀態": pos
                    })
                progress_bar.progress((idx + 1) / watchlist_len)
            
            if summary_data:
                st.table(pd.DataFrame(summary_data))
            progress_bar.empty()

    else:
        st.error(f"數據獲取失敗: {ticker_input}。可能是網路不穩或代號錯誤，請嘗試點選側邊欄的『清除快取數據』再試一次。")

# 詳細數據展開
with st.expander("查看原始數據"):
    if 'df' in locals():
        st.dataframe(df.tail(10).sort_values('Date', ascending=False))
