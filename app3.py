import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from plotly.subplots import make_subplots
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

# --- 2. 登入系統 ---
if "authenticated" not in st.session_state:
    st.set_page_config(page_title="登入 - 股市五線譜")
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
def get_technical_indicators(df):

    def calc_rsi(series, period):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))


    # --- RSI 依時間週期切換 ---
    if time_frame == "日":
        rsi_periods = [7, 14]
    elif time_frame == "週":
        rsi_periods = [7, 14]
    elif time_frame == "月":
        rsi_periods = [7, 14]
    
    for p in rsi_periods:
        df[f'RSI{p}'] = calc_rsi(df['Close'], p)
    
    df.attrs['rsi_periods'] = rsi_periods
    # --------------------------

    
    # MACD (12, 26, 9)
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # BIAS (20) & MA20
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['BIAS'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    # MA 季線 (60)
    df['MA60'] = df['Close'].rolling(window=60).mean()
    return df

def check_advanced_alerts(watchlist, years):
    alerts = []
    for ticker, name in watchlist.items():
        data = get_stock_data(ticker, years)
        if data:
            df, _ = data
            df = get_technical_indicators(df)
            
            # 取得最新一筆與前一筆數據 (判斷交叉)
            curr = df.iloc[-1]
            prev = df.iloc[-2]
            
            # --- 買進訊號條件 ---
            # 1. 五線譜在偏低或特價區
            is_cheap = curr['Close'] <= curr['TL-1SD']
            # 2. 技術面轉強 (滿足其一即可)
            tech_strong = (
                (prev['RSI14'] < 30 and curr['RSI14'] > 30) or       # RSI 低檔回升
                (prev['MACD'] < prev['Signal'] and curr['MACD'] > curr['Signal']) or # MACD 金叉
                (prev['Close'] < curr['MA60'] and curr['Close'] > curr['MA60'])      # 站上季線
            )
            
            # --- 賣出訊號條件 ---
            is_expensive = curr['Close'] >= curr['TL+1SD']
            tech_weak = (
                (prev['RSI14'] > 70 and curr['RSI14'] < 70) or       # RSI 高檔反轉
                (prev['MACD'] > prev['Signal'] and curr['MACD'] < curr['Signal'])    # MACD 死叉
            )

            if is_cheap and tech_strong:
                alerts.append({"name": name, "type": "BUY", "reason": "位階偏低 + 技術面轉強"})
            elif is_expensive and tech_weak:
                alerts.append({"name": name, "type": "SELL", "reason": "位階偏高 + 技術面轉弱"})
                
    return alerts

def calc_resonance_score(df):
    score = 0
    curr = df.iloc[-1]

    # --- 五線譜位階（40）---
    if curr['Close'] < curr['TL-2SD']:
        score += 40
    elif curr['Close'] < curr['TL-1SD']:
        score += 30
    elif curr['Close'] < curr['TL']:
        score += 20
    elif curr['Close'] < curr['TL+1SD']:
        score += 10

    # --- MA 趨勢（30）---
    ma_periods = df.attrs.get('ma_periods', [])
    if ma_periods:
        ma_mid = df[f'MA{ma_periods[len(ma_periods)//2]}'].iloc[-1]
        if curr['Close'] > ma_mid:
            score += 30
        elif abs(curr['Close'] - ma_mid) / ma_mid < 0.01:
            score += 15

    # --- MACD 動能（30）---
    macd = curr['MACD']
    signal = curr['Signal']
    if macd > signal and macd > 0:
        score += 30
    elif macd > signal:
        score += 20
    elif macd > 0:
        score += 10

    return min(score, 100)

def calc_resonance_score_V2(df):
    score = 0
    curr = df.iloc[-1]

    # --- 五線譜位階（40）---
    if curr['Close'] < curr['TL-2SD']:
        score += 40
    elif curr['Close'] < curr['TL-1SD']:
        score += 30
    elif curr['Close'] < curr['TL']:
        score += 20
    elif curr['Close'] < curr['TL+1SD']:
        score += 10

    # --- MA 趨勢（30）---
    ma_periods = df.attrs.get('ma_periods', [])
    if len(ma_periods) >= 3:
        ma_short = df[f'MA{ma_periods[0]}'].iloc[-1]
        ma_mid   = df[f'MA{ma_periods[len(ma_periods)//2]}'].iloc[-1]
        ma_long  = df[f'MA{ma_periods[-1]}'].iloc[-1]
    
        if ma_short > ma_mid > ma_long:
            score += 20
        elif ma_short > ma_mid:
            score += 10

        # 價格相對 MA
        if curr['Close'] > ma_mid:
            score += 10
        elif abs(curr['Close'] - ma_mid) / ma_mid < 0.01:
            score += 5

    # --- MACD 動能（30）---
    macd = curr['MACD']
    signal = curr['Signal']
    macd_diff = macd - signal
    
    if macd_diff > 0 and macd > 0:
        score += min(30, 20 + macd_diff * 50)
    elif macd_diff > 0:
        score += min(20, 10 + macd_diff * 30)
    elif macd > 0:
        score += 5

        # --- 懲罰：高檔轉弱 ---
    if curr['Close'] > curr['TL+1SD'] and macd_diff < 0:
        score -= 15
    
    # --- 懲罰：跌破趨勢 ---
    if curr['Close'] < ma_long:
        score -= 10

    return max(0, min(score, 100))

def detect_market_pattern(df, slope):
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    patterns = []

    W = 20  # 可調 10~20
    window = df.iloc[-W:]
    
    # 區間價格趨勢（線性回歸）
    x = np.arange(W)
    price_slope = np.polyfit(x, window['Close'], 1)[0]
    
    # 區間價格曲率（二階）
    price_curve = np.polyfit(x, window['Close'], 2)[0]
    
    # 區間低點抬高程度
    higher_lows = window['Low'].iloc[-5:].min() > window['Low'].iloc[:5].min()
    
    # 區間動能趨勢
    rsi_slope = np.polyfit(x, window['RSI14'], 1)[0]
    macd_slope = np.polyfit(x, window['MACD'], 1)[0]
    
    # 區間波動收斂
    range_shrink = (
        window['High'].max() - window['Low'].min()
    ) < (
        df.iloc[-2*W:-W]['High'].max() -
        df.iloc[-2*W:-W]['Low'].min()
    )

    close = df['Close']
    high = df['High']
    low = df['Low']
    tl = df['TL']
    ma_periods = df.attrs.get('ma_periods', [])
    
    ###區間型態###
    # =========================
    # 🟢 結構性底部（區間版）
    # =========================
    if (
        close.iloc[-20:].min() < df['TL-1SD'].iloc[-1] and
        close.iloc[-5:].mean() > close.iloc[-15:-5].mean() and
        df['RSI14'].iloc[-5:].mean() > df['RSI14'].iloc[-15:-5].mean() and
        -0.02 < price_slope < 0.05
    ):
        patterns.append("🟢 結構性底部（區間）")




    # 1️⃣ 回測 50 日找出第一個最低點（第一底）
    lookback = 50
    sub_df = df.iloc[-lookback:]
    first_min_idx = sub_df['Close'].idxmin()
    first_bottom_price = df.loc[first_min_idx, 'Close']

    # 2️⃣ 往右回測 ≥10 日，找「高於第一底」的次低點（第二底）
    right_df = df.loc[first_min_idx:].iloc[10:]  # 至少隔 10 日
    if len(right_df) > 10:

        second_min_idx = right_df['Close'].idxmin()
        second_bottom_price = df.loc[second_min_idx, 'Close']
    
        if second_bottom_price > first_bottom_price * 0.98:
   
            # 3️⃣ 次低點後 5 日斜率必須為正
            post_prices = df.loc[second_min_idx:].iloc[:5]['Close'].values
            if len(post_prices) > 5:

                x = np.arange(5)
                slope_post, _, _, _, _ = stats.linregress(x, post_prices)
            
                # 4️⃣ 現價需大於次低點
                if (
                    slope_post > 0 and
                    curr['Close'] > second_bottom_price and
                    curr['Close'] < curr['TL']
                ):
                    patterns.append("🟢 雙底確認（區間）")

    # =========================
    # 🟡 多頭旗形（新增）
    # =========================
    pole_window = 20
    flag_window = 8

    pole_return = close.iloc[-pole_window-flag_window:-flag_window].pct_change().sum()
    flag_range = high.iloc[-flag_window:].max() - low.iloc[-flag_window:].min()
    pole_range = high.iloc[-pole_window-flag_window:-flag_window].max() - \
                 low.iloc[-pole_window-flag_window:-flag_window].min()

    if (
        pole_return > 0.12 and
        flag_range < 0.5 * pole_range and
        close.iloc[-flag_window:].mean() > tl.iloc[-1] and
        slope > 0
    ):
        patterns.append("🟡 多頭旗形（區間）")


    # =========================
    # 🟡 均線糾結（結構）
    # =========================
    if ma_periods:
        ma_s = df[f"MA{ma_periods[0]}"].iloc[-10:].mean()
        ma_l = df[f"MA{ma_periods[2]}"].iloc[-10:].mean()

        if abs(ma_s - ma_l) / ma_l < 0.01:
            patterns.append("🟡 均線糾結（區間）")
    
    # =========================
    # 1️⃣ 回測 50 日找最低點
    lookback = 50
    sub_df = df.iloc[-lookback:]
    min_idx = sub_df['Close'].idxmin()
    bottom_price = df.loc[min_idx, 'Close']
    
    # 2️⃣ 最低點左右斜率（各 5 日）
    left_prices = df.loc[:min_idx].iloc[-5:]['Close'].values
    right_prices = df.loc[min_idx:].iloc[:5]['Close'].values

    if len(left_prices) == 5 and len(right_prices) == 5:
        x = np.arange(5)
        slope_left, _, _, _, _ = stats.linregress(x, left_prices)
        slope_right, _, _, _, _ = stats.linregress(x, right_prices)

        # 3️⃣ 現價回測 10 日，波動 ≤ 5%
        recent_prices = df['Close'].iloc[-10:]
        range_ratio = (recent_prices.max() - recent_prices.min()) / recent_prices.mean()

        if (
            slope_left < 0 and                 # 左側下跌
            slope_right > 0 and                # 右側回升
            range_ratio <= 0.05 and             # 區間盤整
            rsi_slope > 0 and                   # 動能回升
            curr['Close'] < curr['TL'] and      # 位於低檔結構
            curr['Close'] > bottom_price * 1.05         # ✅ 現價需高於碗底
        ):
            patterns.append("🟢 碗型底（區間）")

    # === ⚪ 區間盤整（非趨勢）===
    if (
        abs(price_slope) < 0.01 and
        range_shrink and
        45 < curr['RSI14'] < 55
    ):
        patterns.append("⚪ 區間盤整（區間）")

    
        # === ⚪ 箱型整理 ===
    if (
        df['High'].iloc[-50:].max() - df['Low'].iloc[-50:].min()
        < 1.5 * (curr['TL+1SD'] - curr['TL'])
    ):
        patterns.append("⚪ 箱型整理（區間）")
    
    # === 🔴 區間頭部派發 ===
    if (
        price_slope <= 0 and
        price_curve < 0 and
        macd_slope < 0 and
        curr['Close'] > curr['TL+1SD']
    ):
        patterns.append("🔴 頭部形成（區間）")


    # =========================
    # ⚪ 三角收斂（新增）
    # =========================
    tri_window = 15
    hs = high.iloc[-tri_window:]
    ls = low.iloc[-tri_window:]

    h_slope = np.polyfit(range(tri_window), hs, 1)[0]
    l_slope = np.polyfit(range(tri_window), ls, 1)[0]

    if h_slope < 0 and l_slope > 0:
        patterns.append("⚪ 三角收斂（區間）")

    # =========================
    # 🔴 跌破關鍵均線（結構）
    # =========================
    if ma_periods:
        ma_mid = df[f"MA{ma_periods[len(ma_periods)//2]}"]

        if (
            close.iloc[-5:].mean() < ma_mid.iloc[-5:].mean() and
            slope < 0
        ):
            patterns.append("🔴 跌破關鍵均線（區間）")
        
    ###區間型態###


    # === 🔴 趨勢末端（動能衰竭）===
    if (
        curr['Close'] > prev['Close'] and
        curr['RSI14'] < prev['RSI14'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 趨勢末端（動能衰竭）")

    
    # === 🟢 V 型反轉 ===
    # 1️⃣ 回測 50 日找最低點
    lookback = 10
    sub_df = df.iloc[-lookback:]
    min_idx = sub_df['Close'].idxmin()
    bottom_price = df.loc[min_idx, 'Close']
    
    # 2️⃣ 最低點左右斜率（各 3 日）
    left_prices = df.loc[:min_idx].iloc[-3:]['Close'].values
    right_prices = df.loc[min_idx:].iloc[:3]['Close'].values

    if len(left_prices) == 3 and len(right_prices) == 3:
        x = np.arange(3)
        slope_left, _, _, _, _ = stats.linregress(x, left_prices)
        slope_right, _, _, _, _ = stats.linregress(x, right_prices)

        if (
            slope_left < 0 and                 # 左側下跌
            slope_right > 0 and                # 右側回升
            rsi_slope > 0 and                   # 動能回升
            curr['Close'] > bottom_price * 1.1         # ✅ 現價需高於碗底
        ):
            patterns.append("🟢 V 型反轉")


        # === 🟢 雙底確認 ===
    if (
        abs(curr['Close'] - df['Close'].iloc[-6]) / df['Close'].iloc[-6] < 0.02 and
        curr['RSI14'] > df['RSI14'].iloc[-6] 
    ):
        patterns.append("🟢 雙底確認")


        # === 🟡 多頭旗形 ===
    if (
        df['Close'].iloc[-6] > curr['TL+1SD'] and
        curr['Close'] > curr['TL'] and
        curr['RSI14'] > 50
    ):
        patterns.append("🟡 多頭旗形（續行）")

        # === 🔴 假突破 ===
    if (
        prev['Close'] > curr['TL+1SD'] and
        curr['Close'] < curr['TL'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 假突破")

        # === ⚪ 波動擠壓（即將爆發）===
    if (
        curr['RANGE_N'] <
        df['RANGE_N'].rolling(50).quantile(0.2).iloc[-1]
    ):
        patterns.append("⚪ 波動擠壓（即將爆發）")


    # === ⚪ 財訊：盤整收斂型態 ===
    if (
        curr['RANGE_N'] < curr['RANGE_N_prev'] and
        abs(curr['Close'] - curr['TL']) / curr['TL'] < 0.01 and
        abs(curr['MACD']) < abs(prev['MACD'])
    ):
        patterns.append("⚪ 財訊盤整收斂")

    # === 🟡 財訊：三角收斂（突破前）===
    if (
        curr['RANGE_N'] < df['RANGE_N'].iloc[-2] and
        df['RANGE_N'].iloc[-2] < df['RANGE_N'].iloc[-3] and
        45 < curr['RSI14'] < 55
    ):
        patterns.append("🟡 三角收斂（突破前）")

    # === 🟡 財訊：盤整後上突破 ===
    if (
        curr['Close'] > df['Close'].iloc[-11:-1].max() and
        df['RANGE_N'].iloc[-2] < df['RANGE_N'].iloc[-3] and
        curr['MACD'] > curr['Signal'] and
        curr['RSI14'] > 55
    ):
        patterns.append("🟡 盤整後上突破（起漲型）")

    # --- 結構性底部 ---
    if (
        curr['Close'] < curr['TL-1SD'] and
        curr['RSI7'] > prev['RSI7'] and
        curr['MACD'] > prev['MACD']
    ):
        patterns.append("🟢 結構性底部")

    # --- 趨勢轉折 ---
    ma_periods = df.attrs.get('ma_periods', [])
    if ma_periods:
        ma_mid = df[f"MA{ma_periods[len(ma_periods)//2]}"]
        if prev['Close'] < ma_mid.iloc[-2] and curr['Close'] > ma_mid.iloc[-1]:
            if curr['MACD'] > curr['Signal']:
                patterns.append("🟡 趨勢轉折")

    if (
        curr['Close'] > curr['TL+1SD'] and
        slope > 0 and
        curr['RSI14'] > 60 and
        curr['MACD'] > curr['Signal']
    ):
        patterns.append("🟡 強勢趨勢延伸（高檔鈍化）")

    # --- 過熱反轉 ---
    if (
        curr['Close'] > curr['TL+2SD'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 過熱風險")
        
    if curr['Close'] < curr['TL-1SD'] and slope < 0 and curr['Close'] > curr['TL-2SD']:
        patterns.append("🔴 弱勢趨勢延續")

    if curr['RSI14'] < 20 and curr['Close'] < curr['TL-2SD']:
        patterns.append("🟢 超跌反彈觀察")
        
    # --- 底部背離（價格破底、動能回升） ---
    if (
        curr['Close'] < prev['Close'] and
        curr['RSI14'] > prev['RSI14'] and
        curr['MACD'] > prev['MACD'] and
        curr['Close'] < curr['TL-1SD']
    ):
        patterns.append("🟢 底部背離（潛在反轉）")


    # --- 均線糾結突破 ---
    if ma_periods:
        ma_short = df[f"MA{ma_periods[0]}"]
        ma_long = df[f"MA{ma_periods[2]}"]
    
        if (
            abs(ma_short.iloc[-1] - ma_long.iloc[-1]) / ma_long.iloc[-1] < 0.01 and
            curr['Close'] > ma_short.iloc[-1] and
            curr['MACD'] > curr['Signal']
        ):
            patterns.append("🟡 均線糾結突破")

        # --- 多頭疲勞 ---
    if (
        curr['Close'] > curr['TL+1SD'] and
        curr['RSI14'] < prev['RSI14'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 多頭趨勢疲勞")

        # --- 跌破關鍵均線 ---
    if ma_periods:
        ma_mid = df[f"MA{ma_periods[len(ma_periods)//2]}"]
    
        if (
            prev['Close'] > ma_mid.iloc[-2] and
            curr['Close'] < ma_mid.iloc[-1] and
            slope < 0
        ):
            patterns.append("🔴 跌破關鍵均線")

        # --- 盤整收斂 ---
    if (
        abs(curr['Close'] - curr['TL']) / curr['TL'] < 0.01 and
        abs(curr['RSI14'] - 50) < 5 and
        abs(curr['MACD']) < abs(prev['MACD'])
    ):
        patterns.append("⚪ 盤整收斂")
    
    # =========================
    # 🔵 爆大量（Volume Spike）
    # =========================

    # 1️⃣ 最新收盤日與前一日成交量
    vol_today = df['Volume'].iloc[-1]
    vol_prev = df['Volume'].iloc[-2]

    # 2️⃣ 今日成交量 > 前一日 3 倍
    if vol_today > vol_prev * 3:
        patterns.append("🔵 爆大量")
    
    return patterns

def build_resonance_rank(stock_list, time_frame):
    results = []

    for stock_id in stock_list:
        df = get_stock_data(stock_id, time_frame)
        if df is None or len(df) < 50:
            continue

        score = calc_resonance_score(df)
        price = df.iloc[-1]['Close']

        results.append({
            "股票": stock_id,
            "價格": round(price, 2),
            "共振分數": score
        })

    return pd.DataFrame(results).sort_values("共振分數", ascending=False)

def score_label(score):
    if score >= 80: return "🟢 強烈偏多"
    if score >= 60: return "🟡 偏多"
    if score >= 40: return "⚪ 中性"
    if score >= 20: return "🟠 偏弱"
    return "🔴 高風險"

def summarize_patterns(patterns):
    if not patterns:
        return ["⚪ 無明顯型態"]

    # 優先順序（越上面越重要）
    priority = [
        "🟢 結構性底部",
        "🟢 底部背離（潛在反轉）",
        "🟡 趨勢轉折",
        "🟡 回檔不破趨勢",
        "🟡 均線糾結突破",
        "🟡 強勢趨勢延伸（高檔鈍化）",
        "⚪ 盤整收斂",
        "🔴 多頭趨勢疲勞",
        "🔴 過熱風險",
        "🔴 跌破關鍵均線",
        "🔴 弱勢趨勢延續",
        "🟢 超跌反彈觀察"
    ]

    result = []

    for p in priority:
        for pat in patterns:
            if p in pat and p not in result:
                result.append(p)

    # 如果 patterns 有新型態但不在 priority 裡
    for pat in patterns:
        if pat not in result:
            result.append(pat)

    return result


def update_pattern_history(ticker, patterns):
    if "pattern_history" not in st.session_state:
        st.session_state.pattern_history = {}

    hist = st.session_state.pattern_history.get(ticker, [])
    hist = patterns  # 直接用當週
    st.session_state.pattern_history[ticker] = hist

    return " | ".join(hist) if hist else ""

# --- 4. 側邊欄 ---
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
   
    st.divider()
    st.header("📊 顯示設定")
    # 新增：時間週期選擇
    time_frame = st.selectbox(
        "時間週期 (K線頻率)",
        options=["日", "週", "月"],
        index=0
    )
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)

    # =========================
    # 📊 股價還原設定
    # =========================  
    use_adjusted_price = st.sidebar.toggle(
        "使用還原股價",
        value=True,
        help="開啟：適合長期趨勢\n關閉：適合短線、實際成交價"
    )
    # ----------------------------
    # 還原股價設定
    # ----------------------------
    if use_adjusted_price:
        st.cache_data.clear()
        auto_adjust = True
        actions = True
        repair = True
    else:
        st.cache_data.clear()
        auto_adjust = False
        actions = False
        repair = False
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
def get_stock_data(ticker, years, time_frame="日", use_adjusted_price=False): # 新增參數
    try:
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=auto_adjust, actions=actions, repair=repair)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # --- 新增：數據重採樣邏輯（符合金融慣例） ---
        if time_frame == "週":
    # 週線：週一～週五，K棒時間放在「週五」
            df = df.resample(
                'W-FRI',
                label='right',     # 時間標籤放在區間右側（週五）
                closed='right'     # 包含週五當天
            ).agg({
                'Open': 'first',   # 週一開盤
                'High': 'max',     # 全週最高
                'Low': 'min',      # 全週最低
                'Close': 'last',   # 週五收盤
                'Volume': 'sum'    # 全週成交量
            }).dropna()

        elif time_frame == "月":
    # 月線：整個月份，K棒時間放在「月底（最後交易日）」
            df = df.resample(
                'ME',
                label='right',     # 標記在月底
                closed='right'     # 包含月底最後交易日
            ).agg({
                'Open': 'first',   # 月初開盤
                'High': 'max',     # 當月最高
                'Low': 'min',      # 當月最低
                'Close': 'last',   # 月底收盤
                'Volume': 'sum'    # 當月成交量
            }).dropna()
# ----------------------------------------------
            
        # ---------------------------
# --- 依時間週期自動切換 MA 參數 ---
        if time_frame == "日":
            ma_periods = [5, 10, 20, 60, 120]
        elif time_frame == "週":
            ma_periods = [4, 13, 26, 52, 104]
        elif time_frame == "月":
            ma_periods = [3, 6, 12, 24, 48, 96]

        for p in ma_periods:
            df[f'MA{p}'] = df['Close'].rolling(window=p).mean() 
            df[f'MA{p}_slope'] = df[f'MA{p}'].diff()
            df['sell_signal'] = (
                (df['Close'] < df[f'MA{3}']) &
                (df[f'MA{3}_slope'] < 0) &
                (df['Close'] < df[f'MA{0}']) &
                (df[f'MA{0}_slope'] < 0) &
                (df['Close'] < df['Open']) &               # 本K黑
                (df['Close'].shift(1) > df['Open'].shift(1))   # 前K紅
            )
            df['buy_signal'] = (
                (df['Close'] > df[f'MA{3}']) &
                (df[f'MA{3}_slope'] > 0) &
                (df['Close'] > df[f'MA{0}']) &
                (df[f'MA{0}_slope'] > 0) &
                (df['Close'] > df['Open']) &              # 本K紅
                (df['Close'].shift(1) < df['Open'].shift(1))  # 前K黑
            )
            
        df.attrs['ma_periods'] = ma_periods

# ----------------------------------        
        df = df.reset_index()
        df['x'] = np.arange(len(df))
        
        # --- 趨勢線計算（週線使用加權回歸） ---
        x = df['x'].values
        y = df['Close'].values

        if time_frame == "週":
            # 權重：越近權重越大（平方加權）
            w = np.linspace(0.3, 1.0, len(x)) ** 2
            slope, intercept = np.polyfit(x, y, 1, w=w)
            # 加權 R²
            y_hat = slope * x + intercept
            r_squared = 1 - np.sum(w * (y - y_hat)**2) / np.sum(w * (y - np.average(y, weights=w))**2)
        else:
            slope, intercept, r_value, _, _ = stats.linregress(x, y)
            r_squared = r_value ** 2

        df['TL'] = slope * x + intercept
# ---------------------------------------

        
        # --- 五線譜 SD 倍數依時間尺度調整 ---
        if time_frame == "日":
            sd1, sd2 = 1.0, 2.0
        elif time_frame == "週":
            sd1, sd2 = 1.2, 2.4
        elif time_frame == "月":
            sd1, sd2 = 1.5, 3.0

        std = np.std(df['Close'] - df['TL'])
        df['TL+1SD'] = df['TL'] + sd1 * std
        df['TL-1SD'] = df['TL'] - sd1 * std
        df['TL+2SD'] = df['TL'] + sd2 * std
        df['TL-2SD'] = df['TL'] - sd2 * std
        # ------------------------------------

        
        # 加入技術指標計算
        df = get_technical_indicators(df)        
        # 指標
        low_9 = df['Low'].rolling(9).min(); high_9 = df['High'].rolling(9).max()
        rsv = 100 * (df['Close'] - low_9) / (high_9 - low_9)
        df['K'] = rsv.ewm(com=2).mean(); df['D'] = df['K'].ewm(com=2).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['BB_up'] = df['MA20'] + 2 * df['Close'].rolling(20).std()
        df['BB_low'] = df['MA20'] - 2 * df['Close'].rolling(20).std()
        

        # --- 樂活通道核心計算（依時間尺度修正） ---
        if time_frame == "日":
            h_window = 100      # 約 5 個月
            band_pct = 0.10
        elif time_frame == "週":
            h_window = 52       # 約 1 年
            band_pct = 0.15
        elif time_frame == "月":
            h_window = 24       # 約 2 年
            band_pct = 0.20
        
        df['H_TL'] = df['Close'].rolling(window=h_window, min_periods=h_window//2).mean()
        
        df['H_TL+1SD'] = df['H_TL'] * (1 + band_pct)
        df['H_TL-1SD'] = df['H_TL'] * (1 - band_pct)


        # 價格一階 / 二階差分（趨勢彎曲度）
        df['dP'] = df['Close'].diff()
        df['ddP'] = df['dP'].diff()
        
        # 近 N 日高低區間（收斂用）
        N = 10
        df['RANGE_N'] = (
            df['High'].rolling(N).max() -
            df['Low'].rolling(N).min()
        )
        
        df['RANGE_N_prev'] = df['RANGE_N'].shift(1)
        
        return df, (slope, r_squared)
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
    st.markdown(f'#  {ticker_input} ({stock_name})', unsafe_allow_html=True, help="若無法顯示資料，請按右上角 ⋮ → Clear cache")

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

result = get_stock_data(ticker_input, years_input, time_frame)

vix_val = get_vix_index()

if result:
    df, (slope, r_squared) = result
    curr = float(df['Close'].iloc[-1]); tl_last = df['TL'].iloc[-1]
    dist_pct = ((curr - tl_last) / tl_last) * 100

    #
    patterns = detect_market_pattern(df, slope)
    
    if patterns:
        st.markdown("### 🧠 AI 市場型態判讀")
        for p in patterns:
            st.write(p)
    #
    
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
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{dist_pct:+.2f}%", delta_color="inverse")
    m3.metric("目前狀態", status_label)
    m4.metric("趨勢斜率", f"{slope:.2f}", help="正值代表長期趨勢向上")
    m5.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status, delta_color="off", help="超過60代表極度恐慌")

    # --- 7. 切換按鈕 ---
    
    st.divider()
    show_detailed_metrics = st.toggle("顯示詳細指標", value=False)
    if show_detailed_metrics:

        c_rsi = df['RSI14'].iloc[-1]; c_macd = df['MACD'].iloc[-1]
        c_sig = df['Signal'].iloc[-1]; c_bias = df['BIAS'].iloc[-1]
        ma60_last = df['MA60'].iloc[-1]
        
        i1, i2, i3, i4, i5, i6 = st.columns(6)
        rsi_status = "🔥 超買" if c_rsi > 70 else ("❄️ 超跌" if c_rsi < 30 else "⚖️ 中性")
        i1.metric("RSI (14)", f"{c_rsi:.1f}", rsi_status, delta_color="off")
        
        macd_delta = c_macd - c_sig
        macd_status = "📈 金叉" if macd_delta > 0 else "📉 死叉"
        i2.metric("MACD 趨勢", f"{c_macd:.2f}", macd_status, delta_color="off")
        
        bias_status = "⚠️ 乖離大" if abs(c_bias) > 5 else "✅ 穩定"
        i3.metric("月線乖離 (BIAS)", f"{c_bias:+.2f}%", bias_status, delta_color="off")
        
        ma60_status = "🚀 站上季線" if curr > ma60_last else "🩸 跌破季線"
        i4.metric("季線支撐 (MA60)", f"{ma60_last:.1f}", ma60_status, delta_color="off")

        r2_status = "🎯 趨勢極準" if r_squared > 0.8 else ("✅ 具參考性" if r_squared > 0.5 else "❓ 參考性低")
        i5.metric("決定係數 (R²)", f"{r_squared:.2f}", r2_status, delta_color="off", help="數值越接近 1，代表五線譜趨勢線對股價的解釋力越強。")

        res_score = calc_resonance_score(df)
        res_label = (
            "🟢 強烈偏多" if res_score >= 80 else
            "🟡 偏多" if res_score >= 60 else
            "⚪ 中性" if res_score >= 40 else
            "🟠 偏弱" if res_score >= 20 else
            "🔴 高風險"
        )     
        i6.metric("多指標共振分數", f"{res_score}/100", res_label, delta_color="off")
        
        st.write("")
    
    view_mode = st.radio("分析視圖", ["樂活五線譜", "樂活通道", "K線指標", "KD指標", "布林通道", "成交量"], horizontal=True, label_visibility="collapsed")

    col_sub1, col_sub2 = st.columns([1, 4])
    with col_sub1: show_sub_chart = st.toggle("開啟副圖", value=False)
    with col_sub2: sub_mode = st.selectbox("選擇副圖指標", ["KD指標", "成交量", "RSI", "MACD"], label_visibility="collapsed")

    # --- 8. 繪圖核心 ---
    t_row = 1 if show_sub_chart else None
    t_col = 1 if show_sub_chart else None

    if show_sub_chart:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    else:
        fig = go.Figure()
    
    # --- 8. 圖表核心 (修正縮排並新增 K線指標) ---
    
    if view_mode == "樂活五線譜":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#F08C8C', width=2), name="收盤價", hovertemplate='%{y:.1f}'))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=hex_color, dash=line_style, width=1.5), name=name_tag, hovertemplate='%{y:.1f}'))
            last_val = df[col].iloc[-1]
            fig.add_annotation(x=df['Date'].iloc[-1], y=last_val, text=f"<b>{last_val:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=hex_color, size=13))

    elif view_mode == "樂活通道":
        # 繪製主收盤價線
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#F08C8C', width=2), name="收盤價", hovertemplate='%{y:.1f}'))
        
        # 通道配置：顏色與五線譜連動，方便判斷位階
        h_lines_config = [ 
            ('H_TL+1SD', '#FFBD03', '通道上軌', 'dash'), 
            ('H_TL', '#FFFFFF', '趨勢中軸', 'solid'), 
            ('H_TL-1SD', '#0096FF', '通道下軌', 'dash'), 
        ]
        
        for col, hex_color, name_tag, line_style in h_lines_config:
            # 確保有數據才繪圖 (100MA 需要前100天數據)
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df['Date'], y=df[col], 
                    line=dict(color=hex_color, dash=line_style, width=1.5), 
                    name=name_tag,
                    hovertemplate='%{y:.1f}'
                ))
                
                # 加上右側數值標籤 (模擬截圖中的標記)
                last_val = df[col].iloc[-1]
                if not np.isnan(last_val):
                    fig.add_annotation(
                        x=df['Date'].iloc[-1], y=last_val,
                        text=f"<b>{last_val:.1f}</b>",
                        showarrow=False, xanchor="left", xshift=10,
                        font=dict(color=hex_color, size=12),
                        bgcolor="rgba(0,0,0,0.6)"
                    )
    elif view_mode == "K線指標":
        # 1. 繪製 K 線，並設定 hovertemplate 顯示小數點第一位
        fig.add_trace(go.Candlestick(
            x=df['Date'],
            open=df['Open'].apply(lambda x: round(x, 1)), 
            high=df['High'].apply(lambda x: round(x, 1)),
            low=df['Low'].apply(lambda x: round(x, 1)), 
            close=df['Close'].apply(lambda x: round(x, 1)),
            name="",
            increasing_line_color='#FF3131', # 漲：紅
            decreasing_line_color='#00FF00'  # 跌：綠
            # 自定義 K 線懸浮文字格式
        ))
        
        fig.add_trace(go.Scatter(
            x=df.loc[df['buy_signal'], 'Date'],
            y=df.loc[df['buy_signal'], 'Low'] * 0.995,   # 當日最低價下方
            mode='markers',
            marker=dict(
                symbol='triangle-up',
                size=12,
                color='#00FF00'
            ),
            name='買入訊號'
        ))
        fig.add_trace(go.Scatter(
            x=df.loc[df['sell_signal'], 'Date'],
            y=df.loc[df['sell_signal'], 'High'] * 1.005, # 當日最高價上方
            mode='markers',
            marker=dict(
                symbol='triangle-down',
                size=12,
                color='#FF3131'
            ),
            name='賣出訊號'
        ))


        # 2. 疊加 MA 線段 (5, 10, 20, 60, 120)
        # 從 df 取回 MA 週期（不會 NameError）
        ma_periods = df.attrs.get('ma_periods', [])
        ma_colors = ['#FDDD42', '#87DCF6', '#C29ACF', '#F3524F', '#009B3A', '#FF66CC']

        ma_list = [
            (f'MA{p}', ma_colors[i % len(ma_colors)], f'{p}MA')
            for i, p in enumerate(ma_periods)
        ]

        
        for col, color, name in ma_list:
            if col in df.columns:
                fig.add_trace(go.Scatter(x=df['Date'], y=df[col], name=name, line=dict(color=color, width=1.2), hovertemplate='%{y:.1f}'
                          
        ))
        
        fig.update_layout(xaxis_rangeslider_visible=False) # 隱藏下方的滑桿

    elif view_mode == "KD指標":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['K'], name="K", line=dict(color='#FF3131', width=2), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['D'], name="D", line=dict(color='#0096FF', width=2), hovertemplate='%{y:.1f}'))
        fig.add_hline(y=80, line_dash="dot", line_color="rgba(255,255,255,0.3)")
        fig.add_hline(y=20, line_dash="dot", line_color="rgba(255,255,255,0.3)")

    elif view_mode == "布林通道":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="收盤價", line=dict(color='#F08C8C', width=2), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_up'], name="上軌", line=dict(color='#FF3131', dash='dash'), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['MA20'], name="20MA", line=dict(color='#FFBD03'), hovertemplate='%{y:.1f}'))
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BB_low'], name="下軌", line=dict(color='#00FF00', dash='dash'), hovertemplate='%{y:.1f}'))

    elif view_mode == "成交量":
        bar_colors = ['#FF3131' if c > o else '#00FF00' for o, c in zip(df['Open'], df['Close'])]
        fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], marker_color=bar_colors, name="成交量", hovertemplate='%{y:.0f}'))

    # 共同佈局設定
    if view_mode not in ["成交量", "KD指標"]:
        fig.add_hline(y=curr, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(x=df['Date'].iloc[-1], y=curr, text=f"現價: {curr:.2f}", showarrow=False, xanchor="left", xshift=10, yshift=15, font=dict(color="#FFFFFF", size=14, family="Arial Black"))


    if show_sub_chart:
        if sub_mode == "KD指標":
            fig.add_trace(go.Scatter(x=df['Date'], y=df['K'], name="K", line=dict(color='#FF3131'), hovertemplate='%{y:.1f}'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df['Date'], y=df['D'], name="D", line=dict(color='#0096FF'), hovertemplate='%{y:.1f}'), row=2, col=1)
        elif sub_mode == "成交量":
            v_colors = ['#FF3131' if c > o else '#00FF00' for o, c in zip(df['Open'], df['Close'])]
            fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], marker_color=v_colors, name="成交量", hovertemplate='%{y:.0f}'), row=2, col=1)
        elif sub_mode == "RSI":
            rsi_periods = df.attrs.get('rsi_periods', [])
            for p, color in zip(rsi_periods, ['#00BFFF', '#E066FF']):
                fig.add_trace(
                    go.Scatter(
                        x=df['Date'],
                        y=df[f'RSI{p}'],
                        name=f'RSI{p}',
                        line=dict(color=color, width=1.5),
                        hovertemplate='%{y:.2f}'
                    ),
                    row=2, col=1
                )
        elif sub_mode == "MACD":
            m_diff = df['MACD'] - df['Signal']
            m_colors = ['#FF3131' if v > 0 else '#00FF00' for v in m_diff]
            fig.add_trace(go.Bar(x=df['Date'], y=m_diff, marker_color=m_colors, name="柱狀圖", hovertemplate='%{y:.2f}'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df['Date'], y=df['MACD'], line=dict(color='#00BFFF'), name="MACD", hovertemplate='%{y:.2f}'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df['Date'], y=df['Signal'], line=dict(color='#E066FF'), name="Signal", hovertemplate='%{y:.2f}'), row=2, col=1)
    
    # 使用 Pandas 的 Set 運算取代 Python 迴圈，速度提升數十倍

    # --- X 軸缺口處理（只適用於日線） ---
    if time_frame == "日":
        dt_all = pd.date_range(
            start=df['Date'].min(),
            end=df['Date'].max(),
            freq='D'
        )
        dt_breaks = dt_all.difference(df['Date'])

        if not dt_breaks.empty:
            fig.update_xaxes(
                rangebreaks=[dict(values=dt_breaks.tolist())]
            )
