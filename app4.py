import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import plotly.graph_objects as go
from datetime import datetime, timedelta
import gspread
import time
import random
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

def calc_rsi(series, period):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_technical_indicators(df):
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
    
    # BIAS (20) & MA20 & 布林通道 & BandWidth
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['BIAS'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    std20 = df['Close'].rolling(20).std()
    df['BB_up'] = df['MA20'] + 2 * std20
    df['BB_low'] = df['MA20'] - 2 * std20
    # 計算帶寬指標 (BandWidth) = (上軌 - 下軌) / 中心線
    df['BandWidth'] = (df['BB_up'] - df['BB_low']) / df['MA20']
    
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
            is_cheap = curr['Close'] <= curr['TL-1SD']
            tech_strong = (
                (prev['RSI14'] < 30 and curr['RSI14'] > 30) or       
                (prev['MACD'] < prev['Signal'] and curr['MACD'] > curr['Signal']) or 
                (prev['Close'] < curr['MA60'] and curr['Close'] > curr['MA60'])      
            )
            
            # --- 賣出訊號條件 ---
            is_expensive = curr['Close'] >= curr['TL+1SD']
            tech_weak = (
                (prev['RSI14'] > 70 and curr['RSI14'] < 70) or       
                (prev['MACD'] > prev['Signal'] and curr['MACD'] < curr['Signal'])    
            )

            if is_cheap and tech_strong:
                alerts.append({"name": name, "type": "BUY", "reason": "位階偏低 + 技術面轉強"})
            elif is_expensive and tech_weak:
                alerts.append({"name": name, "type": "SELL", "reason": "位階偏高 + 技術面轉弱"})
                
    return alerts

def calc_resonance_score(df):
    score = 0
    curr = df.iloc[-1]

    if curr['Close'] < curr['TL-2SD']:
        score += 40
    elif curr['Close'] < curr['TL-1SD']:
        score += 30
    elif curr['Close'] < curr['TL']:
        score += 20
    elif curr['Close'] < curr['TL+1SD']:
        score += 10

    ma_periods = df.attrs.get('ma_periods', [])
    if ma_periods:
        ma_mid = df[f'MA{ma_periods[len(ma_periods)//2]}'].iloc[-1]
        if curr['Close'] > ma_mid:
            score += 30
        elif abs(curr['Close'] - ma_mid) / ma_mid < 0.01:
            score += 15

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

    if curr['Close'] < curr['TL-2SD']:
        score += 40
    elif curr['Close'] < curr['TL-1SD']:
        score += 30
    elif curr['Close'] < curr['TL']:
        score += 20
    elif curr['Close'] < curr['TL+1SD']:
        score += 10

    ma_periods = df.attrs.get('ma_periods', [])
    if len(ma_periods) >= 3:
        ma_short = df[f'MA{ma_periods[0]}'].iloc[-1]
        ma_mid   = df[f'MA{ma_periods[len(ma_periods)//2]}'].iloc[-1]
        ma_long  = df[f'MA{ma_periods[-1]}'].iloc[-1]
    
        if ma_short > ma_mid > ma_long:
            score += 20
        elif ma_short > ma_mid:
            score += 10

        if curr['Close'] > ma_mid:
            score += 10
        elif abs(curr['Close'] - ma_mid) / ma_mid < 0.01:
            score += 5

    macd = curr['MACD']
    signal = curr['Signal']
    macd_diff = macd - signal
    
    if macd_diff > 0 and macd > 0:
        score += min(30, 20 + macd_diff * 50)
    elif macd_diff > 0:
        score += min(20, 10 + macd_diff * 30)
    elif macd > 0:
        score += 5

    if curr['Close'] > curr['TL+1SD'] and macd_diff < 0:
        score -= 15
    
    if curr['Close'] < ma_long:
        score -= 10

    return max(0, min(score, 100))

def detect_market_pattern(df, slope):
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    patterns = []
    W = 20
    window = df.iloc[-W:]

    x = np.arange(W)
    price_slope = np.polyfit(x, window['Close'], 1)[0]
    price_curve = np.polyfit(x, window['Close'], 2)[0]
    higher_lows = window['Low'].iloc[-5:].min() > window['Low'].iloc[:5].min()
    
    rsi_slope = np.polyfit(x, window['RSI14'], 1)[0]
    macd_slope = np.polyfit(x, window['MACD'], 1)[0]
    
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

    if (
        close.iloc[-20:].min() < df['TL-1SD'].iloc[-1] and
        close.iloc[-5:].mean() > close.iloc[-15:-5].mean() and
        df['RSI14'].iloc[-5:].mean() > df['RSI14'].iloc[-15:-5].mean() and
        -0.02 < price_slope < 0.05
    ):
        patterns.append("🟢 結構性底部（區間）")

    lookback = 50
    sub_df = df.iloc[-lookback:]
    first_min_idx = sub_df['Close'].idxmin()
    first_bottom_price = df.loc[first_min_idx, 'Close']

    right_df = df.loc[first_min_idx:].iloc[10:]
    if len(right_df) > 10:
        second_min_idx = right_df['Close'].idxmin()
        second_bottom_price = df.loc[second_min_idx, 'Close']
    
        if second_bottom_price > first_bottom_price * 0.98:
            post_prices = df.loc[second_min_idx:].iloc[:5]['Close'].values
            if len(post_prices) > 5:
                x = np.arange(5)
                slope_post, _, _, _, _ = stats.linregress(x, post_prices)
                if (
                    slope_post > 0 and
                    curr['Close'] > second_bottom_price and
                    curr['Close'] < curr['TL']
                ):
                    patterns.append("🟢 雙底確認（區間）")

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

    if ma_periods:
        ma_s = df[f"MA{ma_periods[0]}"].iloc[-10:].mean()
        ma_l = df[f"MA{ma_periods[2]}"].iloc[-10:].mean()
        if abs(ma_s - ma_l) / ma_l < 0.01:
            patterns.append("🟡 均線糾結（區間）")

    lookback = 50
    sub_df = df.iloc[-lookback:]
    min_idx = sub_df['Close'].idxmin()
    bottom_price = df.loc[min_idx, 'Close']
    
    left_prices = df.loc[:min_idx].iloc[-5:]['Close'].values
    right_prices = df.loc[min_idx:].iloc[:5]['Close'].values

    if len(left_prices) == 5 and len(right_prices) == 5:
        x = np.arange(5)
        slope_left, _, _, _, _ = stats.linregress(x, left_prices)
        slope_right, _, _, _, _ = stats.linregress(x, right_prices)

        recent_prices = df['Close'].iloc[-10:]
        range_ratio = (recent_prices.max() - recent_prices.min()) / recent_prices.mean()

        if (
            slope_left < 0 and                 
            slope_right > 0 and                
            range_ratio <= 0.05 and             
            rsi_slope > 0 and                   
            curr['Close'] < curr['TL'] and      
            curr['Close'] > bottom_price * 1.05         
        ):
            patterns.append("🟢 碗型底（區間）")

    if (
        abs(price_slope) < 0.01 and
        range_shrink and
        45 < curr['RSI14'] < 55
    ):
        patterns.append("⚪ 區間盤整（區間）")

    if (
        df['High'].iloc[-50:].max() - df['Low'].iloc[-50:].min()
        < 1.5 * (curr['TL+1SD'] - curr['TL'])
    ):
        patterns.append("⚪ 箱型整理（區間）")

    if (
        price_slope <= 0 and
        price_curve < 0 and
        macd_slope < 0 and
        curr['Close'] > curr['TL+1SD']
    ):
        patterns.append("🔴 頭部形成（區間）")

    tri_window = 15
    hs = high.iloc[-tri_window:]
    ls = low.iloc[-tri_window:]

    h_slope = np.polyfit(range(tri_window), hs, 1)[0]
    l_slope = np.polyfit(range(tri_window), ls, 1)[0]

    if h_slope < 0 and l_slope > 0:
        patterns.append("⚪ 三角收斂（區間）")

    if ma_periods:
        ma_mid = df[f"MA{ma_periods[len(ma_periods)//2]}"]
        if (
            close.iloc[-5:].mean() < ma_mid.iloc[-5:].mean() and
            slope < 0
        ):
            patterns.append("🔴 跌破關鍵均線（區間）")

    if (
        curr['Close'] > prev['Close'] and
        curr['RSI14'] < prev['RSI14'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 趨勢末端（動能衰竭）")

    lookback = 10
    sub_df = df.iloc[-lookback:]
    min_idx = sub_df['Close'].idxmin()
    bottom_price = df.loc[min_idx, 'Close']
    
    left_prices = df.loc[:min_idx].iloc[-3:]['Close'].values
    right_prices = df.loc[min_idx:].iloc[:3]['Close'].values

    if len(left_prices) == 3 and len(right_prices) == 3:
        x = np.arange(3)
        slope_left, _, _, _, _ = stats.linregress(x, left_prices)
        slope_right, _, _, _, _ = stats.linregress(x, right_prices)

        if (
            slope_left < 0 and                 
            slope_right > 0 and                
            rsi_slope > 0 and                   
            curr['Close'] > bottom_price * 1.1         
        ):
            patterns.append("🟢 V 型反轉")

    if (
        abs(curr['Close'] - df['Close'].iloc[-6]) / df['Close'].iloc[-6] < 0.02 and
        curr['RSI14'] > df['RSI14'].iloc[-6] 
    ):
        patterns.append("🟢 雙底確認")

    if (
        df['Close'].iloc[-6] > curr['TL+1SD'] and
        curr['Close'] > curr['TL'] and
        curr['RSI14'] > 50
    ):
        patterns.append("🟡 多頭旗形（續行）")

    if (
        prev['Close'] > curr['TL+1SD'] and
        curr['Close'] < curr['TL'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 假突破")

    if (
        curr['RANGE_N'] <
        df['RANGE_N'].rolling(50).quantile(0.2).iloc[-1]
    ):
        patterns.append("⚪ 波動擠壓（即將爆發）")

    if (
        curr['RANGE_N'] < curr['RANGE_N_prev'] and
        abs(curr['Close'] - curr['TL']) / curr['TL'] < 0.01 and
        abs(curr['MACD']) < abs(prev['MACD'])
    ):
        patterns.append("⚪ 財訊盤整收斂")

    if (
        curr['RANGE_N'] < df['RANGE_N'].iloc[-2] and
        df['RANGE_N'].iloc[-2] < df['RANGE_N'].iloc[-3] and
        45 < curr['RSI14'] < 55
    ):
        patterns.append("🟡 三角收斂（突破前）")

    if (
        curr['Close'] > df['Close'].iloc[-11:-1].max() and
        df['RANGE_N'].iloc[-2] < df['RANGE_N'].iloc[-3] and
        curr['MACD'] > curr['Signal'] and
        curr['RSI14'] > 55
    ):
        patterns.append("🟡 盤整後上突破（起漲型）")

    if (
        curr['Close'] < curr['TL-1SD'] and
        curr['RSI7'] > prev['RSI7'] and
        curr['MACD'] > prev['MACD']
    ):
        patterns.append("🟢 結構性底部")

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

    if (
        curr['Close'] > curr['TL+2SD'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 過熱風險")
        
    if curr['Close'] < curr['TL-1SD'] and slope < 0 and curr['Close'] > curr['TL-2SD']:
        patterns.append("🔴 弱勢趨勢延續")

    if curr['RSI14'] < 20 and curr['Close'] < curr['TL-2SD']:
        patterns.append("🟢 超跌反彈觀察")

    if (
        curr['Close'] < prev['Close'] and
        curr['RSI14'] > prev['RSI14'] and
        curr['MACD'] > prev['MACD'] and
        curr['Close'] < curr['TL-1SD']
    ):
        patterns.append("🟢 底部背離（潛在反轉）")

    if ma_periods:
        ma_short = df[f"MA{ma_periods[0]}"]
        ma_long = df[f"MA{ma_periods[2]}"]
        if (
            abs(ma_short.iloc[-1] - ma_long.iloc[-1]) / ma_long.iloc[-1] < 0.01 and
            curr['Close'] > ma_short.iloc[-1] and
            curr['MACD'] > curr['Signal']
        ):
            patterns.append("🟡 均線糾結突破")

    if (
        curr['Close'] > curr['TL+1SD'] and
        curr['RSI14'] < prev['RSI14'] and
        curr['MACD'] < prev['MACD']
    ):
        patterns.append("🔴 多頭趨勢疲勞")

    if ma_periods:
        ma_mid = df[f"MA{ma_periods[len(ma_periods)//2]}"]
        if (
            prev['Close'] > ma_mid.iloc[-2] and
            curr['Close'] < ma_mid.iloc[-1] and
            slope < 0
        ):
            patterns.append("🔴 跌破關鍵均線")

    if (
        abs(curr['Close'] - curr['TL']) / curr['TL'] < 0.01 and
        abs(curr['RSI14'] - 50) < 5 and
        abs(curr['MACD']) < abs(prev['MACD'])
    ):
        patterns.append("⚪ 盤整收斂")

    vol_today = df['Volume'].iloc[-1]
    vol_prev = df['Volume'].iloc[-2]
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

    for pat in patterns:
        if pat not in result:
            result.append(pat)

    return result

def update_pattern_history(ticker, patterns):
    if "pattern_history" not in st.session_state:
        st.session_state.pattern_history = {}

    hist = patterns
    st.session_state.pattern_history[ticker] = hist
    return " | ".join(hist) if hist else ""

def get_intraday_price(ticker):
    try:
        df_i = yf.Ticker(ticker).history(
            period="1d",
            interval="1m"
        )
        if df_i.empty:
            return None

        last = df_i.iloc[-1]

        return {
            "open": float(df_i.iloc[0]["Open"]),
            "high": float(df_i["High"].max()),
            "low": float(df_i["Low"].min()),
            "close": float(last["Close"]),
            "volume": float(df_i["Volume"].sum())
        }
    except:
        return None
        
@st.cache_data(ttl=3600)
def get_full_stock_data(ticker_str):
    try:
        time.sleep(random.uniform(0.5, 1.5))
        stock = yf.Ticker(ticker_str)
        
        raw_info = dict(stock.info)
        shares = raw_info.get("sharesOutstanding")
        if not shares:
            try:
                shares = stock.fast_info.shares_outstanding
            except:
                shares = None

        df_inc = stock.financials
        df_q_inc = stock.quarterly_financials

        return {
            "info": raw_info,
            "shares": shares,
            "df_inc": df_inc if df_inc is not None else pd.DataFrame(),
            "df_q_inc": df_q_inc if df_q_inc is not None else pd.DataFrame(),
            "pe": raw_info.get("trailingPE"),
            "peg": raw_info.get("pegRatio"),
            "ps": raw_info.get("priceToSalesTrailing12Months"),
            "ins_held": raw_info.get("heldPercentInstitutions"),
            "short_ratio": raw_info.get("shortPercentOfFloat"),
            "net_margin": raw_info.get("netProfitMargins"),
        }
    except Exception as e:
        return None

def calc_fundamental_score_safe(info):
    if not info: return 0
    score = 0
    metrics = {
        "roe": info.get("returnOnEquity", 0) * 100 if info.get("returnOnEquity") else 0,
        "roa": info.get("returnOnAssets", 0) * 100 if info.get("returnOnAssets") else 0,
        "gm": info.get("grossMargins", 0) * 100 if info.get("grossMargins") else 0,
        "om": info.get("operatingMargins", 0) * 100 if info.get("operatingMargins") else 0,
        "debt": info.get("debtToEquity", 100) if info.get("debtToEquity") else 100,
        "rev_g": info.get("revenueGrowth", 0) * 100 if info.get("revenueGrowth") else 0,
        "eps_g": info.get("earningsQuarterlyGrowth", 0) * 100 if info.get("earningsQuarterlyGrowth") else 0,
    }
    
    score += 20 if metrics["roe"] > 20 else (10 if metrics["roe"] > 10 else 0)
    score += 10 if metrics["roa"] > 10 else (5 if metrics["roa"] > 5 else 0)
    score += 10 if metrics["gm"] > 50 else (5 if metrics["gm"] > 30 else 0)
    score += 10 if metrics["om"] > 30 else (5 if metrics["om"] > 15 else 0)
    score += 10 if metrics["debt"] < 50 else (5 if metrics["debt"] < 100 else 0)
    score += 10 if metrics["rev_g"] > 15 else (5 if metrics["rev_g"] > 5 else 0)
    score += 10 if metrics["eps_g"] > 15 else (5 if metrics["eps_g"] > 5 else 0)
    
    fcf = info.get("freeCashflow")
    m_cap = info.get("marketCap")
    if fcf and m_cap:
        f_yield = (fcf / m_cap) * 100
        score += 10 if f_yield > 5 else (5 if f_yield > 2 else 0)
        
    return score

def calc_eps_cagr_safe(df_inc, shares, years=3):
    try:
        if df_inc is None or df_inc.empty or not shares: return None
        net_inc = df_inc.loc["Net Income"]
        eps = (net_inc / shares)[::-1]
        if len(eps) < years + 1: return None
        start, end = eps.iloc[-(years+1)], eps.iloc[-1]
        if start <= 0: return None
        return ((end / start) ** (1 / years) - 1) * 100
    except: return None

def get_latest_eps_safe(df_inc, df_q_inc, shares):
    try:
        if not shares: return None, None, None, None, None
        ann_eps = (df_inc.loc["Net Income"].iloc[0] / shares) if not df_inc.empty else None
        ann_year = df_inc.columns[0].year if not df_inc.empty else None
        q_eps = (df_q_inc.loc["Net Income"].iloc[0] / shares) if not df_q_inc.empty else None
        q_date = df_q_inc.columns[0] if not df_q_inc.empty else None
        q_year, q_num = (q_date.year, (q_date.month - 1) // 3 + 1) if q_date else (None, None)
        return ann_eps, ann_year, q_eps, q_year, q_num
    except: return None, None, None, None, None

# --- 4. 側邊欄 ---
with st.sidebar:
    st.header("📋 追蹤清單")
    
    sorted_tickers = sorted(st.session_state.watchlist_dict.keys())
    display_options = [
        f"{t} - {st.session_state.watchlist_dict[t]}" for t in sorted_tickers
    ]
    
    selected_full_text = st.selectbox(
        "我的收藏", 
        options=["-- 手動輸入 --"] + display_options
    )
    
    st.divider()
    st.header("⚙️ 搜尋設定")
    
    if selected_full_text != "-- 手動輸入 --":
        quick_pick_ticker = selected_full_text.split(" - ")[0]
    else:
        quick_pick_ticker = ""

    ticker_input = st.text_input(
        "股票代號", 
        value=quick_pick_ticker
    ).upper().strip()
    
    stock_name = st.session_state.watchlist_dict.get(ticker_input, "")
   
    st.divider()
    st.header("📊 顯示設定")
    time_frame = st.selectbox(
        "時間週期 (K線頻率)",
        options=["日", "週", "月"],
        index=0
    )
    years_input = st.slider("回測年數", 1.0, 10.0, 3.5, 0.5)
   
    use_k_now = st.sidebar.toggle(
        "啟用及時股價",
        value=True
    )
    if use_k_now:
        st.cache_data.clear()
    else:
        st.cache_data.clear()

    use_adjusted_price = st.sidebar.toggle(
        "使用還原股價",
        value=False,
        help="開啟：適合長期趨勢；關閉：適合短線、實際成交價"
    )
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
    
    show_all_signals = st.sidebar.toggle(
        "顯示全部訊號",
        value=True
    )
    
    show_weak_signal = st.sidebar.toggle(
        "顯示【弱】訊號",
        value=False,
        disabled=not show_all_signals
    )
    if not show_all_signals:
        st.cache_data.clear()
        buy_levels_to_show  = []
        sell_levels_to_show = []
    else:
        if show_weak_signal:
            st.cache_data.clear()
            buy_levels_to_show  = ['弱', '中', '強']
            sell_levels_to_show = ['弱', '中', '強']
        else:
            st.cache_data.clear()
            buy_levels_to_show  = ['中', '強']
            sell_levels_to_show = ['中', '強']

    if st.button("🔄 重新取價"):
        st.cache_data.clear()

    st.divider()
    if st.button("🚪 登出帳號"):
        st.cache_data.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- 5. 核心運算 ---
@st.cache_data(ttl=3600)  
def get_stock_data(ticker, years, time_frame="日", use_adjusted_price=False):
    try:
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))

        df = yf.download(
            ticker,
            start=start,
            end=end,
            interval="1d",
            progress=False,
            auto_adjust=auto_adjust,
            actions=actions,
            repair=repair
        )

        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        intraday = get_intraday_price(ticker)

        if not use_k_now:
            pass
        else:                    
            if intraday is not None:
                now = datetime.now()
                today_date = pd.Timestamp(now.date())
                is_weekday = now.weekday() < 5
                has_volume = intraday["volume"] > 0
            
                if is_weekday and has_volume:
                    if today_date in df.index:
                        df.loc[today_date, ["Open", "High", "Low", "Close", "Volume"]] = [
                            intraday["open"],
                            intraday["high"],
                            intraday["low"],
                            intraday["close"],
                            intraday["volume"]
                        ]
                    else:
                        new_row = pd.DataFrame(
                            {
                                "Open":   intraday["open"],
                                "High":   intraday["high"],
                                "Low":    intraday["low"],
                                "Close":  intraday["close"],
                                "Volume": intraday["volume"]
                            },
                            index=[today_date]
                        )
                        df = pd.concat([df, new_row])
                
        if time_frame == "週":
            df = df.resample(
                'W-FRI',
                label='right',     
                closed='right'     
            ).agg({
                'Open': 'first',   
                'High': 'max',     
                'Low': 'min',      
                'Close': 'last',   
                'Volume': 'sum'    
            }).dropna()

        elif time_frame == "月":
            df = df.resample(
                'ME',
                label='right',     
                closed='right'     
            ).agg({
                'Open': 'first',   
                'High': 'max',     
                'Low': 'min',      
                'Close': 'last',   
                'Volume': 'sum'    
            }).dropna()

        if time_frame == "日":
            ma_periods = [5, 10, 20, 60, 120]
        elif time_frame == "週":
            ma_periods = [4, 13, 26, 52, 104]
        elif time_frame == "月":
            ma_periods = [3, 6, 12, 24, 48, 96]

        for p in ma_periods:
            df[f'MA{p}'] = df['Close'].rolling(window=p).mean() 
            df[f'MA{p}_slope'] = df[f'MA{p}'].diff()

        df.attrs['ma_periods'] = ma_periods
        
        if time_frame == "日":
            fast_ma, slow_ma, trend_ma = 10, 20, 60
        elif time_frame == "週":
            fast_ma, slow_ma, trend_ma = 13, 26, 52
        elif time_frame == "月":
            fast_ma, slow_ma, trend_ma = 6, 12, 24

        rsi_periods = [7, 14]
        for p in rsi_periods:
            df[f'R-RSI{p}'] = calc_rsi(df['Close'], p)
        
        df.attrs['rsi_periods'] = rsi_periods
        
        Klow_9 = df['Low'].rolling(9).min()
        Khigh_9 = df['High'].rolling(9).max()
        Krsv = 100 * (df['Close'] - Klow_9) / (Khigh_9 - Klow_9)
        df['KK'] = Krsv.ewm(com=2).mean()
        df['KD'] = df['KK'].ewm(com=2).mean()
        
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['M-MACD'] = exp1 - exp2
        df['M-Signal'] = df['M-MACD'].ewm(span=9, adjust=False).mean()
        
        df['buy_signal'] = (
            ((df['Close'] > df[f'MA{trend_ma}']) &
            (df['Close'] > df[f'MA{fast_ma}']) &
            (df['Close'].shift(1) <= df[f'MA{fast_ma}'].shift(1)) &
            (df['Close'] > df[f'MA{slow_ma}']) &
            (df[f'MA{fast_ma}_slope'] > 0) &
            (df[f'MA{fast_ma}_slope'].shift(1) > 0) &
            (df[f'MA{slow_ma}_slope'] > 0) &
            (df['Close'] > df['Open']) &
            (df['Close'].shift(1) < df['Open'].shift(1))) |
            ((df['M-MACD'] > df['M-Signal']) & (df['M-MACD'].shift(1) <= df['M-Signal'].shift(1))) |
            ((df['KK'] > df['KD']) & (df['KK'].shift(1) <= df['KD'].shift(1)) & (df['KK'].shift(1) < 20 ))
        )
        
        df['sell_signal'] = (
            ((df['Close'] < df[f'MA{trend_ma}']) &
            (df['Close'] < df[f'MA{fast_ma}']) &
            (df['Close'].shift(1) >= df[f'MA{fast_ma}'].shift(1)) &
            (df['Close'] < df[f'MA{slow_ma}']) &
            (df[f'MA{fast_ma}_slope'] < 0) &
            (df[f'MA{fast_ma}_slope'].shift(1) < 0) &
            (df[f'MA{slow_ma}_slope'] < 0) &
            (df['Close'] < df['Open']) &
            (df['Close'].shift(1) > df['Open'].shift(1))) |
            ((df['M-MACD'] < df['M-Signal']) & (df['M-MACD'].shift(1) >= df['M-Signal'].shift(1))) |
            ((df['KK'] < df['KD']) & (df['KK'].shift(1) >= df['KD'].shift(1)) & (df['KK'].shift(1) > 60 ))
        )

        df['buy_score'] = 0
        df.loc[
            (df['Close'] > df[f'MA{trend_ma}']) &
            (df[f'MA{fast_ma}'] > df[f'MA{slow_ma}']) &
            (df[f'MA{slow_ma}'] > df[f'MA{trend_ma}']),
            'buy_score'
        ] += 3
        df.loc[
            (df[f'MA{fast_ma}_slope'] > 0) &
            (df[f'MA{fast_ma}_slope'].shift(1) > 0),
            'buy_score'
        ] += 1
        df.loc[
            (df['M-MACD'] > df['M-Signal']) &
            (df['M-MACD'].shift(1) <= df['M-Signal'].shift(1)),
            'buy_score'
        ] += 1
        df.loc[
            (df['KK'] > df['KD']) & 
            (df['KK'].shift(1) <= df['KD'].shift(1)),
            'buy_score'
        ] += 1
        df.loc[
            (df['Close'] > df['Open']) &
            ((df['Close'] - df['Open']) > 0.5 * (df['High'] - df['Low'])),
            'buy_score'
        ] += 1

        df['sell_score'] = 0
        df.loc[
            (df['Close'] < df[f'MA{trend_ma}']) &
            (df[f'MA{fast_ma}'] < df[f'MA{slow_ma}']) &
            (df[f'MA{slow_ma}'] < df[f'MA{trend_ma}']),
            'sell_score'
        ] += 3
        df.loc[
            (df[f'MA{fast_ma}_slope'] < 0) &
            (df[f'MA{fast_ma}_slope'].shift(1) < 0),
            'sell_score'
        ] += 1
        df.loc[
            (df['M-MACD'] < df['M-Signal']) &
            (df['M-MACD'].shift(1) >= df['M-Signal'].shift(1)),
            'sell_score'
        ] += 1
        df.loc[
            (df['KK'] < df['KD']) & 
            (df['KK'].shift(1) >= df['KD'].shift(1)),
            'sell_score'
        ] += 1
        df.loc[
            (df['Close'] < df['Open']) &
            ((df['Open'] - df['Close']) > 0.5 * (df['High'] - df['Low'])),
            'sell_score'
        ] += 1

        df['buy_level'] = pd.cut(
            df['buy_score'],
            bins=[-1, 2, 4, 7],
            labels=['弱', '中', '強']
        )
        df['sell_level'] = pd.cut(
            df['sell_score'],
            bins=[-1, 2, 4, 7],
            labels=['弱', '中', '強']
        )

        df = df.reset_index()
        df.rename(columns={df.columns[0]: "Date"}, inplace=True)
        df['x'] = np.arange(len(df))
        
        x = df['x'].values
        y = df['Close'].values

        if time_frame == "週":
            w = np.linspace(0.3, 1.0, len(x)) ** 2
            slope, intercept = np.polyfit(x, y, 1, w=w)
            y_hat = slope * x + intercept
            r_squared = 1 - np.sum(w * (y - y_hat)**2) / np.sum(w * (y - np.average(y, weights=w))**2)
        else:
            slope, intercept, r_value, _, _ = stats.linregress(x, y)
            r_squared = r_value ** 2

        df['TL'] = slope * x + intercept

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

        # 加入技術指標計算 (含 BIAS、MA20、BB_up、BB_low、BandWidth)
        df = get_technical_indicators(df)        
        
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = 100 * (df['Close'] - low_9) / (high_9 - low_9)
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()

        if time_frame == "日":
            h_window = 100      
            band_pct = 0.10
        elif time_frame == "週":
            h_window = 52       
            band_pct = 0.15
        elif time_frame == "月":
            h_window = 24       
            band_pct = 0.20
        
        df['H_TL'] = df['Close'].rolling(window=h_window, min_periods=h_window//2).mean()
        df['H_TL+1SD'] = df['H_TL'] * (1 + band_pct)
        df['H_TL-1SD'] = df['H_TL'] * (1 - band_pct)

        df['dP'] = df['Close'].diff()
        df['ddP'] = df['dP'].diff()
        
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
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), 2)
        else:
            return "無資料"
    except Exception as e:
            print(f"Error: {e}")
            return 0.0

# --- 6. 介面形式恢復 ---
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown(f'#  {ticker_input} ({stock_name})', unsafe_allow_html=True, help="若無法顯示資料，請按🔄重新取價")

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

    patterns = detect_market_pattern(df, slope)
    if patterns:
        st.markdown("### 🧠 AI 市場型態判讀")
        for p in patterns:
            st.write(p)
    
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

    if len(df) >= 2:
        today_close = df["Close"].iloc[-1]
        yesterday_close = df["Close"].iloc[-2]
        change_pct = (today_close - yesterday_close) / yesterday_close * 100
    else:
        change_pct = 0

    last_buy  = bool(df['buy_signal'].iloc[-1])
    last_sell = bool(df['sell_signal'].iloc[-1])
    icon = "—"

    if last_buy:
        lvl = str(df['buy_level'].iloc[-1])
        icon = f"▲ {lvl}"
    elif last_sell:
        lvl = str(df['sell_level'].iloc[-1])
        icon = f"▼ {lvl}"

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("最新股價", f"{curr:.2f}",f"{change_pct:+.2f}%", delta_color="inverse")
    m2.metric("趨勢中心 (TL)", f"{tl_last:.2f}", f"{dist_pct:+.2f}%", delta_color="inverse")
    m3.metric("目前狀態", status_label)
    m4.metric("K線訊號", icon)
    m5.metric("趨勢斜率", f"{slope:.2f}", help="正值代表長期趨勢向上")
    m6.metric("VIX 恐慌指數", f"{vix_val:.2f}", vix_status, delta_color="off", help="超過60代表極度恐慌")

    # --- 7. 切換按鈕 ---
    st.divider()
    show_detailed_metrics = st.toggle("顯示詳細指標", value=False)
    
    if show_detailed_metrics:
        with st.spinner('🔍 深度掃描中...'):
            data_pack = get_full_stock_data(ticker_input)
        
        if data_pack:
            info = data_pack['info']
            shares = data_pack['shares']
         
            f_score = calc_fundamental_score_safe(info)
            cagr_3y = calc_eps_cagr_safe(data_pack['df_inc'], shares, 3)
            ann_eps, ann_y, q_eps, q_y, q_n = get_latest_eps_safe(
                data_pack['df_inc'], 
                data_pack['df_q_inc'], 
                shares
            )
            
            st.markdown("### 📈 技術面")
            t_row = st.columns(6)
            
            c_rsi = df['RSI14'].iloc[-1]
            rsi_status = "🔥 超買" if c_rsi > 70 else ("❄️ 超跌" if c_rsi < 30 else "⚖️ 中性")
            t_row[0].metric("RSI (14)", f"{c_rsi:.1f}", rsi_status, delta_color="off")
    
            macd_delta = df['MACD'].iloc[-1] - df['Signal'].iloc[-1]
            t_row[1].metric("MACD 趨勢", f"{df['MACD'].iloc[-1]:.2f}", "📈 金叉" if macd_delta > 0 else "📉 死叉", delta_color="off")
            
            c_bias = df['BIAS'].iloc[-1]
            t_row[2].metric("月線乖離 (BIAS)", f"{c_bias:+.2f}%", "⚠️ 乖離大" if abs(c_bias) > 5 else "✅ 穩定", delta_color="off")
            
            curr_p = df['Close'].iloc[-1]
            ma60_last = df['MA60'].iloc[-1]
            t_row[3].metric("季線支撐 (MA60)", f"{ma60_last:.1f}", "🚀 站上季線" if curr_p > ma60_last else "🩸 跌破季線", delta_color="off")
            
            r2_status = "🎯 趨勢極準" if r_squared > 0.8 else ("✅ 具參考性" if r_squared > 0.5 else "❓ 參考性低")
            t_row[4].metric("決定係數 (R²)", f"{r_squared:.2f}", r2_status, delta_color="off",help="數值越接近 1，代表五線譜趨勢線對股價的解釋力越強")
            
            res_score = calc_resonance_score(df)
            res_label = (
                "🟢 強烈偏多" if res_score >= 80 else
                "🟡 偏多" if res_score >= 60 else
                "⚪ 中性" if res_score >= 40 else
                "🟠 偏弱" if res_score >= 20 else
                "🔴 高風險"
            )
            t_row[5].metric("多指標共振分數", f"{res_score}/100", res_label, delta_color="off")
            
            st.write("")
            st.markdown("### 📊 基本面")
            f1 = st.columns(6)
            f2 = st.columns(6)
    
            f1[0].metric("ROE", f"{info.get('returnOnEquity',0)*100:.2f}%" if info.get('returnOnEquity') else "N/A",help="股東權益報酬率")
            f1[1].metric("ROA", f"{info.get('returnOnAssets',0)*100:.2f}%" if info.get('returnOnAssets') else "N/A",help="資產報酬率")
            f1[2].metric("毛利率", f"{info.get('grossMargins',0)*100:.2f}%" if info.get('grossMargins') else "N/A")
            f1[3].metric("營益率", f"{info.get('operatingMargins',0)*100:.2f}%" if info.get('operatingMargins') else "N/A")
            f1[4].metric("負債比", f"{info.get('debtToEquity',0):.2f}%" if info.get('debtToEquity') else "N/A")
            
            f_label = (
                "🟢 優質公司" if f_score >= 80 else
                "🟡 穩健公司" if f_score >= 60 else
                "⚪ 普通公司" if f_score >= 40 else
                "🟠 偏弱公司" if f_score >= 20 else
                "🔴 高風險"
            )
            f1[5].metric("基本面評級", f"{f_score}/100", f_label)
    
            f2[0].metric("EPS 成長率", f"{info.get('earningsQuarterlyGrowth',0)*100:.2f}%" if info.get('earningsQuarterlyGrowth') else "N/A")
            f2[1].metric("營收成長率", f"{info.get('revenueGrowth',0)*100:.2f}%" if info.get('revenueGrowth') else "N/A")
            
            fcf_y = (info.get('freeCashflow',0)/info.get('marketCap',1)*100) if info.get('freeCashflow') else None
            f2[2].metric("FCF Yield", f"{fcf_y:.2f}%" if fcf_y else "N/A",help="自由現金流殖利率")
            f2[3].metric("EPS 3Y CAGR", f"{cagr_3y:.2f}%" if cagr_3y else "N/A",help="3年EPS複合年成長率")
            f2[4].metric(f"{q_y} Q{q_n} EPS", f"{q_eps:.2f}" if q_eps else "N/A")
            f2[5].metric(f"{ann_y}年度EPS", f"{ann_eps:.2f}" if ann_eps else "N/A")  
            
            st.write("")
            st.markdown("### 💎 核心估值與籌碼面")
            v_row = st.columns(6)
    
            pe = data_pack.get("pe")
            pe_text = f"{pe:.2f}" if pe else "N/A"
            v_row[0].metric("本益比 (PE)", pe_text)
    
            peg = data_pack.get("peg")
            peg_status = "✅ 便宜" if peg and peg < 1 else ("⚠️ 偏貴" if peg and peg > 2 else None)
            v_row[1].metric("本益成長比 (PEG)", f"{peg:.2f}" if peg else "N/A", peg_status, help="PEG < 1 通常代表股價相對於成長性較便宜")
    
            ps = data_pack.get("ps")
            v_row[2].metric("股價營收比 (PS)", f"{ps:.2f}" if ps else "N/A",help="通常 P/S 低於0.75具吸引力，高於1.5需避開，高於3可能被高估")
    
            nm = data_pack.get("net_margin")
            v_row[3].metric("淨利率 (NM)", f"{nm*100:.2f}%" if nm else "N/A")
    
            ins = data_pack.get("ins_held")
            v_row[4].metric("法人持股比例", f"{ins*100:.1f}%" if ins else "N/A", help="比例越高，代表受大資金青睞")
    
            sr = data_pack.get("short_ratio")
            sr_status = "🔥 易軋空" if sr and sr > 0.1 else None 
            v_row[5].metric("空單餘額比", f"{sr*100:.1f}%" if sr else "N/A", sr_status, help="空單比例過高時，若利多出現易引發軋空行情")
        st.write("")
    
    view_mode = st.radio("分析視圖", ["樂活五線譜", "樂活通道", "K線指標", "KD指標", "布林通道", "成交量"], horizontal=True, label_visibility="collapsed")

    col_sub1, col_sub2 = st.columns([1, 4])
    with col_sub1: show_sub_chart = st.toggle("開啟副圖", value=False)
    # 修改：在副圖選單中加入 BandWidth 指標
    with col_sub2: sub_mode = st.selectbox("選擇副圖指標", ["KD指標", "成交量", "RSI", "MACD", "BandWidth"], label_visibility="collapsed")

    # --- 8. 繪圖核心 ---
    if show_sub_chart:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    else:
        fig = go.Figure()
    
    if view_mode == "樂活五線譜":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#F08C8C', width=2), name="收盤價", hovertemplate='%{y:.1f}'))
        for col, hex_color, name_tag, line_style in lines_config:
            fig.add_trace(go.Scatter(x=df['Date'], y=df[col], line=dict(color=hex_color, dash=line_style, width=1.5), name=name_tag, hovertemplate='%{y:.1f}'))
            last_val = df[col].iloc[-1]
            fig.add_annotation(x=df['Date'].iloc[-1], y=last_val, text=f"<b>{last_val:.1f}</b>", showarrow=False, xanchor="left", xshift=10, font=dict(color=hex_color, size=13))

    elif view_mode == "樂活通道":
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='#F08C8C', width=2), name="收盤價", hovertemplate='%{y:.1f}'))
        
        h_lines_config = [ 
            ('H_TL+1SD', '#FFBD03', '通道上軌', 'dash'), 
            ('H_TL', '#FFFFFF', '趨勢中軸', 'solid'), 
            ('H_TL-1SD', '#0096FF', '通道下軌', 'dash'), 
        ]
        
        for col, hex_color, name_tag, line_style in h_lines_config:
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df['Date'], y=df[col], 
                    line=dict(color=hex_color, dash=line_style, width=1.5), 
                    name=name_tag,
                    hovertemplate='%{y:.1f}'
                ))
                
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
        fig.add_trace(go.Candlestick(
            x=df['Date'],
            open=df['Open'].apply(lambda x: round(x, 1)), 
            high=df['High'].apply(lambda x: round(x, 1)),
            low=df['Low'].apply(lambda x: round(x, 1)), 
            close=df['Close'].apply(lambda x: round(x, 1)),
            name="",
            increasing_line_color='#FF3131', 
            decreasing_line_color='#00FF00'  
        ))
        fig.add_trace(
            go.Scatter(
                x=df['Date'],
                y=df['Close'],
                mode='markers',
                marker=dict(
                    size=40,
                    color='rgba(0,0,0,0)',
                ),
                hovertemplate='<extra></extra>',
                showlegend=False
            )
        )
        offset = (df['High'] - df['Low']).mean() * 0.3
        
        df['buy_y']  = df['Low']  - offset
        df['sell_y'] = df['High'] + offset
        
        buy_plot_df = df[
            (df['buy_signal']) &
            (df['buy_level'].isin(buy_levels_to_show))
        ]
        
        sell_plot_df = df[
            (df['sell_signal']) &
            (df['sell_level'].isin(sell_levels_to_show))
        ]

        fig.add_trace(
            go.Scatter(
                x=buy_plot_df['Date'],
                y=buy_plot_df['buy_y'],
                mode='markers',
                marker=dict(
                    symbol='triangle-up',
                    size=buy_plot_df['buy_level'].map({'弱': 10,'中': 12, '強': 18}),
                    color=buy_plot_df['buy_level'].map({'弱': '#FFD700','中': '#FFD700', '強': '#00FF7F'}),
                    opacity=1.0,
                    line=dict(width=1, color='black')
                ),
                name='Buy Signal',
                hovertext=buy_plot_df['buy_level'],
                hoverinfo='text'
            )
        )

        fig.add_trace(
            go.Scatter(
                x=sell_plot_df['Date'],
                y=sell_plot_df['sell_y'],
                mode='markers',
                marker=dict(
                    symbol='triangle-down',
                    size=sell_plot_df['sell_level'].map({'弱': 10,'中': 12, '強': 18}),
                    color=sell_plot_df['sell_level'].map({'弱': '#FFA500','中': '#FFA500', '強': '#FF3333'}),
                    opacity=1.0,
                    line=dict(width=1, color='black')
                ),
                name='Sell Signal',
                hovertext=sell_plot_df['sell_level'],
                hoverinfo='text'
            )
        )

        ma_periods = df.attrs.get('ma_periods', [])
        ma_colors = ['#FDDD42', '#87DCF6', '#C29ACF', '#F3524F', '#009B3A', '#FF66CC']

        ma_list = [
            (f'MA{p}', ma_colors[i % len(ma_colors)], f'{p}MA')
            for i, p in enumerate(ma_periods)
        ]

        for col, color, name in ma_list:
            if col in df.columns:
                fig.add_trace(go.Scatter(x=df['Date'], y=df[col], name=name, line=dict(color=color, width=1.2), hovertemplate='%{y:.1f}'))
        
        fig.update_layout(xaxis_rangeslider_visible=False)

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

    if view_mode not in ["成交量", "KD指標"]:
        fig.add_hline(y=curr, line_dash="dot", line_color="#FFFFFF", line_width=2)
        fig.add_annotation(x=df['Date'].iloc[-1], y=curr, text=f"現價: {curr:.2f}", showarrow=False, xanchor="left", xshift=10, yshift=15, font=dict(color="#FFFFFF", size=14, family="Arial Black"))

    # 副圖繪製邏輯
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
        # 新增：BandWidth 副圖繪製
        elif sub_mode == "BandWidth":
            fig.add_trace(
                go.Scatter(
                    x=df['Date'], 
                    y=df['BandWidth'], 
                    name="BandWidth", 
                    line=dict(color='#FFD700', width=1.5), 
                    hovertemplate='%{y:.4f}'
                ), 
                row=2, col=1
            )

    if time_frame == "日":
        dt_all = pd.date_range(
            start=df['Date'].min(),
            end=df['Date'].max(),
            freq='D'
        )
        dt_breaks = dt_all.difference(df['Date'])
    
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),        
                dict(values=dt_breaks.tolist())     
            ]
        )
    else:
        fig.update_xaxes(rangebreaks=[])

    fig.update_layout(
        height=800 if show_sub_chart else 650,
        plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1E1E1E", font_size=12),
        showlegend=False, 
        margin=dict(l=10, r=100, t=10, b=10),
        
        xaxis=dict(
            showspikes=True, 
            spikemode="across", 
            spikethickness=1,
            spikecolor="white", 
            spikedash="solid",   
        ),
        yaxis=dict(
            showspikes=True,
            spikemode="across", 
            spikethickness=1,
            spikecolor="white", 
            spikedash="dot",    
            spikesnap="data",   
        )
    )    

    if show_sub_chart:
        fig.update_layout(
            xaxis2=dict(
                showspikes=True, 
                spikemode="across", 
                spikethickness=1,
                spikecolor="white", 
                spikedash="solid"   
            )
        )
    st.plotly_chart(fig, use_container_width=True)

