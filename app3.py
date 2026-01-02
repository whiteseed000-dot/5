import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 邏輯 (加入錯誤攔截) ---
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

# --- 3. 介面佈局 (先定義變數避免 NameError) ---
with st.sidebar:
    st.header("📋 追蹤清單")
    quick_pick = st.selectbox("我的收藏", options=["-- 手動輸入 --"] + st.session_state.watchlist)
    st.divider()
    st.header("⚙️ 搜尋設定")
    default_val = quick_pick if quick_pick != "-- 手動輸入 --" else "2330.TW"
    ticker_input = st.text_input("股票代號", value=default_val).upper().strip()
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

# 佈局主標題與按鈕
col_title, col_btn = st.columns([4, 1])

with col_title:
    st.title(f"📈 樂活五線譜: {ticker_input}")

with col_btn:
    # 這裡現在絕對不會報 NameError 了
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
# --- 5. 數據分析與繪圖 (優化標籤顯示) ---
        fig = go.Figure()
        
        # 繪製主收盤價線
        fig.add_trace(go.Scatter(
            x=df['Date'], y=df['Close'], 
            name='收盤價', 
            line=dict(color='#00DDAA', width=2)
        ))
        
        # 定義五線譜的參數
        lines = [
            ('TL+2SD', 'red', '34.7', '+2 SD (昂貴)'), 
            ('TL+1SD', 'orange', '33.0', '+1SD'), 
            ('TL', 'gray', '31.3', '中心線'), 
            ('TL-1SD', 'lightblue', '29.5', '-1SD'), 
            ('TL-2SD', 'green', '27.8', '-2 SD (便宜)')
        ]
        
        for col, color, _, label in lines:
            # 1. 繪製虛線
            fig.add_trace(go.Scatter(
                x=df['Date'], y=df[col], 
                name=label, 
                line=dict(color=color, dash='dash' if 'SD' in col else 'solid'),
                hoverinfo='skip' # 避免標籤干擾 hover
            ))
            
            # 2. 在線段末端添加數值標籤 (仿照圖片右側方塊)
            last_value = df[col].iloc[-1]
            fig.add_annotation(
                x=df['Date'].iloc[-1],
                y=last_value,
                text=f"<b>{last_value:.1f}</b>", # 顯示數值
                showarrow=False,
                xanchor="left",
                xshift=10,
                font=dict(color="white", size=12),
                bgcolor=color, # 背景顏色與線條一致
                bordercolor=color,
                borderwidth=1,
                borderpad=2
            )

        # 3. 繪製現價橫線與標籤 (圖片中的白色虛線與 "現價: 33.75")
        fig.add_hline(
            y=current_price, 
            line_dash="dot", 
            line_color="white", 
            line_width=2
        )
        
        fig.add_annotation(
            x=df['Date'].iloc[-1],
            y=current_price,
            text=f"現價: {current_price:.2f}",
            showarrow=False,
            xanchor="left",
            xshift=10,
            yshift=15, # 稍微往上飄，避免壓到線
            font=dict(color="white", size=13),
            bgcolor="rgba(0,0,0,0.5)" # 半透明黑背景
        )

        # 調整版面配置，確保右側標籤不會被切掉
        fig.update_layout(
            height=600, 
            template="plotly_dark", # 使用深色主題更像圖片風格
            hovermode="x unified",
            margin=dict(l=10, r=80, t=30, b=10), # r=80 留白給右側標籤
            xaxis_title="日期", 
            yaxis_title="價格",
            showlegend=False # 因為右邊已有標籤，可隱藏圖例讓畫面簡潔
        )

        st.plotly_chart(fig, use_container_width=True)
 #       
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



# 詳細數據展開
with st.expander("查看原始數據"):
    if 'df' in locals():
        st.dataframe(df.tail(10).sort_values('Date', ascending=False))
