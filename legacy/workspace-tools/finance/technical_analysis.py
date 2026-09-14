#!/usr/bin/env python3
"""
Technical Analysis for Elysia Finance
Stock indicators, chart patterns, trading signals.
"""
import json
import sys
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class TechnicalIndicators:
    """Calculate technical analysis indicators."""

    @staticmethod
    def sma(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        return [sum(prices[i-period+1:i+1]) / period for i in range(period-1, len(prices))]

    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema_values = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26) -> Dict[str, float]:
        if len(prices) < slow:
            return {"macd": 0, "signal": 0, "histogram": 0}
        fast_ema = TechnicalIndicators.ema(prices, fast)
        slow_ema = TechnicalIndicators.ema(prices, slow)
        if not fast_ema or not slow_ema:
            return {"macd": 0, "signal": 0, "histogram": 0}
        macd_line = fast_ema[-1] - slow_ema[-1] if fast_ema and slow_ema else 0
        return {"macd": macd_line, "signal": 0, "histogram": macd_line}

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        if len(prices) < period:
            return {"upper": 0, "middle": 0, "lower": 0}
        recent = prices[-period:]
        middle = sum(recent) / period
        variance = sum((p - middle) ** 2 for p in recent) / period
        std = variance ** 0.5
        return {"upper": middle + std_dev * std, "middle": middle, "lower": middle - std_dev * std}

    @staticmethod
    def stochastic(high: float, low: float, close: float, period: int = 14,
                   prices: List[float] = None) -> Dict[str, float]:
        if prices and len(prices) >= period:
            recent_high = max(prices[-period:])
            recent_low = min(prices[-period:])
        else:
            recent_high, recent_low = high, low
        if recent_high == recent_low:
            k = 50
        else:
            k = ((close - recent_low) / (recent_high - recent_low)) * 100
        return {"k": k, "d": k}

    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(highs) < period + 1:
            return 0
        trs = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return sum(trs[-period:]) / period

    @staticmethod
    def obv(closes: List[float], volumes: List[float]) -> List[float]:
        if not closes or not volumes or len(closes) != len(volumes):
            return []
        obv_values = [0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv_values.append(obv_values[-1] + volumes[i])
            elif closes[i] < closes[i-1]:
                obv_values.append(obv_values[-1] - volumes[i])
            else:
                obv_values.append(obv_values[-1])
        return obv_values


class ChartPatterns:
    """Detect common chart patterns."""

    @staticmethod
    def detect_support_resistance(prices: List[float]) -> Dict[str, Any]:
        if len(prices) < 5:
            return {"support": 0, "resistance": 0}
        sorted_prices = sorted(prices)
        support = sorted_prices[len(sorted_prices) // 4]
        resistance = sorted_prices[3 * len(sorted_prices) // 4]
        return {"support": support, "resistance": resistance}

    @staticmethod
    def detect_trend(prices: List[float]) -> str:
        if len(prices) < 10:
            return "insufficient_data"
        recent = prices[-10:]
        slope = (recent[-1] - recent[0]) / len(recent)
        avg = sum(recent) / len(recent)
        pct_change = slope / avg * 100 if avg != 0 else 0
        if pct_change > 1:
            return "strong_uptrend"
        elif pct_change > 0.3:
            return "uptrend"
        elif pct_change < -1:
            return "strong_downtrend"
        elif pct_change < -0.3:
            return "downtrend"
        return "sideways"

    @staticmethod
    def detect_divergence(prices: List[float], indicator: List[float]) -> str:
        if len(prices) < 10 or len(indicator) < 10:
            return "insufficient_data"
        price_trend = prices[-1] - prices[-5]
        ind_trend = indicator[-1] - indicator[-5]
        if price_trend > 0 and ind_trend < 0:
            return "bearish_divergence"
        elif price_trend < 0 and ind_trend > 0:
            return "bullish_divergence"
        return "no_divergence"


class TradingSignals:
    """Generate trading signals from indicators."""

    @staticmethod
    def generate_signals(prices: List[float]) -> List[Dict[str, Any]]:
        signals = []
        if len(prices) < 20:
            return signals

        rsi = TechnicalIndicators.rsi(prices)
        sma20 = TechnicalIndicators.sma(prices, 20)
        trend = ChartPatterns.detect_trend(prices)

        if rsi < 30:
            signals.append({"type": "BUY", "reason": f"RSI oversold ({rsi:.1f})", "confidence": 0.7})
        elif rsi > 70:
            signals.append({"type": "SELL", "reason": f"RSI overbought ({rsi:.1f})", "confidence": 0.7})

        if sma20 and prices[-1] > sma20[-1] and trend in ["uptrend", "strong_uptrend"]:
            signals.append({"type": "BUY", "reason": "Price above SMA20 in uptrend", "confidence": 0.6})
        elif sma20 and prices[-1] < sma20[-1] and trend in ["downtrend", "strong_downtrend"]:
            signals.append({"type": "SELL", "reason": "Price below SMA20 in downtrend", "confidence": 0.6})

        return signals

    @staticmethod
    def calculate_position_size(capital: float, risk_pct: float, entry_price: float,
                                stop_loss: float) -> float:
        risk_amount = capital * (risk_pct / 100)
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return 0
        return int(risk_amount / risk_per_share)


def main():
    if len(sys.argv) < 2:
        print("Technical Analysis")
        print("=" * 40)
        print("\nCommands:")
        print("  indicators <prices_json>   - Calculate indicators")
        print("  trend <prices_json>        - Detect trend")
        print("  signals <prices_json>      - Generate signals")
        print("  position <cap> <risk%> <entry> <stop> - Position size")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "indicators" and len(sys.argv) >= 3:
        prices = json.loads(sys.argv[2])
        print(f"RSI: {TechnicalIndicators.rsi(prices):.1f}")
        print(f"SMA20: {TechnicalIndicators.sma(prices, 20)[-1]:.2f}" if TechnicalIndicators.sma(prices, 20) else "SMA20: N/A")
        print(f"Trend: {ChartPatterns.detect_trend(prices)}")
        bb = TechnicalIndicators.bollinger_bands(prices)
        print(f"Bollinger: Upper={bb['upper']:.2f} Middle={bb['middle']:.2f} Lower={bb['lower']:.2f}")

    elif cmd == "trend" and len(sys.argv) >= 3:
        prices = json.loads(sys.argv[2])
        print(f"Trend: {ChartPatterns.detect_trend(prices)}")

    elif cmd == "signals" and len(sys.argv) >= 3:
        prices = json.loads(sys.argv[2])
        signals = TradingSignals.generate_signals(prices)
        for s in signals:
            print(f"  [{s['type']}] {s['reason']} (confidence: {s['confidence']:.0%})")
        if not signals:
            print("  No signals")

    elif cmd == "position" and len(sys.argv) >= 6:
        size = TradingSignals.calculate_position_size(
            float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]))
        print(f"Position size: {size} shares")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