# ==================================================
# 二、Watchlist「共振排行榜」（全收藏掃描）
# ==================================================
st.divider()
if st.button("🏆 Watchlist 共振排行榜"):
    resonance_rows = []
    
    for ticker, name in st.session_state.watchlist_dict.items():
        res = get_stock_data(ticker, years_input, time_frame)
        if not res:
            continue
        
        tdf, trend_info = res
        if trend_info is None or len(tdf) < 50:
            continue
        
        slope = trend_info[0]
        score = calc_resonance_score(tdf)
        score_V2 = calc_resonance_score_V2(tdf)
        patterns = detect_market_pattern(tdf, slope)
        stable_pattern = update_pattern_history(ticker, patterns)
        
        curr_price = float(tdf['Close'].iloc[-1])
        tl_last = tdf['TL'].iloc[-1]
        dist_pct = ((curr_price - tl_last) / tl_last) * 100

        # --- 修正：帶寬擠壓安全讀取邏輯 ---
        bw_squeeze = "—"
        if 'BandWidth' in tdf.columns and pd.notna(tdf['BandWidth'].iloc[-1]):
            bw_raw = float(tdf['BandWidth'].iloc[-1])
            
            # 如果數據非 0 才進行判斷
            if bw_raw > 0:
                # 自動判斷是小數(0.04)還是百分比(4.0)
                if bw_raw <= 1.0: # 小數格式 (0.035 代表 3.5%)
                    is_squeezed = bw_raw < 0.04
                    display_val = bw_raw * 100
                else: # 百分比格式 (3.5 代表 3.5%)
                    is_squeezed = bw_raw < 4.0
                    display_val = bw_raw
                
                bw_squeeze = f"⚡ {display_val:.1f}%" if is_squeezed else f"{display_val:.1f}%"

        last_buy  = bool(tdf['buy_signal'].iloc[-1])
        last_sell = bool(tdf['sell_signal'].iloc[-1])
        icon = "—"

        if last_buy:
            lvl = str(tdf['buy_level'].iloc[-1])
            icon = f"🔸 {lvl}"
        elif last_sell:
            lvl = str(tdf['sell_level'].iloc[-1])
            icon = f"🔹 {lvl}"
            
        resonance_rows.append({
            "代號": ticker,
            "名稱": name,
            "共振分數": score,
            "共振分數V2": f"{score_V2:.1f}",
            "K線訊號": icon,
            "狀態": score_label(score),
            "最新價格": f"{curr_price:.1f}",
            "偏離 TL": f"{dist_pct:+.1f}%",
            "帶寬擠壓": bw_squeeze,
            "AI 市場型態": stable_pattern,
        })
    
    if resonance_rows:
        df_rank = pd.DataFrame(resonance_rows)
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
                "K線訊號": st.column_config.TextColumn(width="small"),
                "狀態": st.column_config.TextColumn(width="small"),
                "最新價格": st.column_config.TextColumn(width="small"),
                "偏離 TL": st.column_config.TextColumn(width="small"),
                "帶寬擠壓": st.column_config.TextColumn(width="small"),
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

            # --- 修正：帶寬擠壓安全讀取邏輯 ---
            bw_squeeze = "—"
            if 'BandWidth' in tdf.columns and pd.notna(tdf['BandWidth'].iloc[-1]):
                bw_raw = float(tdf['BandWidth'].iloc[-1])
                if bw_raw > 0:
                    if bw_raw <= 1.0:
                        is_squeezed = bw_raw < 0.04
                        display_val = bw_raw * 100
                    else:
                        is_squeezed = bw_raw < 4.0
                        display_val = bw_raw
                    
                    bw_squeeze = f"⚡ {display_val:.1f}%" if is_squeezed else f"{display_val:.1f}%"

            last_buy  = bool(tdf['buy_signal'].iloc[-1])
            last_sell = bool(tdf['sell_signal'].iloc[-1])
            icon = "—"

            if last_buy:
                lvl = str(tdf['buy_level'].iloc[-1])
                icon = f"🔸 {lvl}"
            elif last_sell:
                lvl = str(tdf['sell_level'].iloc[-1])
                icon = f"🔹 {lvl}"
                
            summary.append({
                "代號": t,
                "名稱": name,
                "最新價格": f"{p:.1f}",
                "偏離中心線": f"{((p - t_tl) / t_tl) * 100:+.1f}%",
                "位階狀態": pos,
                "帶寬擠壓": bw_squeeze,
                "K線訊號": icon
            })
    if summary: st.table(pd.DataFrame(summary))

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
