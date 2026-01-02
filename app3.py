import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 核心雲端邏輯 ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def get_user_credentials():
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet("users")
        records = sheet.get_all_records()
        return {str(row['username']): str(row['password']) for row in records}
    except: return {"admin": "1234"}

def load_watchlist_from_google(username):
    """讀取清單，若無分頁則自動建立並預設台積電"""
    default_dict = {"2330.TW": "台積電"}
    try:
        client = get_gsheet_client()
        spreadsheet = client.open("MyWatchlist")
        
        # 獲取所有分頁名稱，確保是最新的
        worksheet_list = [sh.title for sh in spreadsheet.worksheets()]
        
        if username not in worksheet_list:
            try:
                # 建立新分頁
                sheet = spreadsheet.add_worksheet(title=username, rows="100", cols="20")
                # 預設資料
                header_and_default = [["ticker", "name"], ["2330.TW", "台積電"]]
                # 使用 update 寫入資料
                sheet.update("A1", header_and_default)
                st.toast(f"已為新使用者 {username} 建立雲端分頁！", icon="✅")
                return default_dict
            except Exception as e:
                st.error(f"建立分頁失敗: {e}")
                return default_dict
        else:
            # 分頁已存在，正常讀取
            sheet = spreadsheet.worksheet(username)
            records = sheet.get_all_values()
            if len(records) > 1:
                # 排除標題列並過濾空值
                return {row[0]: row[1] if len(row) > 1 else "" for row in records[1:] if row and row[0]}
            else:
                return default_dict
                
    except Exception as e:
        st.error(f"雲端連線異常: {e}")
        return default_dict

def save_watchlist_to_google(username, watchlist_dict):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").worksheet(username)
        sheet.clear()
        data = [["ticker", "name"]] + [[t, n] for t, n in watchlist_dict.items()]
        sheet.update("A1", data)
    except: pass

# --- 2. 登入系統 ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入 - 股市五線譜", page_icon="🔐")
    st.title("🔐 樂活五線譜 Pro")
    with st.form("login"):
        user = st.text_input("帳號")
        pw = st.text_input("密碼", type="password")
        if st.form_submit_button("登入"):
            creds = get_user_credentials()
            if user in creds and creds[user] == pw:
                # --- 關鍵修正：登入成功後，立即清理所有快取 ---
                st.cache_data.clear() 
                
                st.session_state.authenticated = True
                st.session_state.username = user
                # 確保舊帳號的清單不會殘留
                if 'watchlist_dict' in st.session_state:
                    del st.session_state.watchlist_dict
                st.rerun()
            else: st.error("帳號或密碼錯誤")
    st.stop()

# --- 3. 初始化設定 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")
username = st.session_state.username
if 'watchlist_dict' not in st.session_state:
    st.session_state.watchlist_dict = load_watchlist_from_google(username)

# 顏色配置與線段
lines_config = [
    ('TL+2SD', '#FF3131', '+2SD (天價)', 'dash'), 
    ('TL+1SD', '#FFBD03', '+1SD (偏高)', 'dash'), 
    ('TL', '#FFFFFF', '趨勢線 (合理)', 'solid'), 
    ('TL-1SD', '#0096FF', '-1SD (偏低)', 'dash'), 
    ('TL-2SD', '#00FF00', '-2SD (特價)', 'dash')
]

# --- 4. 側邊欄 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    ticker_list = list(st.session_state.watchlist_dict.keys())
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + ticker_list)
    st.divider()
    st.header("⚙️ 搜尋設定")
    ticker_input = st.text_input("股票代號", value=quick_pick if quick_pick != "-- 手動輸入 --" else "").upper().strip()
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
    st.divider()
