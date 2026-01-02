import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_watchlist_from_google():
    default_list = ["2330.TW", "0050.TW", "AAPL", "NVDA"]
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        records = sheet.get_all_values()
        if len(records) > 1:
            return [row[0] for row in records[1:] if row[0]]
    except Exception as e:
        st.warning("目前暫時使用預設清單。")
    return default_list

def save_watchlist_to_google(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("MyWatchlist").sheet1
        sheet.clear()
        data = [["ticker"]] + [[t] for t in watchlist]
        sheet.update("A1", data)
        st.success("成功儲存至 Google 雲端！")
    except Exception as e:
        st.error(f"儲存失敗: {e}")

# --- 2. 初始化 ---
st.set_page_config(page_title="股市五線譜 Pro", layout="wide")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist_from_google()

# --- 3. 介面佈局 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + st.session_state.watchlist)
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
    if ticker_input not in st.session_state.watchlist:
        if st.button("➕ 加入追蹤"):
            st.session_state.watchlist.append(ticker_input)
            save_watchlist_to_google(st.session_state.watchlist)
            st.rerun()
    else:
        if st.button("➖ 移除追蹤"):
            if len(st.session_state.watchlist) > 1:
                st.session_state.watchlist.remove(ticker_input)
                save_watchlist_to_google(st.session_state.watchlist)
                st.rerun()

# --- 4. 核心演算法 ---
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

# --- 5. 數據分析與繪圖 ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        
        fig = go.Figure()
        
        # 每日收盤價
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            name='每日收盤價', 
            line=dict(color='#2E7D32', width=1.5),
            hovertemplate='每日收盤價: %{y:.1f}<extra></extra>'
        ))
        
        # 配置五線譜
        lines_config = [
            ('TL+2SD', '#E53935', '+2SD (天價)'), 
            ('TL+1SD', '#FB8C00', '+1SD (偏高)'), 
            ('TL', '#FFFFFF', '趨勢線 (合理)'), 
            ('TL-1SD', '#1E88E5', '-1SD (偏低)'), 
            ('TL-2SD', '#43A047', '-2SD (特價)')
        ]
        
        for col, hex_color, name_tag in lines_config:
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                name=name_tag, 
                line=dict(color=hex_color, dash='dash' if 'SD' in col else 'solid', width=1),
                hovertemplate=f'{name_tag}: %{{y:.1f}}<extra></extra>'
            ))
            
            # 末端標籤方塊 (修正格式)
            last_val = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1],
                y=last_val,
                text=f"<b>{last_val:.1f}</b>",
                showarrow=False,
                xanchor="left",
                xshift=8,
                font=dict(color="white", size=10),
                bgcolor=hex_color,
                borderpad=3
            )

        # 現價標示
        fig.add_hline(y=current_price, line_dash="dot", line_color="white", line_width=1.5)
        fig.add_annotation(
            x=df['Date'].iloc[-1],
            y=current_price,
            text=f"現價: {current_price:.2f}",
            showarrow=False,
            xanchor="left",
            xshift=8,
            yshift=15,
            font=dict(color="white", size=12)
        )

        fig.update_layout(
            height=600, 
            template="plotly_dark",
            hovermode="x unified",
            margin=dict(l=10, r=100, t=50, b=10),
            xaxis=dict(showgrid=True, gridcolor='#262626'),
            yaxis=dict(showgrid=True, gridcolor='#262626', side="right"),
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- 6. 同步調整後的掃描概覽表 ---
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
                        t_p1 = t_df['TL+1SD'].iloc[-1]
                        t_p2 = t_df['TL+2SD'].iloc[-1]
                        t_m1 = t_df['TL-1SD'].iloc[-1]
                        t_m2 = t_df['TL-2SD'].iloc[-1]
                        
                        # 同步狀態判定與標籤
                        if p > t_p2: pos = "🔴 +2SD (天價)"
                        elif p > t_p1: pos = "🟠 +1SD (偏高)"
                        elif p > t_m1: pos = "⚪ 趨勢線 (合理)"
                        elif p > t_m2: pos = "🔵 -1SD (偏低)"
                        else: pos = "🟢 -2SD (特價)"
                        
                        summary_data.append({
                            "代號": t,
                            "最新價格": f"{p:.1f}",
                            "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.1f}%",
                            "位階狀態": pos
                        })
            
            if summary_data:
                # 使用 DataFrame 顯示，並設定樣式
                st.table(pd.DataFrame(summary_data))
    else:
        st.error("數據獲取失敗。")
