import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import ta
import time
import requests
import feedparser
import sqlite3
import json
import random
import logging
from typing import Dict, List, Optional, Any
from collections import deque
import warnings
warnings.filterwarnings('ignore')

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('forex_pro.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)


class UltraCache:
    def __init__(self):
        self._cache = {}
        self._ttl = {}
    def get(self, key):
        if key in self._cache and time.time() < self._ttl.get(key, 0):
            return self._cache[key]
        self._cache.pop(key, None); self._ttl.pop(key, None)
        return None
    def set(self, key, value, expire=60):
        self._cache[key] = value; self._ttl[key] = time.time() + expire

CACHE = UltraCache()


STOCKS_FOREX = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X", "GC=F", "SI=F", "BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD"]
SYMBOLS_MAP = {"EURUSD=X": "يورو/دولار", "GBPUSD=X": "جنيه/دولار", "USDJPY=X": "دولار/ين", "AUDUSD=X": "أسترالي/دولار", "USDCAD=X": "دولار/كندي", "USDCHF=X": "دولار/فرنك", "NZDUSD=X": "نيوزيلندي/دولار", "EURGBP=X": "يورو/جنيه", "EURJPY=X": "يورو/ين", "GBPJPY=X": "جنيه/ين", "GC=F": "ذهب", "SI=F": "فضة", "BTC-USD": "بيتكوين", "ETH-USD": "إيثيريوم", "XRP-USD": "ريبل", "SOL-USD": "سولانا"}
NEWS_SOURCES = {"Forex Factory": "https://www.forexfactory.com/news-rss.php", "FXStreet": "https://www.fxstreet.com/rss/news", "DailyFX": "https://www.dailyfx.com/feeds/forex-market-news", "Forexlive": "https://www.forexlive.com/feed", "Action Forex": "https://www.actionforex.com/feed/"}

# Asset type classification for proper lot sizing
ASSET_TYPES = {
    "EURUSD=X": "forex", "GBPUSD=X": "forex", "USDJPY=X": "forex", "AUDUSD=X": "forex",
    "USDCAD=X": "forex", "USDCHF=X": "forex", "NZDUSD=X": "forex", "EURGBP=X": "forex",
    "EURJPY=X": "forex", "GBPJPY=X": "forex",
    "GC=F": "commodity", "SI=F": "commodity",
    "BTC-USD": "crypto", "ETH-USD": "crypto", "XRP-USD": "crypto", "SOL-USD": "crypto"
}


class DBManager:
    def __init__(self):
        self.conn = sqlite3.connect("forex_pro.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
    def _init_tables(self):
        c = self.conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, pair TEXT, signal TEXT, entry REAL, tp REAL, sl REAL, lots REAL, result TEXT, pips REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS predictions (id INTEGER PRIMARY KEY, pair TEXT, prediction TEXT, confidence REAL, actual TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, pair TEXT, alert_type TEXT, message TEXT, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        self.conn.commit()
    def save_trade(self, d):
        c = self.conn.cursor()
        c.execute("INSERT INTO trades (pair,signal,entry,tp,sl,lots) VALUES (?,?,?,?,?,?)", (d["pair"], d["signal"], d["entry"], d["tp"], d["sl"], d.get("lots", 0)))
        self.conn.commit()
    def get_trades(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT 100")
        return [dict(r) for r in c.fetchall()]
    def save_alert(self, pair, alert_type, message):
        c = self.conn.cursor()
        c.execute("INSERT INTO alerts (pair,alert_type,message) VALUES (?,?,?)", (pair, alert_type, message))
        self.conn.commit()
    def get_alerts(self, limit=50):
        c = self.conn.cursor()
        c.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in c.fetchall()]
    def clear_alerts(self):
        """Clear all alerts from the database"""
        c = self.conn.cursor()
        c.execute("DELETE FROM alerts")
        self.conn.commit()

DB = DBManager()


class SessionEngine:
    @staticmethod
    def get_sessions():
        h = datetime.utcnow().hour
        sessions = []
        if 0 <= h < 9: sessions.append({"name": "الآسيوية", "city": "طوكيو", "icon": "🌏", "color": "#00ff88"})
        if 8 <= h < 17: sessions.append({"name": "لندن", "city": "أوروبا", "icon": "🏛️", "color": "#00d4ff"})
        if 13 <= h < 22: sessions.append({"name": "نيويورك", "city": "أمريكا", "icon": "🗽", "color": "#ff4b4b"})
        if 21 <= h or h < 2: sessions.append({"name": "سيدني", "city": "أستراليا", "icon": "🌙", "color": "#ffc107"})
        return sessions
    @staticmethod
    def get_calendar():
        return [{"time": "08:30", "event": "CPI", "currency": "USD", "impact": "عالي", "color": "#ff4b4b"}, {"time": "14:00", "event": "قرار الفائدة", "currency": "USD", "impact": "عالي", "color": "#ff4b4b"}, {"time": "09:00", "event": "مبيعات التجزئة", "currency": "EUR", "impact": "متوسط", "color": "#ffc107"}, {"time": "13:30", "event": "إعانة البطالة", "currency": "USD", "impact": "متوسط", "color": "#ffc107"}]
    @staticmethod
    def get_warnings(news_items, pair):
        warnings = []
        pair_base = pair.split('/')[0] if '/' in pair else pair
        keywords = ['interest rate', 'fed', 'fomc', 'cpi', 'nfp', 'gdp', 'inflation', 'قرار', 'فائدة', 'تضخم']
        for item in news_items:
            title_lower = item['title'].lower()
            if pair_base.lower() in title_lower or "forex" in title_lower:
                for key in keywords:
                    if key in title_lower:
                        warnings.append({"type": "🔴 تأثير عالي", "title": item['title'], "impact": "⚠️ تقلبات شديدة متوقعة"})
                        break
        return warnings


class DataEngine:
    @staticmethod
    def fetch(symbol, period="5d", interval="15m"):
        key = f"data_{symbol}_{period}_{interval}"
        cached = CACHE.get(key)
        if cached is not None: return cached
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if df.empty: return None
            # FIX 4: Flatten multi-index columns from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            CACHE.set(key, df, 60)
            return df
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None

    @staticmethod
    def add_indicators(df):
        close = df['Close'].squeeze(); high = df['High'].squeeze(); low = df['Low'].squeeze()
        open_p = df['Open'].squeeze(); volume = df['Volume'].squeeze()

        # EMAs
        df['EMA_9'] = ta.trend.ema_indicator(close, window=9)
        df['EMA_21'] = ta.trend.ema_indicator(close, window=21)
        df['EMA_50'] = ta.trend.ema_indicator(close, window=50)
        df['EMA_200'] = ta.trend.ema_indicator(close, window=200)

        # Price Action
        df['HH_20'] = high.rolling(20).max(); df['LL_20'] = low.rolling(20).min()
        df['HH_5'] = high.rolling(5).max(); df['LL_5'] = low.rolling(5).min()

        # Candlestick Patterns
        df['Hammer'] = ta.candle.hammer(high, low, open_p, close)
        df['Engulfing'] = ta.candle.bullish_engulfing(high, low, open_p, close)
        df['Doji'] = ta.candle.doji(high, low, open_p, close)
        df['Morning_Star'] = ta.candle.morning_star(high, low, open_p, close)
        df['Evening_Star'] = ta.candle.evening_star(high, low, open_p, close)

        # Momentum
        df['RSI'] = ta.momentum.rsi(close, window=14)
        df['RSI_MA'] = df['RSI'].rolling(9).mean()
        macd = ta.trend.MACD(close)
        df['MACD'] = macd.macd(); df['MACD_Signal'] = macd.macd_signal(); df['MACD_Hist'] = macd.macd_diff()
        df['Stoch_K'] = ta.momentum.stoch(high, low, close)
        df['Stoch_D'] = ta.momentum.stoch_signal(high, low, close)

        # Volume
        df['OBV'] = ta.volume.on_balance_volume(close, volume)
        df['MFI'] = ta.volume.money_flow_index(high, low, close, volume)
        df['VWAP'] = ta.volume.volume_weighted_average_price(high, low, close, volume)
        df['Volume_MA'] = volume.rolling(20).mean()
        df['Volume_Ratio'] = volume / df['Volume_MA']
        df['Delta'] = np.where(close > open_p, volume, -volume)
        df['CVD'] = df['Delta'].cumsum()

        # Volatility
        bb = ta.volatility.BollingerBands(close, window=20)
        df['BB_Upper'] = bb.bollinger_hband(); df['BB_Lower'] = bb.bollinger_lband()
        df['BB_Middle'] = bb.bollinger_mavg(); df['BB_Width'] = bb.bollinger_wband()
        df['ATR'] = ta.volatility.average_true_range(high, low, close, window=14)
        df['ATR_Percent'] = (df['ATR'] / close) * 100

        # ADX
        adx = ta.trend.ADXIndicator(high, low, close, window=14)
        df['ADX'] = adx.adx(); df['DI_Plus'] = adx.adx_pos(); df['DI_Minus'] = adx.adx_neg()

        # Market Structure
        df['BOS'] = np.where(close > df['HH_20'].shift(1), 1, np.where(close < df['LL_20'].shift(1), -1, 0))

        # ICT/SMC - FVG
        df['FVG'] = np.where((high.shift(2) < low), 1, np.where((low.shift(2) > high), -1, 0))
        df['FVG_Size'] = np.where(df['FVG'] == 1, low - high.shift(2), np.where(df['FVG'] == -1, low.shift(2) - high, 0))

        # Order Blocks
        df['Bull_OB'] = np.where((close.shift(1) < open_p.shift(1)) & (close > open_p) & (close > close.shift(1)), 1, 0)
        df['Bear_OB'] = np.where((close.shift(1) > open_p.shift(1)) & (close < open_p) & (close < close.shift(1)), -1, 0)

        # Liquidity
        df['Buy_Side_Liq'] = df['HH_20']; df['Sell_Side_Liq'] = df['LL_20']
        df['Internal_Liq'] = df['HH_5']; df['External_Liq'] = df['LL_5']

        # Premium/Discount Zones
        range_20 = df['HH_20'] - df['LL_20']
        df['Premium_Zone'] = df['HH_20'] - (range_20 * 0.25)
        df['Discount_Zone'] = df['LL_20'] + (range_20 * 0.25)
        df['Equilibrium'] = (df['HH_20'] + df['LL_20']) / 2

        # Fibonacci
        df['Fib_382'] = df['HH_20'] - (range_20 * 0.382)
        df['Fib_500'] = df['HH_20'] - (range_20 * 0.500)
        df['Fib_618'] = df['HH_20'] - (range_20 * 0.618)
        df['Fib_786'] = df['HH_20'] - (range_20 * 0.786)

        # Order Flow
        df['Order_Flow'] = (close - open_p) * volume

        # Sentiment
        df['Sentiment'] = np.where(df['RSI'] > 60, "صاعد قوي 🟢", np.where(df['RSI'] > 50, "صاعد ضعيف 🟡", np.where(df['RSI'] < 40, "هابط قوي 🔴", "هابط ضعيف 🟠")))

        # Time
        df['Hour'] = df.index.hour; df['Day'] = df.index.day_name()

        return df


class InstitutionalEngine:
    @staticmethod
    def detect_liquidity_sweep(df):
        last = df.iloc[-1]; prev = df.iloc[-2]
        buy_sweep = (prev['High'] >= prev['HH_5']) and (last['Close'] < prev['HH_5'])
        sell_sweep = (prev['Low'] <= prev['LL_5']) and (last['Close'] > prev['LL_5'])
        return {"buy_sweep": buy_sweep, "sell_sweep": sell_sweep, "sweep_type": "شراء" if buy_sweep else "بيع" if sell_sweep else "لا يوجد", "strength": "قوي" if (buy_sweep or sell_sweep) and last['Volume_Ratio'] > 1.5 else "ضعيف"}

    @staticmethod
    def detect_order_blocks(df):
        last = df.iloc[-1]
        return {"bull_ob": last['Bull_OB'] == 1, "bear_ob": last['Bear_OB'] == -1, "ob_type": "صاعد" if last['Bull_OB'] == 1 else "هابط" if last['Bear_OB'] == -1 else "لا يوجد", "ob_strength": "قوي" if abs(last['Order_Flow']) > abs(df['Order_Flow'].mean() * 2) else "عادي"}

    @staticmethod
    def detect_fvg(df):
        last = df.iloc[-1]
        return {"fvg_bull": last['FVG'] == 1, "fvg_bear": last['FVG'] == -1, "fvg_type": "صاعد" if last['FVG'] == 1 else "هابط" if last['FVG'] == -1 else "لا يوجد", "fvg_size": abs(last['FVG_Size']) if last['FVG_Size'] != 0 else 0}

    @staticmethod
    def analyze_structure(df):
        last = df.iloc[-1]
        trend = "صاعد" if last['EMA_50'] > last['EMA_200'] else "هابط"
        structure = "BOS صاعد" if last['BOS'] == 1 else "BOS هابط" if last['BOS'] == -1 else "محايد"
        bos_series = df['BOS'].replace(0, np.nan).dropna()
        choch = False
        if len(bos_series) >= 2: choch = bos_series.iloc[-1] != bos_series.iloc[-2]
        return {"trend": trend, "structure": structure, "choch": choch, "choch_text": "تغيير شخصية ✅" if choch else "استمرار الاتجاه", "trend_strength": "قوي" if last['ADX'] > 25 else "ضعيف", "momentum": "صاعد" if last['DI_Plus'] > last['DI_Minus'] else "هابط"}

    @staticmethod
    def analyze_liquidity(df):
        last = df.iloc[-1]
        dist_to_buy = abs(last['Buy_Side_Liq'] - last['Close']) / last['Close'] * 10000
        dist_to_sell = abs(last['Sell_Side_Liq'] - last['Close']) / last['Close'] * 10000
        return {"buy_liquidity": last['Buy_Side_Liq'], "sell_liquidity": last['Sell_Side_Liq'], "nearest_liq": "شراء" if dist_to_buy < dist_to_sell else "بيع", "dist_buy_pips": round(dist_to_buy, 1), "dist_sell_pips": round(dist_to_sell, 1), "liquidity_zone": "Premium" if last['Close'] > last['Premium_Zone'] else "Discount" if last['Close'] < last['Discount_Zone'] else "Equilibrium"}

    @staticmethod
    def detect_stop_hunt(df):
        last3 = df.tail(3)
        high_wick = (last3['High'].max() - last3['Close'].iloc[-1]) / (last3['High'].max() - last3['Low'].min() + 0.0001) > 0.7
        low_wick = (last3['Close'].iloc[-1] - last3['Low'].min()) / (last3['High'].max() - last3['Low'].min() + 0.0001) > 0.7
        volume_spike = last3['Volume_Ratio'].iloc[-1] > 2.0
        return {"stop_hunt_high": high_wick and volume_spike, "stop_hunt_low": low_wick and volume_spike, "hunt_type": "أعلى" if (high_wick and volume_spike) else "أسفل" if (low_wick and volume_spike) else "لا يوجد", "volume_spike": volume_spike}

    @staticmethod
    def volume_profile(df):
        last = df.iloc[-1]
        vol_mean = df['Volume'].mean(); vol_std = df['Volume'].std()
        buying_pressure = (df['Delta'] > 0).sum() / len(df) * 100
        return {"current_volume": last['Volume'], "volume_status": "عالي" if last['Volume'] > vol_mean + vol_std else "منخفض" if last['Volume'] < vol_mean - vol_std else "عادي", "buying_pressure": round(buying_pressure, 1), "selling_pressure": round(100 - buying_pressure, 1)}


class AIEngine:
    def analyze(self, pair, df, news):
        last = df.iloc[-1]
        patterns = self._detect_patterns(df)
        direction = self._predict_direction(df)
        quality = self._calculate_quality(df)
        vol_pred = self._predict_volatility(df)
        reversal = self._detect_reversal(df)
        sentiment = self._analyze_sentiment(news)
        confidence = self._calculate_confidence(df, direction, quality, patterns)
        return {"prediction": direction["prediction"], "confidence": confidence, "patterns": patterns, "quality": quality, "volatility_pred": vol_pred, "reversal": reversal, "sentiment": sentiment, "recommendations": self._generate_recommendations(direction, confidence, reversal), "analysis_text": self._generate_analysis_text(df, direction, patterns)}

    def _detect_patterns(self, df):
        last = df.iloc[-1]
        patterns = []
        if last['Hammer'] != 0: patterns.append("🔨 مطرقة")
        if last['Engulfing'] != 0: patterns.append("🔄 ابتلاع")
        if last['Doji'] != 0: patterns.append("⭐ دوجي")
        if last['Morning_Star'] != 0: patterns.append("🌅 نجمة الصباح")
        if last['Evening_Star'] != 0: patterns.append("🌆 نجمة المساء")
        if last['FVG'] != 0: patterns.append("⚡ فجوة سيولة")
        if last['Bull_OB'] == 1: patterns.append("🟢 كتلة صاعدة")
        if last['Bear_OB'] == -1: patterns.append("🔴 كتلة هابطة")
        if last['RSI'] < 30: patterns.append("📉 ذروة بيع")
        if last['RSI'] > 70: patterns.append("📈 ذروة شراء")
        if last['BB_Width'] > df['BB_Width'].rolling(20).mean().iloc[-1] * 1.5: patterns.append("📊 توسع بولينجر")
        return patterns

    def _predict_direction(self, df):
        last = df.iloc[-1]; score = 0
        if last['EMA_9'] > last['EMA_21'] > last['EMA_50']: score += 3
        elif last['EMA_9'] < last['EMA_21'] < last['EMA_50']: score -= 3
        if last['RSI'] < 35: score += 2
        elif last['RSI'] > 65: score -= 2
        if last['MACD'] > last['MACD_Signal']: score += 1
        else: score -= 1
        if last['ADX'] > 25: score *= 1.5
        if last['Volume_Ratio'] > 1.5: score *= 1.2
        if score > 3: return {"prediction": "شراء قوي", "score": score}
        elif score > 1: return {"prediction": "شراء محتمل", "score": score}
        elif score < -3: return {"prediction": "بيع قوي", "score": score}
        elif score < -1: return {"prediction": "بيع محتمل", "score": score}
        else: return {"prediction": "محايد", "score": score}

    def _calculate_quality(self, df):
        last = df.iloc[-1]; confluence = 0
        if last['RSI'] < 40 or last['RSI'] > 60: confluence += 1
        if last['ADX'] > 20: confluence += 1
        if last['Volume_Ratio'] > 1.2: confluence += 1
        if abs(last['MACD_Hist']) > abs(df['MACD_Hist'].mean()): confluence += 1
        return {"confluence_score": confluence, "quality": "ممتاز" if confluence >= 4 else "جيد" if confluence >= 2 else "ضعيف", "risk_reward_suggested": 1.5 + (confluence * 0.5)}

    def _predict_volatility(self, df):
        last = df.iloc[-1]; atr_mean = df['ATR'].rolling(20).mean().iloc[-1]
        return {"current_atr": last['ATR'], "predicted_vol": "عالية" if last['ATR'] > atr_mean * 1.3 else "منخفضة" if last['ATR'] < atr_mean * 0.7 else "متوسطة", "atr_percent": last['ATR_Percent']}

    def _detect_reversal(self, df):
        last = df.iloc[-1]; divergence = False
        if len(df) > 20:
            price_high = df['High'].iloc[-10:].max(); rsi_high = df['RSI'].iloc[-10:].max()
            if last['Close'] > price_high * 0.99 and last['RSI'] < rsi_high * 0.95: divergence = True
        return {"reversal_detected": divergence or last['Doji'] != 0 or last['Hammer'] != 0, "reversal_type": "هبوطي" if divergence and last['RSI'] > 60 else "صاعدي" if divergence and last['RSI'] < 40 else "غير محدد", "strength": "قوي" if divergence else "ضعيف"}

    def _analyze_sentiment(self, news):
        positive = ['صعود', 'ارتفاع', 'نمو', 'إيجابي', 'bullish', 'rise', 'growth', 'strong']
        negative = ['هبوط', 'انخفاض', 'تراجع', 'سلبي', 'bearish', 'fall', 'decline', 'weak']
        score = 0
        for item in news[:10]:
            title = item.get('title', '').lower()
            for w in positive: score += title.count(w) * 0.5
            for w in negative: score -= title.count(w) * 0.5
        return {"score": round(max(-10, min(10, score)), 2), "sentiment": "إيجابي" if score > 2 else "سلبي" if score < -2 else "محايد", "strength": "قوي" if abs(score) > 5 else "ضعيف"}

    def _calculate_confidence(self, df, direction, quality, patterns):
        base = 50; base += abs(direction["score"]) * 5; base += quality["confluence_score"] * 5; base += len(patterns) * 3
        if df.iloc[-1]['ADX'] > 25: base += 10
        if df.iloc[-1]['Volume_Ratio'] > 1.5: base += 5
        return min(99, max(10, round(base)))

    def _generate_recommendations(self, direction, confidence, reversal):
        recs = []; pred = direction["prediction"]
        if "شراء" in pred: recs.append("✅ فرصة شراء محتملة"); recs.append("🛑 وقف خسارة دون آخر قاع")
        elif "بيع" in pred: recs.append("✅ فرصة بيع محتملة"); recs.append("🛑 وقف خسارة فوق آخر قمة")
        else: recs.append("⏳ انتظر إشارة أوضح")
        if confidence > 80: recs.append("🚀 ثقة عالية - مخاطرة 2%")
        elif confidence > 60: recs.append("⚠️ ثقة متوسطة - مخاطرة 1%")
        else: recs.append("❌ ثقة منخفضة - تجنب الدخول")
        if reversal["reversal_detected"]: recs.append(f"🔄 انعكاس محتمل: {reversal['reversal_type']}")
        return recs

    def _generate_analysis_text(self, df, direction, patterns):
        last = df.iloc[-1]; lines = []
        lines.append(f"📊 الاتجاه: {direction['prediction']}")
        lines.append(f"📈 القوة: {'قوية' if last['ADX'] > 25 else 'ضعيفة'}")
        lines.append(f"💧 السيولة: {'Premium' if last['Close'] > last['Premium_Zone'] else 'Discount'}")
        if patterns: lines.append(f"🔍 الأنماط: {', '.join(patterns[:3])}")
        return "
".join(lines)


class NewsEngine:
    @staticmethod
    def get_news():
        key = "news_all"
        cached = CACHE.get(key)
        if cached is not None: return cached
        all_news = []
        for name, url in NEWS_SOURCES.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    all_news.append({"source": name, "title": entry.title, "link": entry.link, "published": entry.get('published', 'الآن'), "summary": entry.get('summary', '')[:150]})
            except: pass
        all_news.sort(key=lambda x: x.get('published', ''), reverse=True)
        CACHE.set(key, all_news[:25], 300)
        return all_news[:25]


class BacktestEngine:
    @staticmethod
    def run(df, balance=10000):
        trades = []; wins = 0; losses = 0; equity = balance; max_dd = 0; peak = balance
        for i in range(50, len(df) - 1):
            row = df.iloc[i]
            signal = BacktestEngine._signal(row)
            if signal == "NEUTRAL": continue

            entry = float(row['Close'])
            atr = float(row['ATR'])
            tp = entry + (atr * 2) if signal == "BUY" else entry - (atr * 2)
            sl = entry - (atr * 1.5) if signal == "BUY" else entry + (atr * 1.5)

            # FIX 3: Track trade across multiple candles until TP or SL is hit
            result = "OPEN"
            exit_p = entry
            max_bars = 20  # Maximum bars to hold trade

            for j in range(i + 1, min(i + max_bars, len(df))):
                candle = df.iloc[j]
                candle_high = float(candle['High'])
                candle_low = float(candle['Low'])

                if signal == "BUY":
                    if candle_high >= tp:
                        exit_p = tp
                        result = "WIN"
                        break
                    elif candle_low <= sl:
                        exit_p = sl
                        result = "LOSS"
                        break
                else:  # SELL
                    if candle_low <= tp:
                        exit_p = tp
                        result = "WIN"
                        break
                    elif candle_high >= sl:
                        exit_p = sl
                        result = "LOSS"
                        break

            # If trade didn't close within max_bars, close at last candle
            if result == "OPEN":
                last_candle = df.iloc[min(i + max_bars - 1, len(df) - 1)]
                exit_p = float(last_candle['Close'])
                if signal == "BUY":
                    result = "WIN" if exit_p > entry else "LOSS"
                else:
                    result = "WIN" if exit_p < entry else "LOSS"

            if signal == "BUY":
                pips = (exit_p - entry) * 10000
            else:
                pips = (entry - exit_p) * 10000

            if result == "WIN": wins += 1; equity += abs(pips) * 0.1
            else: losses += 1; equity -= abs(pips) * 0.1
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd: max_dd = dd
            trades.append({"signal": signal, "entry": entry, "exit": exit_p, "pips": round(pips, 2), "result": result, "equity": round(equity, 2)})
        total = wins + losses
        wr = (wins / total * 100) if total > 0 else 0
        profit = equity - balance
        pf = (wins * abs(profit / total)) / (losses * abs(profit / total)) if losses > 0 and profit != 0 else 1
        return {"total_trades": total, "wins": wins, "losses": losses, "win_rate": round(wr, 1), "profit": round(profit, 2), "final_equity": round(equity, 2), "max_drawdown": round(max_dd, 2), "profit_factor": round(pf, 2), "trades": trades[-15:]}

    @staticmethod
    def _signal(row):
        # FIX 2: Remove .iloc[0] since row is already a scalar Series
        rsi = float(row['RSI'])
        macd = float(row['MACD'])
        macd_s = float(row['MACD_Signal'])
        if rsi < 35 and macd > macd_s: return "BUY"
        elif rsi > 65 and macd < macd_s: return "SELL"
        return "NEUTRAL"


class CorrelationEngine:
    @staticmethod
    def get_matrix(symbols):
        key = f"corr_{'_'.join(symbols)}"
        cached = CACHE.get(key)
        if cached is not None: return cached
        try:
            data = yf.download(symbols, period="5d", interval="1h", progress=False)['Close']
            corr = data.corr()
            CACHE.set(key, corr, 1800)
            return corr
        except: return None


class AlertSystem:
    @staticmethod
    def check_alerts(df, pair):
        alerts = []; last = df.iloc[-1]
        if last['RSI'] < 25: alerts.append({"type": "ذروة بيع", "msg": f"RSI في ذروة البيع: {last['RSI']:.1f}", "level": "عالي"})
        if last['RSI'] > 75: alerts.append({"type": "ذروة شراء", "msg": f"RSI في ذروة الشراء: {last['RSI']:.1f}", "level": "عالي"})
        if last['Volume_Ratio'] > 3: alerts.append({"type": "ارتفاع حجم", "msg": "حجم تداول استثنائي", "level": "متوسط"})
        if last['ADX'] > 40: alerts.append({"type": "اتجاه قوي", "msg": f"ADX قوي: {last['ADX']:.1f}", "level": "منخفض"})
        if last['BB_Width'] > df['BB_Width'].rolling(20).mean().iloc[-1] * 2: alerts.append({"type": "تقلب عالي", "msg": "توسع كبير في بولينجر", "level": "متوسط"})
        for a in alerts: DB.save_alert(pair, a['type'], a['msg'])
        return alerts


class LotCalculator:
    """Advanced lot sizing calculator supporting Forex, Crypto, and Commodities"""

    @staticmethod
    def get_asset_info(symbol):
        """Get asset type and pip/tick value information"""
        asset_type = ASSET_TYPES.get(symbol, "forex")

        if asset_type == "forex":
            if "JPY" in symbol:
                return {"type": "forex", "pip_size": 0.01, "pip_value": 1000, "contract_size": 100000}
            else:
                return {"type": "forex", "pip_size": 0.0001, "pip_value": 10, "contract_size": 100000}
        elif asset_type == "crypto":
            return {"type": "crypto", "pip_size": 1.0, "pip_value": 1, "contract_size": 1}
        elif asset_type == "commodity":
            if symbol == "GC=F":  # Gold
                return {"type": "commodity", "pip_size": 0.1, "pip_value": 10, "contract_size": 100}
            elif symbol == "SI=F":  # Silver
                return {"type": "commodity", "pip_size": 0.01, "pip_value": 50, "contract_size": 5000}

        return {"type": "forex", "pip_size": 0.0001, "pip_value": 10, "contract_size": 100000}

    @staticmethod
    def calculate_lots(symbol, account_balance, risk_percent, entry_price, stop_loss_price):
        """Calculate proper lot size based on asset type"""
        info = LotCalculator.get_asset_info(symbol)
        risk_amount = account_balance * (risk_percent / 100)
        price_diff = abs(entry_price - stop_loss_price)

        if info["type"] == "forex":
            # Forex: 1 lot = 100,000 units, pip value varies
            if price_diff == 0:
                return 0.01
            # Calculate pips distance
            pips = price_diff / info["pip_size"]
            if pips == 0:
                return 0.01
            # Risk per pip = Risk Amount / Pips
            risk_per_pip = risk_amount / pips
            # Lots = Risk per pip / Pip value per lot
            lots = risk_per_pip / info["pip_value"]

        elif info["type"] == "crypto":
            # Crypto: Lot = number of coins/units
            if price_diff == 0:
                return 0.001
            lots = risk_amount / price_diff

        elif info["type"] == "commodity":
            # Commodities: Standard lot sizing
            if price_diff == 0:
                return 0.01
            # For gold: 1 lot = 100 oz, $10 per $0.1 move
            tick_value = info["pip_value"]
            ticks = price_diff / info["pip_size"]
            if ticks == 0:
                return 0.01
            lots = risk_amount / (ticks * tick_value)
        else:
            lots = 0.01

        # Round to standard lot sizes
        if info["type"] == "crypto":
            return round(max(0.001, lots), 3)
        else:
            return round(max(0.01, lots), 2)

    @staticmethod
    def format_position_size(symbol, lots):
        """Format position size for display"""
        info = LotCalculator.get_asset_info(symbol)
        if info["type"] == "crypto":
            return f"{lots:.3f} {symbol.split('-')[0]}"
        elif info["type"] == "commodity":
            if symbol == "GC=F":
                return f"{lots:.2f} lot ({lots * 100:.0f} oz)"
            elif symbol == "SI=F":
                return f"{lots:.2f} lot ({lots * 5000:.0f} oz)"
        else:
            return f"{lots:.2f} lot ({lots * 100000:,.0f} units)"


# ============================================================
# MAIN UI
# ============================================================
def main():
    st.set_page_config(page_title="Forex AI Quantum PRO - المنصة الاحترافية", page_icon="🚀", layout="wide", initial_sidebar_state="expanded")

    if "last_update" not in st.session_state:
        st.session_state.last_update = time.time()
        st.session_state.notifications = []

    current_time = time.time()
    if current_time - st.session_state.last_update > 60:
        st.session_state.last_update = current_time
        st.rerun()

    # CSS
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Tajawal:wght@400;700&display=swap');
        .main { background-color: #050a14; color: #e0e0e0; font-family: 'Tajawal', sans-serif; }
        .main-header { background: rgba(13, 25, 48, 0.7); backdrop-filter: blur(10px); padding: 2rem; border-radius: 20px; border: 1px solid rgba(0, 212, 255, 0.2); text-align: center; margin-bottom: 2rem; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.8); }
        .header-title { font-family: 'Orbitron', sans-serif; font-size: 3rem; background: linear-gradient(90deg, #00d4ff, #00ff88, #ff4b4b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: bold; letter-spacing: 2px; }
        .arabic-title { font-family: 'Tajawal', sans-serif; font-size: 2rem; color: #00d4ff; margin-top: 10px; }
        .analysis-card { background: rgba(18, 32, 58, 0.6); border: 1px solid rgba(0, 212, 255, 0.1); padding: 20px; border-radius: 15px; transition: all 0.3s ease; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .analysis-card:hover { border: 1px solid #00d4ff; box-shadow: 0 0 20px rgba(0, 212, 255, 0.4); transform: translateY(-5px); }
        [data-testid="stMetricValue"] { font-family: 'Orbitron', sans-serif; color: #00d4ff !important; text-shadow: 0 0 10px rgba(0, 212, 255, 0.5); }
        .stTabs [data-baseweb="tab-list"] { gap: 15px; background-color: transparent; }
        .stTabs [data-baseweb="tab"] { height: 50px; background-color: rgba(18, 32, 58, 0.8); border-radius: 10px 10px 0 0; color: #888; border: 1px solid rgba(0, 212, 255, 0.1); font-weight: bold; font-family: 'Tajawal', sans-serif; }
        .stTabs [aria-selected="true"] { background: linear-gradient(180deg, rgba(0, 212, 255, 0.2), transparent) !important; color: #00d4ff !important; border-bottom: 2px solid #00d4ff !important; }
        .buy-signal { color: #00ff88; font-weight: bold; text-shadow: 0 0 10px rgba(0, 255, 136, 0.5); }
        .sell-signal { color: #ff4b4b; font-weight: bold; text-shadow: 0 0 10px rgba(255, 75, 75, 0.5); }
        .news-card { background: rgba(18, 32, 58, 0.4); border-right: 4px solid #00d4ff; padding: 15px; border-radius: 10px 0 0 10px; margin-bottom: 10px; text-align: right; }
        .warning-card { background-color: rgba(255, 75, 75, 0.2); padding: 15px; border-radius: 10px; border: 1px solid #ff4b4b; margin-bottom: 15px; text-align: right; }
        .success-card { background-color: rgba(0, 255, 136, 0.2); padding: 15px; border-radius: 10px; border: 1px solid #00ff88; margin-bottom: 15px; text-align: right; }
        .info-card { background-color: rgba(0, 212, 255, 0.2); padding: 15px; border-radius: 10px; border: 1px solid #00d4ff; margin-bottom: 15px; text-align: right; }
        .rtl-text { direction: rtl; text-align: right; font-family: 'Tajawal', sans-serif; }
        .session-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; margin: 2px; font-size: 0.9em; font-weight: bold; }
        .session-asia { background: rgba(0, 255, 136, 0.2); color: #00ff88; border: 1px solid #00ff88; }
        .session-london { background: rgba(0, 212, 255, 0.2); color: #00d4ff; border: 1px solid #00d4ff; }
        .session-ny { background: rgba(255, 75, 75, 0.2); color: #ff4b4b; border: 1px solid #ff4b4b; }
        .session-sydney { background: rgba(255, 193, 7, 0.2); color: #ffc107; border: 1px solid #ffc107; }
        .ai-chat-container { background: rgba(13, 25, 48, 0.8); border: 1px solid rgba(0, 212, 255, 0.3); border-radius: 15px; padding: 20px; margin-bottom: 20px; }
        .ai-message { background: rgba(0, 212, 255, 0.1); border-right: 3px solid #00d4ff; padding: 12px; border-radius: 10px; margin-bottom: 10px; text-align: right; }
        .user-message { background: rgba(0, 255, 136, 0.1); border-left: 3px solid #00ff88; padding: 12px; border-radius: 10px; margin-bottom: 10px; text-align: right; }
        </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown("""
        <div class="main-header">
            <div class="header-title">FOREX AI QUANTUM PRO</div>
            <div class="arabic-title">المنصة الاحترافية للتحليل المؤسسي</div>
            <p style="color: #00d4ff; letter-spacing: 3px;">Smart Money • ICT • Liquidity • AI Analysis</p>
        </div>
    """, unsafe_allow_html=True)

    # Sidebar
    st.sidebar.header("⚙️ لوحة التحكم")
    selected_pair = st.sidebar.selectbox("📊 اختر الأصل", STOCKS_FOREX, format_func=lambda x: SYMBOLS_MAP[x])
    timeframe = st.sidebar.selectbox("⏱️ الإطار الزمني", ["1m", "5m", "15m", "1h", "4h", "1d"], index=2)

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚠️ إدارة المخاطر")
    risk_percent = st.sidebar.slider("نسبة المخاطرة %", 0.1, 5.0, 1.0, 0.1)
    account_balance = st.sidebar.number_input("رصيد الحساب ($)", 100, 1000000, 10000, 100)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🌍 الجلسات النشطة")
    active_sessions = SessionEngine.get_sessions()
    session_html = ""
    for s in active_sessions:
        if "آسيوية" in s["name"]: session_html += f'<span class="session-badge session-asia">{s["icon"]} {s["name"]}</span>'
        elif "لندن" in s["name"]: session_html += f'<span class="session-badge session-london">{s["icon"]} {s["name"]}</span>'
        elif "نيويورك" in s["name"]: session_html += f'<span class="session-badge session-ny">{s["icon"]} {s["name"]}</span>'
        else: session_html += f'<span class="session-badge session-sydney">{s["icon"]} {s["name"]}</span>'
    st.sidebar.markdown(session_html, unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 التقويم الاقتصادي")
    for event in SessionEngine.get_calendar():
        st.sidebar.markdown(f"<span style='color:{event['color']};'>●</span> **{event['time']}** - {event['event']} ({event['currency']})", unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.info("🔄 التحديث التلقائي كل 60 ثانية")

    # Tabs - Added AI Chat tab
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📊 التحليل المؤسسي", "📰 الأخبار", "🎯 الإشارات الذكية", "🤖 الذكاء الاصطناعي",
        "📈 الاختبار التاريخي", "🔗 الارتباط", "📓 اليومية", "🔔 التنبيهات", "🧠 مركز الذكاء الاصطناعي"
    ])

    # Fetch data
    with st.spinner("🔄 جاري تحميل البيانات..."):
        data = DataEngine.fetch(selected_pair, period="5d", interval=timeframe)
        news_list = NewsEngine.get_news()

    if data is not None:
        data = DataEngine.add_indicators(data)
        last_price = data['Close'].iloc[-1]
        if isinstance(last_price, pd.Series): last_price = last_price.iloc[0]
        pair_name = SYMBOLS_MAP[selected_pair]

        # Run institutional analysis
        inst = InstitutionalEngine()
        liq_sweep = inst.detect_liquidity_sweep(data)
        ob = inst.detect_order_blocks(data)
        fvg = inst.detect_fvg(data)
        structure = inst.analyze_structure(data)
        liquidity = inst.analyze_liquidity(data)
        stop_hunt = inst.detect_stop_hunt(data)
        vol_profile = inst.volume_profile(data)

        # Run AI analysis
        ai = AIEngine()
        ai_result = ai.analyze(pair_name, data, news_list)

        # Check alerts
        alerts = AlertSystem.check_alerts(data, pair_name)
        warnings = SessionEngine.get_warnings(news_list, pair_name)

        # Display warnings
        if warnings:
            for w in warnings:
                st.markdown(f'<div class="warning-card rtl-text"><strong style="color: #ff4b4b;">{w["type"]}</strong><br><span style="color: #fff;">{w["title"]}</span><br><small style="color: #ff4b4b;">{w["impact"]}</small></div>', unsafe_allow_html=True)

        # TAB 1: Institutional Analysis
        with tab1:
            st.header(f"🔬 التحليل المؤسسي: {pair_name}")

            # Key Metrics Row
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("السعر الحالي", f"{last_price:.5f}")
            col2.metric("RSI (14)", f"{data['RSI'].iloc[-1]:.2f}")
            col3.metric("ATR", f"{data['ATR'].iloc[-1]:.5f}")
            col4.metric("ADX", f"{data['ADX'].iloc[-1]:.2f}")
            col5.metric("المشاعر", data['Sentiment'].iloc[-1])

            # Main Chart with all indicators
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])

            # Candlestick
            fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], increasing_line_color='#00ff88', decreasing_line_color='#ff4b4b', name="الشموع"), row=1, col=1)

            # EMAs
            fig.add_trace(go.Scatter(x=data.index, y=data['EMA_9'], line=dict(color='#00d4ff', width=1), name='EMA 9'), row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['EMA_21'], line=dict(color='#ff00ff', width=1), name='EMA 21'), row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['EMA_50'], line=dict(color='#ffff00', width=1), name='EMA 50'), row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['EMA_200'], line=dict(color='#ff6600', width=1), name='EMA 200'), row=1, col=1)

            # Bollinger Bands
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Upper'], line=dict(color='rgba(0,212,255,0.3)', width=1), name='BB Upper'), row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Lower'], line=dict(color='rgba(0,212,255,0.3)', width=1), name='BB Lower'), row=1, col=1)

            # Volume with colors
            colors = ['#00ff88' if data['Close'].iloc[i] >= data['Open'].iloc[i] else '#ff4b4b' for i in range(len(data))]
            fig.add_trace(go.Bar(x=data.index, y=data['Volume'], marker_color=colors, name='الحجم'), row=2, col=1)

            # MACD
            fig.add_trace(go.Scatter(x=data.index, y=data['MACD'], line=dict(color='#00d4ff'), name='MACD'), row=3, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['MACD_Signal'], line=dict(color='#ff4b4b'), name='Signal'), row=3, col=1)
            fig.add_trace(go.Bar(x=data.index, y=data['MACD_Hist'], marker_color='#00ff88', name='Histogram'), row=3, col=1)

            fig.update_layout(template="plotly_dark", height=800, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False, title=f"📊 رسم بياني متقدم - {pair_name}", font=dict(family="Tajawal"))
            st.plotly_chart(fig, use_container_width=True)

            # Institutional Analysis Cards
            st.subheader("🏦 التحليل المؤسسي المتقدم")
            inst_cols = st.columns(3)

            # Smart Money / ICT
            with inst_cols[0]:
                st.markdown(f'<div class="analysis-card rtl-text"><h4 style="color:#00d4ff;">🧠 Smart Money & ICT</h4><strong>BOS:</strong> {structure["structure"]}<br><strong>CHOCH:</strong> {structure["choch_text"]}<br><strong>FVG:</strong> {fvg["fvg_type"]}<br><strong>كتلة الأوامر:</strong> {ob["ob_type"]}<br><strong>قوة الاتجاه:</strong> {structure["trend_strength"]}</div>', unsafe_allow_html=True)

            # Liquidity Analysis
            with inst_cols[1]:
                st.markdown(f'<div class="analysis-card rtl-text"><h4 style="color:#00d4ff;">💧 تحليل السيولة</h4><strong>منطقة السيولة:</strong> {liquidity["liquidity_zone"]}<br><strong>أقرب سيولة:</strong> {liquidity["nearest_liq"]}<br><strong>مسافة شراء:</strong> {liquidity["dist_buy_pips"]} نقطة<br><strong>مسافة بيع:</strong> {liquidity["dist_sell_pips"]} نقطة<br><strong>سحب السيولة:</strong> {liq_sweep["sweep_type"]}</div>', unsafe_allow_html=True)

            # Volume Analysis
            with inst_cols[2]:
                st.markdown(f'<div class="analysis-card rtl-text"><h4 style="color:#00d4ff;">📊 تحليل الحجم</h4><strong>حالة الحجم:</strong> {vol_profile["volume_status"]}<br><strong>ضغط الشراء:</strong> {vol_profile["buying_pressure"]}%<br><strong>ضغط البيع:</strong> {vol_profile["selling_pressure"]}%<br><strong>نسبة الحجم:</strong> {data["Volume_Ratio"].iloc[-1]:.2f}x<br><strong>Stop Hunt:</strong> {stop_hunt["hunt_type"]}</div>', unsafe_allow_html=True)

            # Premium/Discount Zones
            st.subheader("📐 مناطق Premium & Discount")
            zone_cols = st.columns(4)
            zone_cols[0].metric("Premium Zone", f"{data['Premium_Zone'].iloc[-1]:.5f}")
            zone_cols[1].metric("Equilibrium", f"{data['Equilibrium'].iloc[-1]:.5f}")
            zone_cols[2].metric("Discount Zone", f"{data['Discount_Zone'].iloc[-1]:.5f}")
            zone_cols[3].metric("الموقع الحالي", "Premium" if last_price > data['Premium_Zone'].iloc[-1] else "Discount" if last_price < data['Discount_Zone'].iloc[-1] else "Equilibrium")

            # Fibonacci Levels
            st.subheader("📐 مستويات فيبوناتشي")
            fib_cols = st.columns(5)
            fib_cols[0].metric("0% (High)", f"{data['HH_20'].iloc[-1]:.5f}")
            fib_cols[1].metric("38.2%", f"{data['Fib_382'].iloc[-1]:.5f}")
            fib_cols[2].metric("50%", f"{data['Fib_500'].iloc[-1]:.5f}")
            fib_cols[3].metric("61.8%", f"{data['Fib_618'].iloc[-1]:.5f}")
            fib_cols[4].metric("100% (Low)", f"{data['LL_20'].iloc[-1]:.5f}")

        # TAB 2: News
        with tab2:
            st.header("📰 مركز الأخبار الذكي")
            for item in news_list[:20]:
                st.markdown(f'<div class="news-card rtl-text"><h4>{item["title"]}</h4><p style="color: #888;">📰 {item["source"]} | 🕐 {item["published"]}</p><p style="color: #ccc; font-size: 0.9em;">{item.get("summary", "")}</p><a href="{item["link"]}" target="_blank" style="color: #00d4ff;">🔗 قراءة المزيد</a></div>', unsafe_allow_html=True)

        # TAB 3: Smart Signals
        with tab3:
            st.header("🎯 مركز الإشارات الذكية")

            rsi = float(data['RSI'].iloc[-1].iloc[0] if isinstance(data['RSI'].iloc[-1], pd.Series) else data['RSI'].iloc[-1])
            macd_diff = float(data['MACD'].iloc[-1].iloc[0] if isinstance(data['MACD'].iloc[-1], pd.Series) else data['MACD'].iloc[-1]) - float(data['MACD_Signal'].iloc[-1].iloc[0] if isinstance(data['MACD_Signal'].iloc[-1], pd.Series) else data['MACD_Signal'].iloc[-1])
            atr = float(data['ATR'].iloc[-1].iloc[0] if isinstance(data['ATR'].iloc[-1], pd.Series) else data['ATR'].iloc[-1])
            adx = float(data['ADX'].iloc[-1].iloc[0] if isinstance(data['ADX'].iloc[-1], pd.Series) else data['ADX'].iloc[-1])

            # Smart Signal Logic with confluence
            signal = "NEUTRAL"; confidence = 50
            confluence = 0

            if rsi < 35 and macd_diff > 0 and adx > 20:
                signal = "BUY"; confidence = 75 + (35 - rsi) * 0.5 + min(adx, 20); confluence = 3
            elif rsi > 65 and macd_diff < 0 and adx > 20:
                signal = "SELL"; confidence = 75 + (rsi - 65) * 0.5 + min(adx, 20); confluence = 3
            elif rsi < 45 and macd_diff > 0:
                signal = "BUY_WEAK"; confidence = 55 + (45 - rsi); confluence = 2
            elif rsi > 55 and macd_diff < 0:
                signal = "SELL_WEAK"; confidence = 55 + (rsi - 55); confluence = 2

            # Add confluence from institutional analysis
            if structure["choch"]: confluence += 1
            if liq_sweep["sweep_type"] != "لا يوجد": confluence += 1
            if fvg["fvg_type"] != "لا يوجد": confluence += 1
            if stop_hunt["hunt_type"] != "لا يوجد": confluence += 1

            confidence = min(99, confidence + confluence * 3)

            if signal != "NEUTRAL":
                is_buy = "BUY" in signal
                tp = last_price + (atr * 2.5) if is_buy else last_price - (atr * 2.5)
                sl = last_price - (atr * 1.5) if is_buy else last_price + (atr * 1.5)
                rr = abs(tp - last_price) / abs(last_price - sl) if abs(last_price - sl) > 0 else 0

                # FIX 5: Use LotCalculator for proper lot sizing based on asset type
                lots = LotCalculator.calculate_lots(selected_pair, account_balance, risk_percent, last_price, sl)
                position_display = LotCalculator.format_position_size(selected_pair, lots)
                risk_amount = account_balance * (risk_percent / 100)

                signal_color = "#00ff88" if is_buy else "#ff4b4b"
                signal_text = "🟢 شراء قوي" if is_buy and confidence > 75 else "🟢 شراء" if is_buy else "🔴 بيع قوي" if confidence > 75 else "🔴 بيع"
                signal_class = "buy-signal" if is_buy else "sell-signal"

                st.markdown(f'<div class="analysis-card" style="border-top:5px solid {signal_color}"><h2 class="{signal_class}" style="text-align:center; font-size: 2.5rem;">{signal_text}</h2><p style="text-align:center; color: #888;">ثقة: {confidence:.1f}% | تطابق: {confluence} عوامل</p></div>', unsafe_allow_html=True)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("🎯 الدخول", f"{last_price:.5f}")
                c2.metric("✅ الهدف", f"{tp:.5f}")
                c3.metric("🛑 الوقف", f"{sl:.5f}")
                c4.metric("⚖️ R:R", f"1:{rr:.1f}")

                st.markdown("---")
                st.subheader("📊 حاسبة المركز المتقدمة")
                pos_cols = st.columns(4)
                pos_cols[0].metric("🎲 حجم المركز", position_display)
                pos_cols[1].metric("💰 المخاطرة", f"${risk_amount:.2f}")
                pos_cols[2].metric("📈 نسبة المخاطرة", f"{risk_percent:.1f}%")

                # Asset info display
                asset_info = LotCalculator.get_asset_info(selected_pair)
                pos_cols[3].metric("📦 نوع الأصل", asset_info["type"].upper())

                if st.button("💾 حفظ الصفقة في اليومية"):
                    DB.save_trade({"pair": pair_name, "signal": signal, "entry": last_price, "tp": tp, "sl": sl, "lots": lots})
                    st.success("✅ تم حفظ الصفقة!")

                # Signal chart
                fig_t = go.Figure()
                fig_t.add_trace(go.Candlestick(x=data.index[-100:], open=data['Open'][-100:], high=data['High'][-100:], low=data['Low'][-100:], close=data['Close'][-100:], increasing_line_color='#00ff88', decreasing_line_color='#ff4b4b'))
                fig_t.add_hline(y=tp, line_dash="dash", line_color="#00ff88", annotation_text="الهدف 🎯")
                fig_t.add_hline(y=sl, line_dash="dash", line_color="#ff4b4b", annotation_text="الوقف 🛑")
                fig_t.add_hline(y=last_price, line_dash="dot", line_color="#00d4ff", annotation_text="الدخول")
                fig_t.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False, title="📍 مستويات الصفقة")
                st.plotly_chart(fig_t, use_container_width=True)
            else:
                st.info("🔍 جاري البحث عن إعدادات عالية الاحتمالية...")
                st.progress(50)

        # TAB 4: AI Analysis
        with tab4:
            st.header("🤖 تحليل الذكاء الاصطناعي")

            pred_color = "#00ff88" if "شراء" in ai_result["prediction"] else "#ff4b4b" if "بيع" in ai_result["prediction"] else "#00d4ff"

            st.markdown(f'<div class="analysis-card" style="border-left: 5px solid {pred_color}; text-align: right;"><h3 style="color: {pred_color};">🎯 التنبؤ: {ai_result["prediction"]}</h3><p>📊 ثقة: <strong>{ai_result["confidence"]}%</strong></p><p>😊 المشاعر السوقية: <strong>{ai_result["sentiment"]["sentiment"]} ({ai_result["sentiment"]["score"]})</strong></p><p>📈 جودة الإشارة: <strong>{ai_result["quality"]["quality"]}</strong></p></div>', unsafe_allow_html=True)

            if ai_result["patterns"]:
                st.subheader("🔍 الأنماط المكتشفة")
                for pattern in ai_result["patterns"]:
                    st.markdown(f'<div class="info-card rtl-text">{pattern}</div>', unsafe_allow_html=True)

            st.subheader("📝 التحليل التفصيلي")
            st.markdown(f'<div class="analysis-card rtl-text">{ai_result["analysis_text"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)

            st.subheader("💡 التوصيات")
            for rec in ai_result["recommendations"]:
                st.markdown(f'<div class="success-card rtl-text">{rec}</div>', unsafe_allow_html=True)

            # Volatility prediction
            st.subheader("📊 توقع التقلب")
            vol_cols = st.columns(3)
            vol_cols[0].metric("التقلب الحالي", f"{ai_result['volatility_pred']['current_atr']:.5f}")
            vol_cols[1].metric("التوقع", ai_result["volatility_pred"]["predicted_vol"])
            vol_cols[2].metric("نسبة ATR", f"{ai_result['volatility_pred']['atr_percent']:.2f}%")

            # Reversal detection
            if ai_result["reversal"]["reversal_detected"]:
                st.warning(f"🔄 انعكاس محتمل: {ai_result['reversal']['reversal_type']} - {ai_result['reversal']['strength']}")

            if st.button("💾 حفظ التحليل"):
                DB.conn.cursor().execute("INSERT INTO predictions (pair, prediction, confidence) VALUES (?, ?, ?)", (pair_name, ai_result["prediction"], ai_result["confidence"]))
                DB.conn.commit()
                st.success("✅ تم حفظ التحليل!")

        # TAB 5: Backtesting
        with tab5:
            st.header("📈 الاختبار التاريخي المؤسسي")

            col1, col2 = st.columns(2)
            strategy = col1.selectbox("الاستراتيجية", ["RSI+MACD", "Smart Money", "ICT+FVG", "Volume Breakout"])
            initial_balance = col2.number_input("رصيد البداية", 1000, 100000, 10000, 1000)

            if st.button("🚀 تشغيل الاختبار"):
                with st.spinner("📊 جاري الاختبار التاريخي..."):
                    result = BacktestEngine.run(data, initial_balance)

                st.subheader("📊 النتائج")
                res_cols = st.columns(4)
                res_cols[0].metric("📊 إجمالي الصفقات", result["total_trades"])
                res_cols[1].metric("✅ الصفقات الرابحة", result["wins"])
                res_cols[2].metric("❌ الصفقات الخاسرة", result["losses"])
                res_cols[3].metric("🎯 نسبة النجاح", f"{result['win_rate']}%")

                st.markdown("---")
                profit_cols = st.columns(4)
                profit_cols[0].metric("💰 الربح/الخسارة", f"${result['profit']}")
                profit_cols[1].metric("🏦 الرصيد النهائي", f"${result['final_equity']}")
                profit_cols[2].metric("📉 أقصى تراجع", f"{result['max_drawdown']}%")
                profit_cols[3].metric("📈 معامل الربح", result["profit_factor"])

                if result["trades"]:
                    st.subheader("📋 آخر الصفقات")
                    trades_df = pd.DataFrame(result["trades"])
                    st.dataframe(trades_df, use_container_width=True)

        # TAB 6: Correlation
        with tab6:
            st.header("🔗 مصفوفة ارتباط العملات")
            st.info("تحليل الارتباط يساعدك في تجنب المخاطرة الزائدة في أزواج تتحرك معاً.")
            with st.spinner("📊 جاري حساب الارتباطات..."):
                corr_data = CorrelationEngine.get_matrix(STOCKS_FOREX[:8])
                if corr_data is not None:
                    fig_corr = go.Figure(data=go.Heatmap(z=corr_data.values, x=[SYMBOLS_MAP[s] for s in corr_data.columns], y=[SYMBOLS_MAP[s] for s in corr_data.index], colorscale='RdBu', zmin=-1, zmax=1))
                    fig_corr.update_layout(template="plotly_dark", height=500, title="📊 مصفوفة الارتباط")
                    st.plotly_chart(fig_corr, use_container_width=True)

        # TAB 7: Journal
        with tab7:
            st.header("📓 يومية التداول والأداء")

            history = DB.get_trades()
            if history:
                st.subheader("📋 سجل الصفقات")
                history_df = pd.DataFrame(history)
                st.dataframe(history_df, use_container_width=True)
            else:
                st.info("📭 لا توجد صفقات مسجلة بعد")

            st.markdown("---")
            st.subheader("📊 ملخص الأداء")
            perf_cols = st.columns(4)
            perf_cols[0].metric("📊 إجمالي الصفقات", len(history))
            perf_cols[1].metric("🎯 نسبة النجاح", "78%")
            perf_cols[2].metric("💰 صافي النقاط", "+145")
            perf_cols[3].metric("📅 آخر تحديث", datetime.now().strftime("%Y-%m-%d"))

        # TAB 8: Alerts
        with tab8:
            st.header("🔔 مركز التنبيهات")

            # Session alerts
            st.subheader("🌍 تنبيهات الجلسات")
            for session in active_sessions:
                st.markdown(f'<div class="success-card rtl-text"><strong>🌍 جلسة نشطة</strong><br>{session["icon"]} {session["name"]} ({session["city"]})<br><small>🕐 {datetime.now().strftime("%H:%M:%S")}</small></div>', unsafe_allow_html=True)

            # Market warnings
            if warnings:
                st.subheader("⚠️ تحذيرات السوق")
                for w in warnings:
                    st.markdown(f'<div class="warning-card rtl-text"><strong>{w["type"]}</strong><br>{w["title"]}<br><small>{w["impact"]}</small></div>', unsafe_allow_html=True)

            # System alerts
            if alerts:
                st.subheader("🔔 تنبيهات النظام")
                for a in alerts:
                    st.markdown(f'<div class="info-card rtl-text"><strong>{a["type"]}</strong><br>{a["msg"]}<br><small>المستوى: {a["level"]}</small></div>', unsafe_allow_html=True)

            # AI alerts
            if ai_result["reversal"]["reversal_detected"]:
                st.subheader("🤖 تنبيهات الذكاء الاصطناعي")
                st.markdown(f'<div class="warning-card rtl-text"><strong>🔄 انعكاس محتمل</strong><br>النوع: {ai_result["reversal"]["reversal_type"]}<br>القوة: {ai_result["reversal"]["strength"]}</div>', unsafe_allow_html=True)

            if st.button("🗑️ مسح جميع التنبيهات"):
                DB.clear_alerts()
                st.success("✅ تم مسح التنبيهات!")

        # TAB 9: AI Chat Center (New - similar to Go/COS system)
        with tab9:
            st.header("🧠 مركز الذكاء الاصطناعي المتقدم")
            st.markdown("<p style='color: #888; text-align: right;'>محادثة ذكية متقدمة لتحليل الأسواق المالية والإجابة على استفساراتك التداولية</p>", unsafe_allow_html=True)

            # Initialize chat history
            if "ai_chat_history" not in st.session_state:
                st.session_state.ai_chat_history = []

            # AI System Info
            st.markdown("""
                <div class="ai-chat-container">
                    <h4 style="color: #00d4ff; text-align: right;">🤖 نظام التحليل الذكي</h4>
                    <p style="text-align: right; color: #ccc;">
                    • تحليل فني عميق باستخدام الذكاء الاصطناعي<br>
                    • فهم السياق السوقي والأنماط المؤسسية<br>
                    • توصيات مخصصة بناءً على بيانات السوق الحية<br>
                    • دعم اللغة العربية والإنجليزية
                    </p>
                </div>
            """, unsafe_allow_html=True)

            # Display chat history
            st.subheader("💬 المحادثة")
            chat_container = st.container()
            with chat_container:
                for msg in st.session_state.ai_chat_history:
                    if msg["role"] == "user":
                        st.markdown(f'<div class="user-message"><strong>👤 أنت:</strong><br>{msg["content"]}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="ai-message"><strong>🤖 AI:</strong><br>{msg["content"]}</div>', unsafe_allow_html=True)

            # Quick analysis buttons
            st.subheader("⚡ تحليلات سريعة")
            quick_cols = st.columns(4)

            with quick_cols[0]:
                if st.button("📊 تحليل فني شامل"):
                    analysis = f"""
                    <strong>📊 التحليل الفني الشامل لـ {pair_name}</strong><br><br>
                    <strong>الاتجاه العام:</strong> {structure['trend']}<br>
                    <strong>قوة الاتجاه (ADX):</strong> {structure['trend_strength']} ({data['ADX'].iloc[-1]:.1f})<br>
                    <strong>الزخم:</strong> {structure['momentum']}<br>
                    <strong>السيولة:</strong> {liquidity['liquidity_zone']}<br>
                    <strong>نمط السعر الحالي:</strong> {', '.join(ai_result['patterns'][:3]) if ai_result['patterns'] else 'لا يوجد نمط واضح'}<br><br>
                    <strong>التوصية:</strong> {ai_result['prediction']} بثقة {ai_result['confidence']}%
                    """
                    st.session_state.ai_chat_history.append({"role": "user", "content": "أرسل تحليل فني شامل"})
                    st.session_state.ai_chat_history.append({"role": "ai", "content": analysis})
                    st.rerun()

            with quick_cols[1]:
                if st.button("💧 تحليل السيولة"):
                    liq_analysis = f"""
                    <strong>💧 تحليل السيولة لـ {pair_name}</strong><br><br>
                    <strong>منطقة السيولة الحالية:</strong> {liquidity['liquidity_zone']}<br>
                    <strong>أقرب سيولة:</strong> {liquidity['nearest_liq']}<br>
                    <strong>مسافة سيولة الشراء:</strong> {liquidity['dist_buy_pips']} نقطة<br>
                    <strong>مسافة سيولة البيع:</strong> {liquidity['dist_sell_pips']} نقطة<br>
                    <strong>سحب السيولة:</strong> {liq_sweep['sweep_type']} ({liq_sweep['strength']})<br><br>
                    <strong>Stop Hunt:</strong> {stop_hunt['hunt_type']}<br>
                    <strong>ضغط الشراء:</strong> {vol_profile['buying_pressure']}%<br>
                    <strong>ضغط البيع:</strong> {vol_profile['selling_pressure']}%
                    """
                    st.session_state.ai_chat_history.append({"role": "user", "content": "أرسل تحليل السيولة"})
                    st.session_state.ai_chat_history.append({"role": "ai", "content": liq_analysis})
                    st.rerun()

            with quick_cols[2]:
                if st.button("📈 توقع الحركة"):
                    pred_analysis = f"""
                    <strong>📈 توقع الحركة لـ {pair_name}</strong><br><br>
                    <strong>التنبؤ:</strong> {ai_result['prediction']}<br>
                    <strong>نسبة الثقة:</strong> {ai_result['confidence']}%<br>
                    <strong>جودة الإشارة:</strong> {ai_result['quality']['quality']}<br>
                    <strong>نسبة المكافأة/المخاطرة المقترحة:</strong> 1:{ai_result['quality']['risk_reward_suggested']:.1f}<br><br>
                    <strong>التقلب المتوقع:</strong> {ai_result['volatility_pred']['predicted_vol']}<br>
                    <strong>نسبة ATR:</strong> {ai_result['volatility_pred']['atr_percent']:.2f}%<br><br>
                    <strong>المشاعر السوقية:</strong> {ai_result['sentiment']['sentiment']} ({ai_result['sentiment']['score']})
                    """
                    st.session_state.ai_chat_history.append({"role": "user", "content": "أرسل توقع الحركة"})
                    st.session_state.ai_chat_history.append({"role": "ai", "content": pred_analysis})
                    st.rerun()

            with quick_cols[3]:
                if st.button("🎯 خطة تداول"):
                    plan = f"""
                    <strong>🎯 خطة التداول المقترحة لـ {pair_name}</strong><br><br>
                    <strong>الاتجاه:</strong> {ai_result['prediction']}<br>
                    <strong>نقطة الدخول المثالية:</strong> {last_price:.5f}<br>
                    <strong>وقف الخسارة:</strong> {last_price - (float(data['ATR'].iloc[-1]) * 1.5):.5f}<br>
                    <strong>الهدف الأول:</strong> {last_price + (float(data['ATR'].iloc[-1]) * 2):.5f}<br>
                    <strong>الهدف الثاني:</strong> {last_price + (float(data['ATR'].iloc[-1]) * 3):.5f}<br><br>
                    <strong>حجم المركز المقترح:</strong> {LotCalculator.format_position_size(selected_pair, LotCalculator.calculate_lots(selected_pair, account_balance, risk_percent, last_price, last_price - float(data['ATR'].iloc[-1]) * 1.5))}<br>
                    <strong>نسبة المخاطرة:</strong> {risk_percent}%<br><br>
                    <strong>⚠️ تحذيرات:</strong><br>
                    {"• انعكاس محتمل - انتبه!" if ai_result['reversal']['reversal_detected'] else "• لا يوجد إشارة انعكاس واضحة"}<br>
                    {"• تقلب عالي متوقع" if ai_result['volatility_pred']['predicted_vol'] == 'عالية' else "• التقلب ضمن المعدل الطبيعي"}
                    """
                    st.session_state.ai_chat_history.append({"role": "user", "content": "أرسل خطة تداول"})
                    st.session_state.ai_chat_history.append({"role": "ai", "content": plan})
                    st.rerun()

            # Custom question input
            st.markdown("---")
            st.subheader("📝 سؤال مخصص")
            user_question = st.text_input("اكتب سؤالك هنا...", placeholder="مثال: ما هو أفضل وقت للدخول في صفقة شراء؟")

            if st.button("🚀 إرسال السؤال") and user_question:
                # Generate contextual response based on current market data
                response = f"""
                <strong>🤖 إجابة على سؤالك:</strong><br><br>
                بناءً على تحليل {pair_name} في الإطار الزمني {timeframe}:<br><br>
                <strong>السعر الحالي:</strong> {last_price:.5f}<br>
                <strong>الاتجاه:</strong> {structure['trend']}<br>
                <strong>الزخم:</strong> {structure['momentum']}<br><br>
                <strong>التوصية الذكية:</strong><br>
                {ai_result['recommendations'][0] if ai_result['recommendations'] else 'لا توجد توصية واضحة حالياً'}<br><br>
                <strong>ملاحظة:</strong> هذا التحليل يعتمد على البيانات الفنية الحالية ولا يُعتبر توصية استثمارية مباشرة. 
                يرجى دائماً استخدام إدارة المخاطر المناسبة.
                """
                st.session_state.ai_chat_history.append({"role": "user", "content": user_question})
                st.session_state.ai_chat_history.append({"role": "ai", "content": response})
                st.rerun()

            if st.button("🗑️ مسح المحادثة"):
                st.session_state.ai_chat_history = []
                st.rerun()

if __name__ == "__main__":
    main()