# 在側邊欄的登出按鈕部分
    if st.button("🚪 登出帳號"):
    # 清理快取
        st.cache_data.clear()
    # 清理 Session 狀態
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- 5. 核心運算 ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker, years):
    try:
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df['x'] = np.arange(len(df))
        slope, intercept, _, _, _ = stats.linregress(df['x'], df['Close'])
        df['TL'] = slope * df['x'] + intercept
        std = np.std(df['Close'] - df['TL'])
        df['TL+2SD'], df['TL+1SD'] = df['TL'] + 2*std, df['TL'] + std
        df['TL-1SD'], df['TL-2SD'] = df['TL'] - std, df['TL'] - 2*std
        
        # 指標
        low_9 = df['Low'].rolling(9).min(); high_9 = df['High'].rolling(9).max()
        rsv = 100 * (df['Close'] - low_9) / (high_9 - low_9)
        df['K'] = rsv.ewm(com=2).mean(); df['D'] = df['K'].ewm(com=2).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['BB_up'] = df['MA20'] + 2 * df['Close'].rolling(20).std()
        df['BB_low'] = df['MA20'] - 2 * df['Close'].rolling(20).std()
        return df, slope
    except: return None

@st.cache_data(ttl=3600)
def get_vix_index():
    try:
        vix = yf.download("^VIX", period="1d", progress=False)
        return float(vix['Close'].iloc[-1])
    except: return 0.0

# --- 6. 介面形式恢復 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown(f'# <img src="https://cdn-icons-png.flaticon.com/512/421/421644.png" width="30"> 樂活五線譜: {ticker_input} ({stock_name})', unsafe_allow_html=True, help="若無法顯示資料，請按右上角 ⋮ → Clear cache")

with col_btn:
    if ticker_input in st.session_state.watchlist_dict:
        if st.button("➖ 移除追蹤"):
            del st.session_state.watchlist_dict[ticker_input]
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
            st.rerun()
    else:
        new_name = st.text_input("股票中文名稱")
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist_dict[ticker_input] = new_name
            save_watchlist_to_google(username, st.session_state.watchlist_dict)
            st.rerun()

result = get_stock_data(ticker_input, years_input)
vix_val = get_vix_index()

