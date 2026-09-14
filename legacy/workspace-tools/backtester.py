#!/usr/bin/env python3
"""Task #26: Backtesting framework."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

class Backtester:
    def __init__(self, initial_capital=10000):
        self.initial_capital = initial_capital

    def run(self, prices, strategy_func, **kwargs):
        """Run backtest with given strategy."""
        capital = self.initial_capital
        position = 0
        trades = []
        equity = [capital]
        for i in range(1, len(prices)):
            signal = strategy_func(prices[:i+1], **kwargs)
            if signal == "buy" and position == 0:
                shares = int(capital / prices[i])
                position = shares
                capital -= shares * prices[i]
                trades.append({"type": "buy", "price": prices[i], "shares": shares, "date": i})
            elif signal == "sell" and position > 0:
                capital += position * prices[i]
                trades.append({"type": "sell", "price": prices[i], "shares": position, "date": i, "pnl": (prices[i] - trades[-1]["price"]) * position})
                position = 0
            equity.append(capital + position * prices[i])
        total_return = (equity[-1] - self.initial_capital) / self.initial_capital * 100
        max_drawdown = min((equity[i] - max(equity[:i+1])) / max(equity[:i+1]) * 100 for i in range(1, len(equity)))
        win_trades = [t for t in trades if t.get("pnl", 0) > 0]
        return {
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "total_trades": len(trades),
            "win_rate": round(len(win_trades) / len(trades) * 100, 1) if trades else 0,
            "final_equity": round(equity[-1], 2),
            "trades": trades
        }

def sma_crossover_strategy(prices, fast=20, slow=50):
    """Simple SMA crossover strategy."""
    if len(prices) < slow:
        return "hold"
    fast_ma = sum(prices[-fast:]) / fast
    slow_ma = sum(prices[-slow:]) / slow
    if fast_ma > slow_ma and sum(prices[-fast-1:-1]) / fast <= sum(prices[-slow-1:-1]) / slow:
        return "buy"
    elif fast_ma < slow_ma and sum(prices[-fast-1:-1]) / fast >= sum(prices[-slow-1:-1]) / slow:
        return "sell"
    return "hold"

if __name__ == "__main__":
    import random
    prices = [100]
    for _ in range(251):
        prices.append(prices[-1] * (1 + random.uniform(-0.02, 0.025)))
    bt = Backtester(10000)
    result = bt.run(prices, sma_crossover_strategy)
    print("Backtest Results:")
    print(f"  Total Return: {result['total_return']}%")
    print(f"  Max Drawdown: {result['max_drawdown']}%")
    print(f"  Total Trades: {result['total_trades']}")
    print(f"  Win Rate: {result['win_rate']}%")
    print(f"  Final Equity: ${result['final_equity']:,.2f}")
    output = os.path.join(WORKSPACE, "backtest_result.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[+] Saved to {output}")