# 週線 / 月線：不使用 rangebreaks，避免 K 棒中心位移
# -----------------------------------


    fig.update_layout(
        height=800 if show_sub_chart else 650,
        plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1E1E1E", font_size=12),
        showlegend=False, 
        margin=dict(l=10, r=100, t=10, b=10),
        
        xaxis=dict(
            showspikes=True, # 顯示指引線
            spikemode="across", # 穿過整個圖表
            spikethickness=1,
            spikecolor="white", # 設定為白色
            spikedash="solid",   # 實線 (若要虛線改為 dash)
        )
    )    
        # 如果有開啟副圖，額外設定副圖的 Y 軸指引線顏色為白色
    if show_sub_chart:
        fig.update_layout(
        xaxis2=dict(
            showspikes=True, # 顯示指引線
            spikemode="across", # 穿過整個圖表
            spikethickness=1,
            spikecolor="white", # 設定為白色
            spikedash="solid"   # 實線 (若要虛線改為 dash)
        )
    )
    st.plotly_chart(fig, use_container_width=True)
    
# ==================================================
# 二、Watchlist「共振排行榜」（全收藏掃描）
# ==================================================
st.divider()
if st.button("## 🏆 Watchlist 共振排行榜"):
    resonance_rows = []
    
    for ticker, name in st.session_state.watchlist_dict.items():
        res = get_stock_data(ticker, years_input, time_frame)
        if not res:
            continue
    
        tdf, trend_info = res
        if trend_info is None or len(tdf) < 50:
            continue
    
        slope = trend_info[0]
    
        # ========= 原本共振分數 =========
        score = calc_resonance_score(tdf)
        score_V2 = calc_resonance_score_V2(tdf)
        # ========= AI 市場型態（穩定版） =========
        patterns = detect_market_pattern(tdf, slope)
        stable_pattern = update_pattern_history(ticker, patterns)
    
        # ========= 價格 / TL =========
        curr_price = float(tdf['Close'].iloc[-1])
        tl_last = tdf['TL'].iloc[-1]
        dist_pct = ((curr_price - tl_last) / tl_last) * 100
    
        resonance_rows.append({
            "代號": ticker,
            "名稱": name,
            "共振分數": score,
            "共振分數V2": f"{score_V2:.1f}",
            "狀態": score_label(score),
            "最新價格": f"{curr_price:.1f}",
            "偏離 TL": f"{dist_pct:+.1f}%",
            "AI 市場型態": stable_pattern,
        })
    
    # ========= 顯示排行榜 =========
    if resonance_rows:
        df_rank = pd.DataFrame(resonance_rows)
    
        # 依共振分數排序（高 → 低）
        df_rank = df_rank.sort_values("共振分數", ascending=False)
    
        st.dataframe(
            df_rank,
            use_container_width=True,
            hide_index=True,
            column_config={
                "代號": st.column_config.TextColumn(width="small"),
                "名稱": st.column_config.TextColumn(width="small"),
                "共振分數": st.column_config.NumberColumn(width="small"),
                "共振分數V2": st.column_config.NumberColumn(width="small"),
                "狀態": st.column_config.TextColumn(width="small"),
                "最新價格": st.column_config.TextColumn(width="small"),
                "偏離 TL": st.column_config.TextColumn(width="small"),
                "AI 市場型態": st.column_config.TextColumn(),
            }
        )
    else:
        st.info("目前收藏清單中沒有可計算共振分數的股票。")