if result:
    df, slope = result
    curr = float(df['Close'].iloc[-1]); tl_last = df['TL'].iloc[-1]
    dist_pct = ((curr - tl_last) / tl_last) * 100

    if curr > df['TL+2SD'].iloc[-1]: status_label = "🔴 天價"
    elif curr > df['TL+1SD'].iloc[-1]: status_label = "🟠 偏高"
    elif curr > df['TL-1SD'].iloc[-1]: status_label = "⚪ 合理"
    elif curr > df['TL-2SD'].iloc[-1]: status_label = "🔵 偏低"
    else: status_label = "🟢 特價"

    if vix_val >= 30: vix_status = "🔴 恐慌"
    elif vix_val > 15: vix_status = "🟠 警戒"
    elif round(vix_val) == 15: vix_status = "⚪ 穩定"
    elif vix_val > 0: vix_status = "🔵 樂觀"
    else: vix_status = "🟢 極致樂觀"

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("最新股價", f"{curr:.2f}")
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{dist_pct:+.2f}%")
    m3.metric("目前狀態", status_label)
    m4.metric("趨勢斜率", f"{slope:.2f}", help="正值代表長期趨勢向上")
    m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status, help="超過60代表極度恐慌")

    # --- 7. 切換按鈕 ---
    st.divider()
    with st.container():
        c_rsi = df['RSI'].iloc[-1]; c_macd = df['MACD'].iloc[-1]
        c_sig = df['Signal'].iloc[-1]; c_bias = df['BIAS'].iloc[-1]
        ma60_last = df['MA60'].iloc[-1]
        
        i1, i2, i3, i4 = st.columns(4)
        rsi_status = "🔥 超買" if c_rsi > 70 else ("❄️ 超跌" if c_rsi < 30 else "⚖️ 中性")
        i1.metric("RSI (14)", f"{c_rsi:.1f}", rsi_status, delta_color="off")
        
        macd_delta = c_macd - c_sig
        macd_status = "📈 金叉" if macd_delta > 0 else "📉 死叉"
        i2.metric("MACD 趨勢", f"{c_macd:.2f}", macd_status)
        
        bias_status = "⚠️ 乖離大" if abs(c_bias) > 5 else "✅ 穩定"
        i3.metric("月線乖離 (BIAS)", f"{c_bias:+.2f}%", bias_status, delta_color="inverse")
        
        ma60_status = "🚀 站上季線" if curr > ma60_last else "🩸 跌破季線"
        i4.metric("季線支撐 (MA60)", f"{ma60_last:.1f}", ma60_status)
    
    st.write("")
    view_mode = st.radio("分析視圖", ["樂活五線譜", "KD指標", "布林通道", "成交量"], horizontal=True, label_visibility="collapsed")

    # --- 8. 圖表核心 (修正文字重複問題) ---
    fig = go.Figure()
    
    if view_mode == "樂活五線譜":
        # 修正：hovertemplate 移除手寫文字，直接使用 %{y} 即可，因為文字會由 name 自動提供
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#00D084', width=2), name="收盤價", hovertemplate='%{y:.1f}'))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=hex_color, dash=line_style, width=1.5), name=name_tag, hovertemplate='%{y:.1f}'))
            last_val = df[col].iloc[-1]
            fig.add_annotation(x=df['Date'].iloc[-1], y=last_val, text=f"<b>{last_val:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=hex_color, size=13))

    elif view_mode == "KD指標":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['K'], name="K", line=dict(color='#FF3131', width=2), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['D'], name="D", line=dict(color='#0096FF', width=2), hovertemplate='%{y:.1f}'))
        fig.add_hline(y=80, line_dash="dot", line_color="rgba(255,255,255,0.3)"); fig.add_hline(y=20, line_dash="dot", line_color="rgba(255,255,255,0.3)")

    elif view_mode == "布林通道":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="收盤價", line=dict(color='#00D084', width=2), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_up'], name="上軌", line=dict(color='#FF3131', dash='dash'), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['MA20'], name="20MA", line=dict(color='#FFBD03'), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_low'], name="下軌", line=dict(color='#00FF00', dash='dash'), hovertemplate='%{y:.1f}'))

    elif view_mode == "成交量":
        bar_colors = ['#FF3131' if c > o else '#00FF00' for o, c in zip(df['Open'], df['Close'])]
        fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], marker_color=bar_colors, name="成交量", hovertemplate='%{y}'))

    # 共同設定
    if view_mode not in ["成交量", "KD指標"]:
        fig.add_hline(y=curr, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(x=df['Date'].iloc[-1], y=curr, text=f"現價: {curr:.2f}", showarrow=False, xanchor="left", xshift=10, yshift=15, font=dict(color="#FFFFFF", size=14, family="Arial Black"))

    fig.update_layout(
        height=650, plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1E1E1E", font_size=12),
        showlegend=False, margin=dict(l=10, r=100, t=10, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)

# --- 9. 掃描 ---
st.divider()
if st.button("🔄 開始掃描所有標的狀態"):
    summary = []
    for t, name in st.session_state.watchlist_dict.items():
        res = get_stock_data(t, years_input)
        if res:
            tdf, _ = res; p = float(tdf['Close'].iloc[-1]); t_tl = tdf['TL'].iloc[-1]
            if p > tdf['TL+2SD'].iloc[-1]: pos = "🔴 天價"
            elif p > tdf['TL+1SD'].iloc[-1]: pos = "🟠 偏高"
            elif p > tdf['TL-1SD'].iloc[-1]: pos = "⚪ 合理"
            elif p > tdf['TL-2SD'].iloc[-1]: pos = "🔵 偏低"
            else: pos = "🟢 特價"
            summary.append({"代號": t, "名稱": name, "最新價格": f"{p:.1f}", "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.1f}%", "位階狀態": pos})
    if summary: st.table(pd.DataFrame(summary))
