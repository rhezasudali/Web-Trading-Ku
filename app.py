import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import math
import time
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator, MACD, ADXIndicator, PSARIndicator
from ta.volatility import AverageTrueRange
from ta.volume import MFIIndicator, OnBalanceVolumeIndicator

# Konfigurasi Halaman Website
st.set_page_config(page_title="Quant Screener", page_icon="🚀", layout="wide")

FILE_PATH = "Stock List  - 20250805.xlsx"  
PERIOD = "1y"
INTERVAL = "1d"
MIN_DATA = 200
MIN_AVG_VALUE = 10_000_000_000   
LOT_SIZE = 100                 
RISK_PER_TRADE_PCT = 0.01      
ACCOUNT_SIZE = 1_000_000_000   
ATR_MULTIPLIER = 3             

@st.cache_data
def read_tickers_and_metadata(path):
    try:
        df = pd.read_excel(path)
    except Exception:
        df = pd.read_csv(path) 
        
    tickers = []
    metadata = {}
    if "Code" in df.columns:
        for _, row in df.iterrows():
            code_raw = row['Code']
            code_str = code_raw.iloc[0] if isinstance(code_raw, pd.Series) else code_raw
            code = str(code_str).strip().upper() + ".JK"
            nama = str(row.get("Company Name", "-")).strip()
            sektor = str(row.get("Sektor", "-")).strip()
            tickers.append(code)
            metadata[code] = {'nama': nama, 'sektor': sektor}
        tickers = list(dict.fromkeys(tickers))
        return tickers, metadata
    else:
        tickers = [str(x).strip().upper() + ".JK" for x in df.iloc[:,0].dropna().unique()]
        return tickers, {}

def safe_download(ticker):
    for attempt in range(1, 4):
        try:
            data = yf.download(ticker, period=PERIOD, interval=INTERVAL, progress=False, multi_level_index=False)
            if data is None or data.empty:
                return None
            data.columns = [c.capitalize() for c in data.columns]
            return data
        except Exception:
            time.sleep(0.5)
    return None

def get_ihsg_baseline():
    ihsg = safe_download("^JKSE")
    if ihsg is not None and len(ihsg) > 20:
        return (float(ihsg['Close'].iloc[-1]) - float(ihsg['Close'].iloc[-21])) / float(ihsg['Close'].iloc[-21])
    return 0.0

def compute_indicators(data):
    data = data.dropna(subset=["Close"]).copy()
    res = {}
    close, high, low, vol = data["Close"], data["High"], data["Low"], data["Volume"]

    res['ma20'] = float(SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
    res['ma50'] = float(SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
    res['ma200'] = float(SMAIndicator(close=close, window=200).sma_indicator().iloc[-1]) if len(close)>=200 else float('nan')
    res['rsi'] = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])
    res['macd_hist'] = float(MACD(close=close).macd_diff().iloc[-1])
    
    try: res['adx'] = float(ADXIndicator(high=high, low=low, close=close, window=14).adx().iloc[-1])
    except: res['adx'] = 0.0

    res['mfi'] = float(MFIIndicator(high=high, low=low, close=close, volume=vol, window=14).money_flow_index().iloc[-1])
    obv_series = OnBalanceVolumeIndicator(close=close, volume=vol).on_balance_volume()
    res['obv_current'] = float(obv_series.iloc[-1])
    res['obv_ma20'] = float(obv_series.rolling(20).mean().iloc[-1])
    res['target_resist'] = float(high.rolling(20).max().iloc[-1])
    res['atr'] = float(AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1])
    res['psar'] = float(PSARIndicator(high=high, low=low, close=close).psar().iloc[-1])

    data['Value'] = close * vol
    res['avg_value_20'] = float(data['Value'].rolling(20).mean().iloc[-1])
    res['return_20d'] = (float(close.iloc[-1]) - float(close.iloc[-21])) / float(close.iloc[-21]) if len(close) > 20 else 0.0
    return res

