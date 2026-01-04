import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (僅新增名稱抓取) ---
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
            # A欄代號, B欄名稱 (若B欄無資料則回傳空字串)
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row[0]}
    except Exception as e:
        st.warning("目前暫時使用預設清單。")
    return default_dict

def save_watchlist_to_google(watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        sheet.clear()
        # 存入 A, B 兩欄
        # --- 新增排序邏輯 ---
        # 將 dict 轉換為 list，並根據第一個元素 (ticker) 進行排序
        sorted_items = sorted(watchlist_dict.items(), key=lambda x: x[0])
        
        # 重新組合資料，加入標題列
        data = [["ticker", "name"]] + [[t, n] for t, n in sorted_items]
        
        sheet.update("A1", data)
        
        # 同步更新 session_state，確保 UI 上的下拉選單也會立即排序
        st.session_state.watchlist_dict = dict(sorted_items)
    except Exception as e:
        st.error(f"儲存並排序失敗: {e}")

# --- 2. 初始化 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")

if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google()

# --- 顏色配置 (維持原樣) ---
lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 3. 介面佈局 (側邊欄) ---
with st.sidebar:
    st.header("📋 追蹤清單")
    
    # 1. 先獲取排序後的代號清單
    sorted_tickers = sorted(st.session_state.watchlist_dict.keys())
    
    # 2. 建立「代號 - 名稱」的顯示格式
    display_options = [
        f"{t} - {st.session_state.watchlist_dict[t]}" for t in sorted_tickers
    ]
    
    # 3. 在下拉選單中顯示 (加上手動輸入選項)
    selected_full_text = st.selectbox(
        "我的收藏", 
        options=["-- 手動輸入 --"] + display_options
    )
    
    st.divider()
    st.header("⚙️ 搜尋設定")
    
    # 4. 處理選取後的代號提取
    if selected_full_text != "-- 手動輸入 --":
        # 提取第一個空格前的內容作為代號
        quick_pick_ticker = selected_full_text.split(" - ")[0]
    else:
        quick_pick_ticker = ""

    ticker_input = st.text_input(
        "股票代號", 
        value=quick_pick_ticker
    ).upper().strip()
    
    # 自動抓取對應的中文名稱 (用於顯示)
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    st.divider()
    st.subheader("📌 線段說明")
    st.markdown(f'<span style="color:#00FFFF; font-size:18px;">●</span> 每日收盤價', unsafe_allow_html=True)
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "━━━━" if line_style == 'solid' else "----"
        st.markdown(f'<span style="color:{hex_color}; font-weight:bold;">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)

# --- 4. 核心演算法 (維持原樣) ---
@st.cache_data(ttl=3600)
def get_vix_index():
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        return float(vix_data['Close'].iloc[-1])
    except:
        return 0.0

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
    except:
        return None

# --- 5. 數據分析與繪圖 (僅改動標題顯示) ---
# 組合標題：2330.TW (台積電)
display_name = f"{ticker_input} ({stock_name})" if stock_name else ticker_input

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title(f"📈 樂活五線譜: {display_name}")

with col_btn:
    if ticker_input not in st.session_state.watchlist_dict:
        # 手動輸入名稱功能
        input_n = st.text_input("輸入顯示名稱", key="add_n")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = input_n
            save_watchlist_to_google(st.session_state.watchlist_dict)
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
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
        last_p2 = df['TL+2SD'].iloc[-1]
        last_p1 = df['TL+1SD'].iloc[-1]
        last_m1 = df['TL-1SD'].iloc[-1]
        last_m2 = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 五級判定 (維持原樣)
        if current_price > last_p2: status_label = "🔴 天價"
        elif current_price > last_p1: status_label = "🟠 偏高"
        elif current_price > last_m1: status_label = "⚪ 合理"
        elif current_price > last_m2: status_label = "🔵 偏低"
        else: status_label = "🟢 特價"

        if vix_val >= 30: vix_status = "🔴 恐慌"
        elif vix_val > 15: vix_status = "🟠 警戒"
        elif round(vix_val) == 15: vix_status = "⚪ 穩定"
        elif vix_val > 0: vix_status = "🔵 樂觀"
        else: vix_status = "🟢 極致樂觀"

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%", delta_color="inverse")
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.2f}" , help="正值代表長期趨勢向上")
        m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status, delta_color="off", help="超過60代表極度恐慌")

        # --- 繪圖邏輯 (維持原樣，保留所有小數點與高度設定) ---
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            line=dict(color='#00FFFF', width=2),
            hovertemplate='收盤價: %{y:.1f}<extra></extra>'
        ))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                line=dict(color=hex_color, dash=line_style, width=1.5),
                hovertemplate=f'{name_tag}: %{{y:.1f}}<extra></extra>'
            ))
            last_val = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1], y=last_val,
                text=f"<b>{last_val:.1f}</b>", # 保留 .1f
                showarrow=False, xanchor="left", xshift=10,
                font=dict(color=hex_color, size=13),
                bgcolor="rgba(0,0,0,0)"
            )
        fig.add_hline(y=current_price, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(
            x=df['Date'].iloc[-1], y=current_price,
            text=f"現價: {current_price:.2f}", # 保留 .2f
            showarrow=False, xanchor="left", xshift=10, yshift=15,
            font=dict(color="#FFFFFF", size=14, family="Arial Black"),
            bgcolor="rgba(0,0,0,0)"
        )
        fig.update_layout(
            height=650, # 保留 650
            plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
            hovermode="x unified", showlegend=False,
            margin=dict(l=10, r=100, t=50, b=10),

            xaxis=dict(
                showspikes=True, # 顯示指引線
                spikemode="across", # 穿過整個圖表
                spikethickness=1,
                spikecolor="white", # 設定為白色
                spikedash="solid"   # 實線 (若要虛線改為 dash)
        )
        )
        st.plotly_chart(fig, use_container_width=True)

# --- 6. 掃描概覽表 (同步顯示代號與名稱) ---
        st.divider()
        st.subheader("📋 全球追蹤標的 - 位階概覽掃描")
        if st.button("🔄 開始掃描所有標的狀態"):
            st.cache_data.clear() 
            summary_data = []
            with st.spinner('掃描中...'):
                # 修改此處：遍歷字典的鍵值對 (t=代號, name=名稱)
                for t, name in st.session_state.watchlist_dict.items():
                    res = get_lohas_data(t, years_input)
                    if res:
                        t_df, _, _ = res
                        p = float(t_df['Close'].iloc[-1])
                        t_tl = t_df['TL'].iloc[-1]
                        t_p1 = t_df['TL+1SD'].iloc[-1]
                        t_p2 = t_df['TL+2SD'].iloc[-1]
                        t_m1 = t_df['TL-1SD'].iloc[-1]
                        t_m2 = t_df['TL-2SD'].iloc[-1]
                        
                        if p > t_p2: pos = "🔴 +2SD (天價)"
                        elif p > t_p1: pos = "🟠 +1SD (偏高)"
                        elif p > t_m1: pos = "⚪ 趨勢線 (合理)"
                        elif p > t_m2: pos = "🔵 -1SD (偏低)"
                        else: pos = "🟢 -2SD (特價)"
                        
                        summary_data.append({
                            "代號": t, 
                            "名稱": name,  # 新增這一欄顯示中文名稱
                            "最新價格": f"{p:.1f}",
                            "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.1f}%", 
                            "位階狀態": pos
                        })
            if summary_data:
                st.table(pd.DataFrame(summary_data))
