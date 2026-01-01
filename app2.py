# --- 5. 新增：所有追蹤標的位階概覽 ---
st.divider()
st.header("📋 追蹤清單位階概覽")

# 建立一個按鈕來觸發掃描 (避免每次重新整理都掃描，節省流量)
if st.button("🔄 掃描所有追蹤標的位階"):
    summary_data = []
    with st.spinner('正在分析清單中的股票...'):
        for t in st.session_state.watchlist:
            # 獲取各標的數據 (同樣使用 3.5 年回測)
            res = get_lohas_data(t, years_input)
            if res:
                temp_df, _, _ = res
                price = float(temp_df['Close'].iloc[-1])
                tl = temp_df['TL'].iloc[-1]
                p2sd = temp_df['TL+2SD'].iloc[-1]
                m2sd = temp_df['TL-2SD'].iloc[-1]
                
                # 判斷位階
                if price > p2sd:
                    pos = "⚠️ 過熱"
                elif price > tl:
                    pos = "📊 偏高"
                elif price < m2sd:
                    pos = "💎 特價"
                else:
                    pos = "✅ 便宜"
                
                dist = ((price - tl) / tl) * 100
                summary_data.append({
                    "股票代號": t,
                    "目前價格": f"{price:.2f}",
                    "中心線距離": f"{dist:+.2f}%",
                    "目前位階": pos
                })
    
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        # 使用顏色標註功能
        def color_status(val):
            color = 'white'
            if val == "💎 特價": color = '#90ee90' # 淺綠
            elif val == "⚠️ 過熱": color = '#ffcccb' # 淺紅
            return f'background-color: {color}'
        
        st.table(summary_df.style.applymap(color_status, subset=['目前位階']))
    else:
        st.info("請點擊按鈕開始掃描清單位階。")

# --- 6. 顯示原始詳細數據 (保留原功能) ---
with st.expander("查看當前標的詳細數據"):
    st.dataframe(df.tail(10).sort_values('Date', ascending=False))
