import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 連線邏輯 ---
def get_gsheet_client():
    # 從 Streamlit Secrets 讀取憑證
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # 假設您在 Secrets 中設定了名為 "gcp_service_account" 的區塊
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_watchlist_from_google():
    try:
        client = get_gsheet_client()
        # 開啟試算表 (請替換成您的試算表名稱或 URL)
        sheet = client.open("MyWatchlist").sheet1
        # 讀取 A 欄所有資料並去掉標題
        records = sheet.get_all_values()
        if len(records) > 1:
            return [row[0] for row in records[1:] if row[0]]
    except Exception as e:
        st.error(f"Google 讀取失敗: {e}")
    return ["2330.TW", "0050.TW"]

def save_watchlist_to_google(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        # 清空並重新寫入
        sheet.clear()
        data = [["ticker"]] + [[t] for t in watchlist]
        sheet.update("A1", data)
    except Exception as e:
        st.error(f"Google 儲存失敗: {e}")

# --- 2. 初始化 Session State ---
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist_from_google()

# --- (其餘數據計算與圖表邏輯保持不變) ---
# ... (您的 get_lohas_data 函式與 UI 程式碼) ...

# 修改按鈕觸發部分：
with col_btn:
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist.append(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist) # 改成存到 Google
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
            st.session_state.watchlist.remove(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist) # 改成存到 Google
            st.rerun()

# --- 2. 核心演算法 (五線譜計算) ---
@st.cache_data(ttl=3600)
def get_lohas_data(ticker, years):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(years * 365))
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        df['x'] = np.arange(len(df))
        
        # 線性回歸
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        
        # 標準差通道
        std_dev = np.std(df['Close'] - df['TL'])
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        
        return df, std_dev, slope
    except:
        return None

# --- 3. 頁面初始化與側邊欄 ---
st.set_page_config(page_title="股市樂活五線譜 Pro", layout="wide")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

with st.sidebar:
    st.header("📋 追蹤清單")
    # 這裡使用 selectbox 讓使用者快速選取
    selected_ticker = st.selectbox("我的收藏", options=st.session_state.watchlist)
    
    st.divider()
    st.header("⚙️ 參數設定")
    ticker_input = st.text_input("輸入股票代號", value=selected_ticker).upper()
    years_input = st.slider("回測年數 (建議 3.5 年)", 1.0, 10.0, 3.5, 0.5)
    
    st.info("💡 說明：\n- **+2SD**: 昂貴區\n- **TL**: 趨勢中心線\n- **-2SD**: 特價區")

# --- 4. 主畫面控制按鈕 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
    # 加入與移除功能
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

# --- 5. 數據分析與繪圖 ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 狀態判斷
        if current_price > last_p2sd:
            status, color = "⚠️ 過熱 (高於 +2SD)", "red"
        elif current_price > last_tl:
            status, color = "📊 相對偏高", "orange"
        elif current_price < last_m2sd:
            status, color = "💎 特價區 (低於 -2SD)", "green"
        else:
            status, color = "✅ 相對便宜", "lightgreen"

        # 顯示關鍵指標
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # 繪製圖表
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='#2D5E3F', width=2)))
        
        lines = [('TL+2SD', 'red', '昂貴'), ('TL+1SD', 'orange', '+1SD'), 
                 ('TL', 'gray', '中心線'), ('TL-1SD', 'lightgreen', '-1SD'), 
                 ('TL-2SD', 'green', '便宜')]
        
        for col, color, label in lines:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], name=label, 
                                     line=dict(color=color, dash='dash' if 'SD' in col else 'solid')))

        fig.update_layout(height=500, template="plotly_white", hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

        # --- 6. 掃描概覽表 ---
        st.divider()
        st.subheader("📋 全球追蹤標的 - 位階概覽掃描")
        
        if st.button("🔄 開始掃描所有標的狀態"):
            summary_data = []
            with st.spinner('掃描中...'):
                for t in st.session_state.watchlist:
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
            
            if summary_data:
                # 簡單美化表格
                st.table(pd.DataFrame(summary_data))

    else:
        st.error("數據獲取失敗，請確認代號是否正確。")

# 詳細數據展開
with st.expander("查看原始數據"):
    if 'df' in locals():
        st.dataframe(df.tail(10).sort_values('Date', ascending=False))
