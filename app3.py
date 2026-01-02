import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (支援 A欄代號, B欄名稱) ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_watchlist_from_google():
    # 預設對照表
    default_dict = {"2330.TW": "台積電", "0050.TW": "元大台灣50", "AAPL": "蘋果", "NVDA": "輝達"}
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        records = sheet.get_all_values()
        if len(records) > 1:
            # 讀取 A2 (row[0]) 與 B2 (row[1])
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row[0]}
    except Exception as e:
        st.warning("目前無法連接 Google 雲端，使用預設資料。")
    return default_dict

def save_watchlist_to_google(watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        sheet.clear()
        # 寫入標題與資料
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
        st.success("雲端清單已同步更新！")
    except Exception as e:
        st.error(f"儲存失敗: {e}")

# --- 2. 初始化 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")

if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google()

# 顏色配置
lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 3. 側邊欄佈局 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    # 取得現有代號清單
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    
    # 取得名稱 (若不在字典裡則回傳空字串)
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    st.divider()
    st.subheader("📌 線段說明")
    st.markdown(f'<span style="color:#00D084; font-size:18px;">●</span> 每日收盤價', unsafe_allow_html=True)
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "━━━━" if line_style == 'solid' else "----"
        st.markdown(f'<span style="color:{hex_color}; font-weight:bold;">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)

# --- 4. 核心演算法 ---
@st.cache_data(ttl=3600)
def get_vix_index():
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        return float(vix_data['Close'].iloc[-1])
    except: return 0.0

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
        
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        std_dev = np.std(df['Close'] - df['TL'])
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        return df, std_dev, slope
    except: return None

# --- 5. 數據分析與繪圖 ---
# 組合顯示標題：代號 (名稱)
display_title = f"{ticker_input} ({stock_name})" if stock_name else ticker_input

col_title, col_btn = st.columns([4, 1.5])
with col_title:
    st.title(f"📈 樂活五線譜: {display_title}")

with col_btn:
    if ticker_input not in st.session_state.watchlist_dict:
        # 新增邏輯：如果是新股票，彈出輸入框詢問中文名稱
        new_name = st.text_input("輸入此股票名稱", placeholder="例如：台積電")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = new_name
            save_watchlist_to_google(st.session_state.watchlist_dict)
            st.rerun()
    else:
        if st.button("➖ 移除此標的"):
            if len(st.session_state.watchlist_dict) > 1:
                del st.session_state.watchlist_dict[ticker_input]
                save_watchlist_to_google(st.session_state.watchlist_dict)
                st.rerun()

if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    vix_val = get_vix_index()
    
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 五級判定
        if current_price > df['TL+2SD'].iloc[-1]: status_label = "🔴 天價"
        elif current_price > df['TL+1SD'].iloc[-1]: status_label = "🟠 偏高"
        elif current_price > df['TL-1SD'].iloc[-1]: status_label = "⚪ 合理"
        elif current_price > df['TL-2SD'].iloc[-1]: status_label = "🔵 偏低"
        else: status_label = "🟢 特價"

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("中心線 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.4f}")
        m5.metric("VIX 指數", f"{vix_val:.2f}")

        # Plotly 繪圖
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#00D084', width=2), name="收盤價"))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=hex_color, dash=line_style, width=1.5), name=name_tag))
            
        fig.update_layout(height=600, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font_color="white", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

# --- 6. 掃描概覽表 (同步加入名稱) ---
        st.divider()
        st.subheader("📋 全球追蹤標的 - 位階概覽掃描")
        if st.button("🔄 開始掃描所有標的狀態"):
            summary_data = []
            with st.spinner('掃描中...'):
                for t, name in st.session_state.watchlist_dict.items():
                    res = get_lohas_data(t, years_input)
                    if res:
                        t_df, _, _ = res
                        p = float(t_df['Close'].iloc[-1])
                        t_tl = t_df['TL'].iloc[-1]
                        if p > t_df['TL+2SD'].iloc[-1]: pos = "🔴 天價"
                        elif p > t_df['TL+1SD'].iloc[-1]: pos = "🟠 偏高"
                        elif p > t_df['TL-1SD'].iloc[-1]: pos = "⚪ 合理"
                        elif p > t_df['TL-2SD'].iloc[-1]: pos = "🔵 偏低"
                        else: pos = "🟢 特價"
                        
                        summary_data.append({
                            "代號": t, 
                            "名稱": name,
                            "最新價格": f"{p:.1f}",
                            "偏離中心": f"{((p-t_tl)/t_tl)*100:+.1f}%", 
                            "位階狀態": pos
                        })
            if summary_data:
                st.table(pd.DataFrame(summary_data))
