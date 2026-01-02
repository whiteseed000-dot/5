import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 核心雲端邏輯 (支援多使用者分頁) ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def get_user_credentials():
    """從 Google Sheet 的 'users' 分頁讀取帳密"""
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet("users")
        records = sheet.get_all_records()
        return {row['username']: str(row['password']) for row in records}
    except:
        return {"admin": "1234"} # 備援帳號

def load_watchlist_from_google(username):
    default_dict = {"2330.TW": "台積電", "0050.TW": "元大台灣50"}
    try:
        client = get_gsheet_client()
        spreadsheet = client.open("MyWatchlist")
        try:
            sheet = spreadsheet.worksheet(username)
        except gspread.exceptions.WorksheetNotFound:
            # 首次登入者自動建立個人分頁
            sheet = spreadsheet.add_worksheet(title=username, rows="100", cols="20")
            sheet.update("A1", [["ticker", "name"]])
            return default_dict
            
        records = sheet.get_all_values()
        if len(records) > 1:
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row[0]}
    except:
        st.warning(f"無法讀取 {username} 的清單，使用預設值。")
    return default_dict

def save_watchlist_to_google(username, watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet(username)
        sheet.clear()
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
        st.success("個人清單已儲存至雲端！")
    except Exception as e:
        st.error(f"儲存失敗: {e}")

# --- 2. 登入系統 ---
def login_screen():
    if "authenticated" not in st.session_state:
        st.set_page_config(page_title="登入 - 股市五線譜 Pro", page_icon="🔐")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔐 樂活五線譜 Pro")
            st.subheader("請登入以使用個人清單")
            user = st.text_input("帳號")
            pw = st.text_input("密碼", type="password")
            if st.button("確認登入", use_container_width=True):
                creds = get_user_credentials()
                if user in creds and creds[user] == pw:
                    st.session_state.authenticated = True
                    st.session_state.username = user
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤，或 'users' 分頁尚未設定。")
        return False
    return True

if not login_screen():
    st.stop()

# --- 3. 初始化 (登入後) ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username

if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

# 顏色與線段設定 (維持原樣)
lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 4. 介面佈局 (側邊欄) ---
with st.sidebar:
    st.title(f"👤 {username}")
    if st.button("登出帳號"):
        del st.session_state.authenticated
        st.rerun()
    
    st.divider()
    st.header("📋 我的追蹤")
    tickers = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("切換收藏標的", options=["-- 手動輸入 --"] + tickers)
    
    st.divider()
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    # 說明文字 (維持原樣)
    st.divider()
    st.subheader("📌 線段說明")
    st.markdown('<span style="color:#00D084;">●</span> 每日收盤價', unsafe_allow_html=True)
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "━━━━" if line_style == 'solid' else "----"
        st.markdown(f'<span style="color:{hex_color}; font-weight:bold;">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)

# --- 5. 核心演算法 (維持原樣) ---
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
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Close']].reset_index()
        df.columns = ['Date', 'Close']
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        std_dev = np.std(df['Close'] - df['TL'])
        for i, (sd, col) in enumerate([(2,'TL+2SD'), (1,'TL+1SD'), (-1,'TL-1SD'), (-2,'TL-2SD')]):
            df[col] = df['TL'] + (sd * std_dev)
        return df, std_dev, slope
    except: return None

# --- 6. 數據分析與繪圖 (顯示 A2+B2 標題) ---
display_name = f"{ticker_input} ({stock_name})" if stock_name else ticker_input

col_title, col_btn = st.columns([4, 1.5])
with col_title:
    st.title(f"📈 {display_name}")

with col_btn:
    if ticker_input not in st.session_state.watchlist_dict:
        new_n = st.text_input("輸入顯示名稱", key="add_name_field")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = new_n
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
            st.rerun()
    else:
        if st.button("➖ 移除此標的"):
            del st.session_state.watchlist_dict[ticker_input]
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
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
        m2.metric("中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.4f}")
        m5.metric("VIX 指數", f"{vix_val:.2f}")

        # Plotly 繪圖 (維持所有格式)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#00D084', width=2), hovertemplate='收盤價: %{y:.1f}<extra></extra>'))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=hex_color, dash=line_style, width=1.5), hovertemplate=f'{name_tag}: %{{y:.1f}}<extra></extra>'))
            last_val = df[col].iloc[-1]
            fig.add_annotation(x=df['Date'].iloc[-1], y=last_val, text=f"<b>{last_val:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=hex_color, size=13))
        
        fig.add_hline(y=current_price, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(x=df['Date'].iloc[-1], y=current_price, text=f"現價: {current_price:.2f}", showarrow=False, xanchor="left", xshift=10, yshift=15, font=dict(color="#FFFFFF", size=14, family="Arial Black"))
        
        fig.update_layout(height=650, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', hovermode="x unified", showlegend=False, margin=dict(l=10, r=100, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- 7. 掃描概覽表 (顯示中文名稱) ---
        st.divider()
        st.subheader(f"📋 {username} 的追蹤標的一覽")
        if st.button("🔄 開始掃描所有標的狀態"):
            summary_data = []
            with st.spinner('同步雲端資料中...'):
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
                        summary_data.append({"代號": t, "名稱": name, "最新價格": f"{p:.1f}", "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.1f}%", "位階狀態": pos})
            if summary_data:
                st.table(pd.DataFrame(summary_data))