def scoring_strict(metrics, last_price, ihsg_return):
    skor_tek = 0
    if not math.isnan(metrics['ma200']) and last_price > metrics['ma20'] > metrics['ma50'] > metrics['ma200']: skor_tek += 30
    elif last_price > metrics['ma200']: skor_tek += 10
    
    jarak_ma20 = abs(last_price - metrics['ma20']) / metrics['ma20']
    if last_price >= metrics['ma20'] and jarak_ma20 <= 0.05: skor_tek += 30
    if metrics['adx'] >= 25: skor_tek += 20
    if 40 <= metrics['rsi'] <= 60 and metrics['macd_hist'] > 0: skor_tek += 20

    skor_flow = 0
    if metrics['mfi'] > 60: skor_flow += 40 
    elif metrics['mfi'] > 50: skor_flow += 20
    if metrics['obv_current'] > metrics['obv_ma20']: skor_flow += 40 
    if jarak_ma20 <= 0.05 and metrics['macd_hist'] > 0: skor_flow += 20 
    skor_flow = min(100, skor_flow)

    rs_diff = (metrics['return_20d'] - ihsg_return) * 100
    if rs_diff >= 5.0: star = 5
    elif rs_diff >= 2.0: star = 4
    elif rs_diff >= 0.0: star = 3
    elif rs_diff >= -2.0: star = 2
    else: star = 1

    if skor_tek >= 80 and skor_flow >= 80 and star >= 4: grade = "A"
    elif skor_tek >= 70 and skor_flow >= 60 and star >= 3: grade = "B"
    elif skor_flow >= 80 and skor_tek < 60: grade = "C"
    elif skor_tek < 50 and skor_flow < 50: grade = "D"
    else: grade = "C"
    return skor_tek, skor_flow, star, grade

def scoring_aggressive(metrics, last_price):
    skor_tek = 0
    if not math.isnan(metrics['ma200']) and last_price > metrics['ma20'] > metrics['ma50'] > metrics['ma200']: skor_tek += 30
    elif last_price > metrics['ma200']: skor_tek += 10
    
    jarak_ma20 = abs(last_price - metrics['ma20']) / metrics['ma20']
    if last_price >= metrics['ma20'] and jarak_ma20 <= 0.05: skor_tek += 30
    elif last_price >= metrics['ma20'] and jarak_ma20 > 0.05 and metrics['macd_hist'] > 0 and metrics['adx'] >= 20: skor_tek += 30
    if metrics['adx'] >= 20: skor_tek += 20
    if 40 <= metrics['rsi'] <= 75 and metrics['macd_hist'] > 0: skor_tek += 20

    skor_flow = 0
    if metrics['mfi'] > 60: skor_flow += 40 
    elif metrics['mfi'] >= 45: skor_flow += 20 
    if metrics['obv_current'] > metrics['obv_ma20']: skor_flow += 40 
    if metrics['macd_hist'] > 0 and metrics['obv_current'] > metrics['obv_ma20']: skor_flow += 20
    skor_flow = min(100, skor_flow)

    if skor_tek >= 80 and skor_flow >= 80: grade = "A"
    elif skor_tek >= 70 and skor_flow >= 60: grade = "B"
    elif skor_flow >= 80 and skor_tek < 60: grade = "C"
    elif skor_tek < 50 and skor_flow < 50: grade = "D"
    else: grade = "C"
    return skor_tek, skor_flow, grade

def compute_risk_reward(last_price, metrics):
    stop_price = metrics['psar'] if metrics['psar'] < last_price else (last_price - (ATR_MULTIPLIER * metrics['atr']))
    if stop_price <= 0 or stop_price >= last_price: 
        return round(last_price*0.9, 2), round(last_price*1.1, 2), 0.0, 0, 0.0

    target = metrics['target_resist']
    if target <= last_price: target = last_price + ((last_price - stop_price) * 2) 

    risk = last_price - stop_price
    reward = target - last_price
    rrr_ratio = reward / risk if risk > 0 else 0

    risk_money = ACCOUNT_SIZE * RISK_PER_TRADE_PCT
    qty_shares = math.floor(risk_money / risk) if risk > 0 else 0
    qty_lots = math.floor(qty_shares / LOT_SIZE)
    
    if qty_lots < 1: return round(stop_price, 2), round(target, 2), round(rrr_ratio, 2), 0, 0.0
    pos_pct = ((qty_lots * LOT_SIZE) * last_price / ACCOUNT_SIZE) * 100
    return round(stop_price, 2), round(target, 2), round(rrr_ratio, 2), qty_lots, round(pos_pct, 2)

# --- TAMPILAN WEBSITE STREAMLIT ---
st.title("🚀 Quant Screener: Dual-Engine")
st.markdown("Sistem *screening* saham otomatis berbasis institusional.")

