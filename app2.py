import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (保留原樣) ---
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

# --- 5. 數據分析與繪圖 ---
if ticker_input:
    result = get_lohas_data(ticker_input, years_input)
    if result:
        df, std_dev, slope = result
        current_price = float(df['Close'].iloc[-1])
        last_tl = df['TL'].iloc[-1]
        last_p2sd = df['TL+2SD'].iloc[-1]
        last_p1sd = df['TL+1SD'].iloc[-1]
        last_m1sd = df['TL-1SD'].iloc[-1]
        last_m2sd = df['TL-2SD'].iloc[-1]
        dist_pct = ((current_price - last_tl) / last_tl) * 100

        # 狀態判斷 (保留原邏輯)
        if current_price > last_p2sd:
            status, color = "⚠️ 過熱 (高於 +2SD)", "red"
        elif current_price > last_tl:
            status, color = "📊 相對偏高", "orange"
        elif current_price < last_m2sd:
            status, color = "💎 特價區 (低於 -2SD)", "green"
        else:
            status, color = "✅ 相對便宜", "lightgreen"

        # 顯示關鍵指標 (保留原代碼資料)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新股價", f"{current_price:.2f}")
        m2.metric("趨勢中心 (TL)", f"{last_tl:.2f}", f"{dist_pct:+.2f}%")
        m3.metric("目前狀態", status)
        m4.metric("趨勢斜率", f"{slope:.4f}")

        # --- 繪製圖表 (仿圖修正版) ---
        fig = go.Figure()
        
        # 股價線
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name='收盤價', line=dict(color='black', width=1.5)))
        
        # 定義五線譜配置 (顏色對應你圖片中的風格)
        lines_config = [
            ('TL+2SD', '#E91E63', '65', '+2SD (昂貴)'), 
            ('TL+1SD', '#F48FB1', '61', '+1SD'), 
            ('TL', '#90A4AE', '57', '中心線'), 
            ('TL-1SD', '#90CAF9', '53', '-1SD'), 
            ('TL-2SD', '#1565C0', '50', '-2SD (便宜)')
        ]
        
        # 繪製五線譜與右側彩色標籤
        for col, line_color, short_lab, long_lab in lines_config:
            val = df[col].iloc[-1]
            # 畫線
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                name=long_lab, 
                line=dict(color=line_color, width=1, dash='dash' if 'SD' in col else 'solid'),
                hoverinfo='skip'
            ))
            # 新增右側彩色標籤 (使用 Annotation 達成圖片效果)
            fig.add_annotation(
                x=df['Date'].iloc[-1], y=val,
                text=f"<b>{val:.0f}</b>",
                showarrow=False,
                xanchor="left",
                xshift=10,
                bgcolor=line_color,
                font=dict(color="white", size=12),
                borderpad=4
            )

        # 新增目前股價的黑色標籤 (對應圖片中的 67)
        fig.add_annotation(
            x=df['Date'].iloc[-1], y=current_price,
            text=f"<b>{current_price:.0f}</b>",
            showarrow=False,
            xanchor="left",
            xshift=10,
            bgcolor="black",
            font=dict(color="white", size=13),
            borderpad=4
        )
        
        # 輔助虛線 (目前股價)
        fig.add_hline(y=current_price, line_dash="dash", line_color="black", line_width=1)

        fig.update_layout(
            height=600,
            template="plotly_white",
            hovermode="x unified",
            margin=dict(l=10, r=80, t=30, b=10), # 預留右側空間放標籤
            xaxis_title="日期",
            yaxis=dict(side="right", showgrid=True, gridcolor="#F0F0F0") # 座標軸改到右邊
        )

        st.plotly_chart(fig, use_container_width=True)
        
        # --- 6. 掃描概覽表 (保留原樣) ---
        st.divider()
        st.subheader("📋 全球追蹤標立 - 位階概覽掃描")
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

# 詳細數據展開
with st.expander("查看原始數據"):
    if 'df' in locals():
        st.dataframe(df.tail(10).sort_values('Date', ascending=False))
