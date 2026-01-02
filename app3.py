import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 核心邏輯 (多帳號支援) ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def get_user_credentials():
    """從雲端 'users' 分頁讀取帳密"""
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet("users")
        records = sheet.get_all_records()
        return {str(row['username']): str(row['password']) for row in records}
    except:
        return {"admin": "1234"}

def load_watchlist_from_google(username):
    default_dict = {"2330.TW": "台積電", "0050.TW": "元大台灣50"}
    try:
        client = get_gsheet_client()
        spreadsheet = client.open("MyWatchlist")
        try:
            sheet = spreadsheet.worksheet(username)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=username, rows="100", cols="20")
            sheet.update("A1", [["ticker", "name"]])
            return default_dict
        records = sheet.get_all_values()
        if len(records) > 1:
            return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row[0]}
    except:
        pass
    return default_dict

def save_watchlist_to_google(username, watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet(username)
        sheet.clear()
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
    except Exception as e:
        st.error(f"同步失敗: {e}")

# --- 2. 登入系統邏輯 ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入 - 股市五線譜", page_icon="🔐")
    st.title("🔐 股市五線譜 Pro")
    with st.form("login_form"):
        user = st.text_input("帳號")
        pw = st.text_input("密碼", type="password")
        if st.form_submit_button("登入"):
            creds = get_user_credentials()
            if user in creds and creds[user] == pw:
                st.session_state.authenticated = True
                st.session_state.username = user
                st.rerun()
            else:
                st.error("帳號或密碼錯誤")
    st.stop()

# --- 3. 初始化設定 (維持原樣) ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username

if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 4. 側邊欄 (維持原樣) ---
with st.sidebar:
    st.header("📋 追蹤清單")
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    
    # 從字典獲取名稱
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    st.divider()
    st.subheader("📌 線段說明")
    st.markdown(f'<span style="color:#00D084;">●</span> 每日收盤價', unsafe_allow_html=True)
    for col, hex_color, name_tag, line_style in lines_config:
        line_symbol = "━━━━" if line_style == 'solid' else "----"
        st.markdown(f'<span style="color:{hex_color}; font-weight:bold;">{line_symbol}</span> {name_tag}', unsafe_allow_html=True)
    
    if st.button("🚪 登出帳號"):
        del st.session_state.authenticated
        st.rerun()

# --- 5. 核心運算 ---
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
        df['TL+2SD'] = df['TL'] + (2 * std_dev)
        df['TL+1SD'] = df['TL'] + (1 * std_dev)
        df['TL-1SD'] = df['TL'] - (1 * std_dev)
        df['TL-2SD'] = df['TL'] - (2 * std_dev)
        return df, std_dev, slope
    except: return None

# --- 6. 標題與按鈕區 (嚴格對齊圖片) ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    # 標題格式校正：📈 樂活五線譜: 代號 (中文名稱)
    st.markdown(f'# <img src="https://cdn-icons-png.flaticon.com/512/421/421644.png" width="30"> 樂活五線譜: {ticker_input} ({stock_name if stock_name else ""})', unsafe_allow_html=True)

with col_btn:
    if ticker_input in st.session_state.watchlist_dict:
        if st.button("➖ 移除追蹤"):
            del st.session_state.watchlist_dict[ticker_input]
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
            st.rerun()
    else:
        new_n = st.text_input("請輸入股票中文名稱", key="add_stock_name")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = new_n
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
            st.rerun()

# --- 7. 主要內容顯示 ---
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

                
        if vix_val >= 30: vix_status = "🔴 恐慌"
        elif vix_val > 15: vix_status = "🟠 警戒"
        elif round(vix_val) == 15: vix_status = "⚪ 穩定"
        elif vix_val > 0: vix_status = "🔵 樂觀"
        else: vix_status = "🟢 極致樂觀"
            
        # 頂部 5 指標欄位 (維持圖片格式)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status_label)
        m4.metric("趨勢斜率", f"{slope:.2f}", help="正值代表長期趨勢向上") # 校對圖片為 5 位小數

            
        m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status, help="超過60代表極度恐慌")

        # Plotly 繪圖 (保留 650 高度與所有格式)
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

# --- 8. 概覽掃描 (包含名稱欄位) ---
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