# --- 9. 掃描 ---
st.divider()
if st.button("🔄 開始掃描所有標的狀態"):
    summary = []
    for t, name in st.session_state.watchlist_dict.items():
        res = get_stock_data(t, years_input, time_frame)
        if res:
            tdf, _ = res; p = float(tdf['Close'].iloc[-1]); t_tl = tdf['TL'].iloc[-1]
            if p > tdf['TL+2SD'].iloc[-1]: pos = "🔴 天價"
            elif p > tdf['TL+1SD'].iloc[-1]: pos = "🟠 偏高"
            elif p > tdf['TL-1SD'].iloc[-1]: pos = "⚪ 合理"
            elif p > tdf['TL-2SD'].iloc[-1]: pos = "🔵 偏低"
            else: pos = "🟢 特價"
            summary.append({"代號": t, "名稱": name, "最新價格": f"{p:.1f}", "偏離中心線": f"{((p-t_tl)/t_tl)*100:+.1f}%", "位階狀態": pos})
    if summary: st.table(pd.DataFrame(summary))
# --- 3. UI 顯示部分 (放置於指標儀表板下方) ---

# 點擊掃描按鈕後觸發
if st.button("🔍 多指標雷達掃描"):
    st.cache_data.clear() 
    with st.spinner("正在計算 RSI/MACD/MA/BIAS 共振訊號..."):
        adv_alerts = check_advanced_alerts(st.session_state.watchlist_dict, years_input)
        
        if adv_alerts:
            st.write("### 🔔 即時策略警示")
            for alert in adv_alerts:
                if alert['type'] == "BUY":
                    st.success(f"✅ **買進建議：{alert['name']}** ({alert['reason']})")
                else:
                    st.error(f"⚠️ **減碼建議：{alert['name']}** ({alert['reason']})")
        else:
            st.info("目前沒有標的符合共振條件。")
