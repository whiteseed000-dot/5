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
        st.warning(f"目前無法連線至 Google Sheets (原因: {e})，暫時使用預設清單。")
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

# --- 5. 數據分析與繪圖 (整合照片顯示邏輯) ---
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
            status, status_color = "⚠️ 過熱 (高於 +2SD)", "red"
        elif current_price > last_tl:
            status, status_color = "📊 相對偏高", "orange"
        elif current_price < last_m2sd:
            status, status_color = "💎 特價區 (低於 -2SD)", "green"
        else:
            status, status_color = "✅ 相對便宜", "lightgreen"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # --- 繪圖邏輯 ---
        fig = go.Figure()
        
        # 收盤價主線
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            name='收盤價', 
            line=dict(color='#00DDAA', width=2)
        ))
        
        # 五線譜參數與標籤配置
        lines_config = [
            ('TL+2SD', '#FF5555', 'red', '+2 SD (極端高)'), 
            ('TL+1SD', '#FFAA00', 'orange', '+1 SD (偏高)'), 
            ('TL', '#AAAAAA', 'gray', '中心線'), 
            ('TL-1SD', '#55AAFF', 'blue', '-1 SD (偏低)'), 
            ('TL-2SD', '#00FF00', 'green', '-2 SD (極端低)')
        ]
        
        for col, hex_color, label_name, full_label in lines_config:
            # 畫線
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                name=full_label, 
                line=dict(color=hex_color, dash='dash' if 'SD' in col else 'solid'),
                hoverinfo='skip'
            ))
            
            # 末端數值標籤 (仿照片中的方塊)
            last_val = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1],
                y=last_val,
                text=f"<b>{last_val:.1f}</b>",
                showarrow=False,
                xanchor="left",
                xshift=12,
                font=dict(color="white", size=11),
                bgcolor=hex_color,
                bordercolor=hex_color,
                borderwidth=1,
                borderpad=3
            )

        # 現價水平虛線與文字 (仿照片白色虛線)
        fig.add_hline(y=current_price, line_dash="dot", line_color="white", line_width=1.5)
        fig.add_annotation(
            x=df['Date'].iloc[-1],
            y=current_price,
            text=f"現價: {current_price:.2f}",
            showarrow=False,
            xanchor="left",
            xshift=12,
            yshift=18, # 向上偏移避免重疊
            font=dict(color="white", size=13),
            bgcolor="rgba(0,0,0,0.6)"
        )

        fig.update_layout(
            height=650, 
            template="plotly_dark", # 使用深色背景更專業
            hovermode="x unified",
            margin=dict(l=10, r=80, t=30, b=10), # 右側留白 80px 給標籤
            xaxis=dict(title="日期", gridcolor='#333333'),
            yaxis=dict(title="價格", gridcolor='#333333'),
            showlegend=False
        )

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
                st.table(pd.DataFrame(summary_data))

    else:
        st.error("數據獲取失敗，請確認代號是否正確。")

with st.expander("查看原始數據"):
    if 'df' in locals():
        st.dataframe(df.tail(10).sort_values('Date', ascending=False))
