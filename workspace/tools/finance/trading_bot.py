#!/usr/bin/env python3
"""
Trading Bot Framework for Elysia
Algorithmic trading with backtesting, live trading, and risk management.
"""
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Position:
    symbol: str
    shares: float
    entry_price: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class Trade:
    symbol: str
    side: str
    shares: float
    price: float
    timestamp: datetime
    signal: str
    pnl: float = 0.0


class RiskManager:
    """Risk management for trading."""

    def __init__(self, max_position_pct: float = 0.1,
                 max_loss_pct: float = 0.02,
                 max_daily_loss_pct: float = 0.05):
        self.max_position_pct = max_position_pct
        self.max_loss_pct = max_loss_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.daily_pnl = 0.0

    def check_position_size(self, portfolio_value: float,
                            position_value: float) -> bool:
        """Check if position size is within limits."""
        max_allowed = portfolio_value * self.max_position_pct
        return position_value <= max_allowed

    def check_stop_loss(self, entry_price: float,
                        current_price: float) -> bool:
        """Check if stop loss is hit."""
        loss_pct = (entry_price - current_price) / entry_price
        return loss_pct >= self.max_loss_pct

    def check_daily_loss(self, portfolio_value: float) -> bool:
        """Check if daily loss limit is hit."""
        max_daily_loss = portfolio_value * self.max_daily_loss_pct
        return abs(self.daily_pnl) >= max_daily_loss

    def record_trade_pnl(self, pnl: float):
        """Record trade P&L for daily tracking."""
        self.daily_pnl += pnl

    def reset_daily(self):
        """Reset daily tracking."""
        self.daily_pnl = 0.0


class Strategy:
    """Base trading strategy."""

    def __init__(self, name: str):
        self.name = name
        self.params = {}

    def analyze(self, data: List[Dict[str, Any]]) -> Signal:
        """Analyze market data and return signal."""
        raise NotImplementedError

    def backtest(self, historical_data: List[Dict[str, Any]]) -> List[Trade]:
        """Run backtest on historical data."""
        trades = []
        position = None

        for i, candle in enumerate(historical_data):
            signal = self.analyze(historical_data[:i+1])

            if signal == Signal.BUY and position is None:
                position = Position(
                    symbol=candle.get("symbol", "UNKNOWN"),
                    shares=100,
                    entry_price=candle["close"],
                    entry_time=datetime.fromisoformat(candle.get("timestamp", datetime.now().isoformat()))
                )
            elif signal == Signal.SELL and position is not None:
                trade = Trade(
                    symbol=position.symbol,
                    side="sell",
                    shares=position.shares,
                    price=candle["close"],
                    timestamp=datetime.fromisoformat(candle.get("timestamp", datetime.now().isoformat())),
                    signal=self.name,
                    pnl=(candle["close"] - position.entry_price) * position.shares
                )
                trades.append(trade)
                position = None

        return trades


class MACrossStrategy(Strategy):
    """Moving Average Crossover strategy."""

    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        super().__init__("MA_Cross")
        self.params = {"fast": fast_period, "slow": slow_period}

    def analyze(self, data: List[Dict[str, Any]]) -> Signal:
        if len(data) < self.params["slow"]:
            return Signal.HOLD

        closes = [d["close"] for d in data]
        fast_ma = sum(closes[-self.params["fast"]:]) / self.params["fast"]
        slow_ma = sum(closes[-self.params["slow"]:]) / self.params["slow"]

        if fast_ma > slow_ma:
            return Signal.BUY
        elif fast_ma < slow_ma:
            return Signal.SELL
        return Signal.HOLD


class RSIStrategy(Strategy):
    """RSI (Relative Strength Index) strategy."""

    def __init__(self, period: int = 14, overbought: float = 70,
                 oversold: float = 30):
        super().__init__("RSI")
        self.params = {"period": period, "overbought": overbought, "oversold": oversold}

    def analyze(self, data: List[Dict[str, Any]]) -> Signal:
        if len(data) < self.params["period"] + 1:
            return Signal.HOLD

        closes = [d["close"] for d in data[-(self.params["period"] + 1):]]
        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.0001

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        if rsi < self.params["oversold"]:
            return Signal.BUY
        elif rsi > self.params["overbought"]:
            return Signal.SELL
        return Signal.HOLD


class TradingBot:
    """Main trading bot controller."""

    def __init__(self, strategy: Strategy, risk_manager: RiskManager = None):
        self.strategy = strategy
        self.risk_manager = risk_manager or RiskManager()
        self.positions: List[Position] = []
        self.trades: List[Trade] = []
        self.portfolio_value = 10000.0

    def run_backtest(self, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run backtest and return results."""
        print(f"[*] Running backtest with {self.strategy.name} strategy...")

        trades = self.strategy.backtest(historical_data)

        # Calculate metrics
        total_pnl = sum(t.pnl for t in trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]

        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0

        results = {
            "strategy": self.strategy.name,
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else float("inf"),
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "price": t.price,
                    "pnl": t.pnl,
                    "timestamp": t.timestamp.isoformat()
                }
                for t in trades[:20]  # Last 20 trades
            ]
        }

        print(f"[+] Backtest complete: {len(trades)} trades, P&L: ${total_pnl:+.2f}")
        return results

    def generate_signal(self, market_data: List[Dict[str, Any]]) -> Signal:
        """Generate trading signal from market data."""
        return self.strategy.analyze(market_data)

    def execute_trade(self, signal: Signal, symbol: str,
                      price: float, shares: float) -> Optional[Trade]:
        """Execute a trade (paper or live)."""
        if signal == Signal.HOLD:
            return None

        # Risk checks
        trade_value = price * shares
        if not self.risk_manager.check_position_size(self.portfolio_value, trade_value):
            print(f"[-] Position size too large")
            return None

        trade = Trade(
            symbol=symbol,
            side="buy" if signal == Signal.BUY else "sell",
            shares=shares,
            price=price,
            timestamp=datetime.now(),
            signal=self.strategy.name
        )

        self.trades.append(trade)
        print(f"[+] Trade executed: {trade.side.upper()} {shares} {symbol} @ ${price:.2f}")
        return trade


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Trading Bot Framework")
        print("=" * 40)
        print("\nCommands:")
        print("  backtest <strategy> <data_file>  - Run backtest")
        print("  strategies                       - List strategies")
        print("  signal <strategy>                - Generate signal")
        print("\nStrategies: ma_cross, rsi")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "strategies":
        print("\nAvailable Strategies:")
        print("  ma_cross  - Moving Average Crossover")
        print("  rsi       - Relative Strength Index")

    elif cmd == "backtest" and len(sys.argv) >= 4:
        strategy_name = sys.argv[2]
        data_file = sys.argv[3]

        if strategy_name == "ma_cross":
            strategy = MACrossStrategy()
        elif strategy_name == "rsi":
            strategy = RSIStrategy()
        else:
            print(f"[-] Unknown strategy: {strategy_name}")
            return

        # Load data
        with open(data_file) as f:
            data = json.load(f)

        bot = TradingBot(strategy)
        results = bot.run_backtest(data)

        print(f"\nBacktest Results:")
        print(f"  Strategy: {results['strategy']}")
        print(f"  Total Trades: {results['total_trades']}")
        print(f"  Win Rate: {results['win_rate']:.1f}%")
        print(f"  Total P&L: ${results['total_pnl']:+.2f}")
        print(f"  Profit Factor: {results['profit_factor']:.2f}")

    else:
        print("Unknown command. Run without args for help.")


import sys
if __name__ == "__main__":
    main()