if st.button("Jalankan Screening Hari Ini (Klik 1x Saja)", type="primary"):
    with st.spinner("Mengunduh data IHSG..."):
        ihsg_return = get_ihsg_baseline()
        st.info(f"Performa IHSG 1 Bulan Terakhir: {ihsg_return*100:.2f}%")

    tickers, metadata = read_tickers_and_metadata(FILE_PATH)
    all_results = []
    
    # Membuat Progress Bar di Website
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, t in enumerate(tickers, 1):
        # Update tulisan dan loading bar di website
        status_text.text(f"Menganalisa {t} ({i}/{len(tickers)})... Proses ini memakan waktu beberapa menit.")
        progress_bar.progress(i / len(tickers))
        
        data = safe_download(t)
        if data is None or data.empty: continue
        data = data.dropna(subset=["Close"]).copy()
        if len(data) < MIN_DATA: continue

        metrics = compute_indicators(data)
        if metrics['avg_value_20'] < MIN_AVG_VALUE: continue 

        raw_last = data['Close'].iloc[-1]
        if pd.isna(raw_last): continue
        last_price = float(raw_last)
        
        tek_s, flow_s, star, grade_s = scoring_strict(metrics, last_price, ihsg_return)
        tek_a, flow_a, grade_a = scoring_aggressive(metrics, last_price)
        stop, target, rrr, lots, pos_pct = compute_risk_reward(last_price, metrics)
        if stop is None: continue

        prev_close = float(data['Close'].iloc[-2]) if not pd.isna(data['Close'].iloc[-2]) and data['Close'].iloc[-2] > 0 else last_price
        change_pct = round(((last_price - prev_close) / prev_close) * 100, 2)
        jarak_ma20_pct = round(((last_price - metrics['ma20']) / metrics['ma20']) * 100, 2)
        obv_status = "Akumulasi" if metrics['obv_current'] > metrics['obv_ma20'] else "Distribusi"
        
        all_results.append({
            "Saham": t.replace(".JK",""),
            "Sektor": metadata.get(t, {}).get('sektor', '-'),
            "Harga": int(last_price),
            "%Ubah": change_pct,
            "GRADE_STRICT": grade_s,
            "GRADE_AGRES": grade_a,
            "RRR": rrr,
            "MFI(Uang)": round(metrics['mfi'], 2),
            "ADX(Tren)": round(metrics['adx'], 2) if not math.isnan(metrics['adx']) else 0,
            "JarakMA20%": jarak_ma20_pct,
            "Max Modal%": pos_pct,
            "Val(M)": round(metrics['avg_value_20']/1_000_000_000, 1)
        })

    status_text.text("Screening Selesai! Memuat hasil...")
    
    if all_results:
        df_all = pd.DataFrame(all_results)
        
        # Filter Strict
        m_strict_grade = df_all['GRADE_STRICT'].isin(['A', 'B'])
        df_strict = df_all[m_strict_grade & (df_all['RRR'] >= 1.0) & (df_all['MFI(Uang)'] > 50)].copy()
        df_strict = df_strict.sort_values(by=["GRADE_STRICT", "RRR"], ascending=[True, False])
        
        # Filter Aggressive
        m_agg_grade = df_all['GRADE_AGRES'].isin(['A', 'B'])
        # Kita menggunakan threshold MFI 45 untuk aggressive (sesuai kode kita sebelumnya)
        df_aggressive = df_all[m_agg_grade & (df_all['MFI(Uang)'] >= 45)].copy()
        df_aggressive = df_aggressive.sort_values(by=["GRADE_AGRES", "MFI(Uang)"], ascending=[True, False])

        st.subheader("🛡️ ENGINE 1: STRICT SETUP (Pelindung Modal & Risiko Aman)")
        if not df_strict.empty:
            st.dataframe(df_strict.style.background_gradient(cmap='Greens', subset=['RRR', 'MFI(Uang)']))
        else:
            st.warning("Tidak ada saham yang memenuhi syarat Strict hari ini. Tetap pegang Cash!")

        st.subheader("🔥 ENGINE 2: AGGRESSIVE MOMENTUM (High Risk / Breakout)")
        st.markdown("*Peringatan: Risiko tinggi. Patuhi batas Max Modal% jika membeli saham ini.*")
        if not df_aggressive.empty:
            st.dataframe(df_aggressive.style.background_gradient(cmap='Oranges', subset=['MFI(Uang)', 'ADX(Tren)']))
        else:
            st.info("Tidak ada saham Momentum hari ini.")
            
    else:
        st.error("Tidak ada saham yang memenuhi kriteria likuiditas.")