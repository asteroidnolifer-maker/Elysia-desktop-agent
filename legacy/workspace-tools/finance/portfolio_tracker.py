#!/usr/bin/env python3
"""
Stock Portfolio Tracker for Elysia Financial Management
Real-time stock prices, P&L calculation, alerts, and historical data.
"""
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import urllib.request


class StockTracker:
    """Stock portfolio tracker with real-time data."""

    def __init__(self, portfolio_path: str = None):
        self.portfolio_path = portfolio_path or Path(__file__).parent / "portfolio.json"
        self.portfolio = self._load_portfolio()
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    def _load_portfolio(self) -> Dict[str, Any]:
        """Load portfolio from file."""
        if self.portfolio_path.exists():
            return json.loads(self.portfolio_path.read_text())
        return {
            "holdings": {},
            "transactions": [],
            "alerts": [],
            "settings": {
                "currency": "USD",
                "initial_capital": 10000.00
            }
        }

    def _save_portfolio(self):
        """Save portfolio to file."""
        self.portfolio_path.write_text(json.dumps(self.portfolio, indent=2))

    def get_stock_price(self, symbol: str) -> Dict[str, Any]:
        """Fetch current stock price (using free API)."""
        # Check cache
        if symbol in self.cache:
            cached = self.cache[symbol]
            if datetime.now().timestamp() - cached["time"] < self.cache_ttl:
                return cached["data"]

        try:
            # Using Yahoo Finance query (no API key needed)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            result = data["chart"]["result"][0]
            quote = result["meta"]
            price_data = {
                "symbol": symbol,
                "price": quote.get("regularMarketPrice", 0),
                "previous_close": quote.get("previousClose", 0),
                "currency": quote.get("currency", "USD"),
                "timestamp": datetime.now().isoformat()
            }

            # Cache it
            self.cache[symbol] = {"data": price_data, "time": datetime.now().timestamp()}
            return price_data

        except Exception as e:
            return {"symbol": symbol, "error": str(e), "price": 0}

    def add_holding(self, symbol: str, shares: float, avg_cost: float):
        """Add or update a stock holding."""
        symbol = symbol.upper()
        if symbol in self.portfolio["holdings"]:
            h = self.portfolio["holdings"][symbol]
            total_shares = h["shares"] + shares
            h["avg_cost"] = (h["avg_cost"] * h["shares"] + avg_cost * shares) / total_shares
            h["shares"] = total_shares
        else:
            self.portfolio["holdings"][symbol] = {
                "shares": shares,
                "avg_cost": avg_cost,
                "added_date": datetime.now().isoformat()
            }

        # Record transaction
        self.portfolio["transactions"].append({
            "type": "buy",
            "symbol": symbol,
            "shares": shares,
            "price": avg_cost,
            "timestamp": datetime.now().isoformat()
        })

        self._save_portfolio()
        print(f"[+] Added {shares} shares of {symbol} at ${avg_cost:.2f}")

    def remove_holding(self, symbol: str, shares: float, sell_price: float):
        """Remove shares from a holding."""
        symbol = symbol.upper()
        if symbol not in self.portfolio["holdings"]:
            print(f"[-] No holding for {symbol}")
            return False

        h = self.portfolio["holdings"][symbol]
        if shares > h["shares"]:
            print(f"[-] Not enough shares (have {h['shares']}, trying to sell {shares})")
            return False

        # Calculate profit/loss
        profit = (sell_price - h["avg_cost"]) * shares
        h["shares"] -= shares

        if h["shares"] == 0:
            del self.portfolio["holdings"][symbol]

        # Record transaction
        self.portfolio["transactions"].append({
            "type": "sell",
            "symbol": symbol,
            "shares": shares,
            "price": sell_price,
            "profit": profit,
            "timestamp": datetime.now().isoformat()
        })

        self._save_portfolio()
        print(f"[+] Sold {shares} shares of {symbol} at ${sell_price:.2f} (P&L: ${profit:+.2f})")
        return True

    def get_portfolio_value(self) -> Dict[str, Any]:
        """Calculate total portfolio value and P&L."""
        total_value = 0
        total_cost = 0
        holdings_detail = []

        for symbol, h in self.portfolio["holdings"].items():
            price_data = self.get_stock_price(symbol)
            current_price = price_data.get("price", 0)

            market_value = current_price * h["shares"]
            cost_basis = h["avg_cost"] * h["shares"]
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

            total_value += market_value
            total_cost += cost_basis

            holdings_detail.append({
                "symbol": symbol,
                "shares": h["shares"],
                "avg_cost": h["avg_cost"],
                "current_price": current_price,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct
            })

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

        return {
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "holdings": holdings_detail,
            "cash": self.portfolio["settings"]["initial_capital"] - total_cost,
            "timestamp": datetime.now().isoformat()
        }

    def set_alert(self, symbol: str, alert_type: str, target_price: float):
        """Set a price alert."""
        self.portfolio["alerts"].append({
            "symbol": symbol.upper(),
            "type": alert_type,  # "above" or "below"
            "target_price": target_price,
            "created": datetime.now().isoformat(),
            "triggered": False
        })
        self._save_portfolio()
        print(f"[+] Alert set: {symbol} {alert_type} ${target_price:.2f}")

    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check if any alerts have been triggered."""
        triggered = []
        for alert in self.portfolio["alerts"]:
            if alert["triggered"]:
                continue

            price_data = self.get_stock_price(alert["symbol"])
            current_price = price_data.get("price", 0)

            if alert["type"] == "above" and current_price >= alert["target_price"]:
                alert["triggered"] = True
                triggered.append(alert)
                print(f"[ALERT] {alert['symbol']} is above ${alert['target_price']:.2f} (now ${current_price:.2f})")
            elif alert["type"] == "below" and current_price <= alert["target_price"]:
                alert["triggered"] = True
                triggered.append(alert)
                print(f"[ALERT] {alert['symbol']} is below ${alert['target_price']:.2f} (now ${current_price:.2f})")

        if triggered:
            self._save_portfolio()
        return triggered

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get portfolio performance summary."""
        transactions = self.portfolio["transactions"]
        buys = [t for t in transactions if t["type"] == "buy"]
        sells = [t for t in transactions if t["type"] == "sell"]

        total_invested = sum(t["shares"] * t["price"] for t in buys)
        total_sold = sum(t["shares"] * t["price"] for t in sells)
        total_profit = sum(t.get("profit", 0) for t in sells)

        return {
            "total_transactions": len(transactions),
            "total_buys": len(buys),
            "total_sells": len(sells),
            "total_invested": total_invested,
            "total_sold": total_sold,
            "realized_profit": total_profit,
            "active_alerts": len([a for a in self.portfolio["alerts"] if not a["triggered"]])
        }


def main():
    """CLI entry point."""
    tracker = StockTracker()

    if len(sys.argv) < 2:
        print("Stock Portfolio Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  value              - Show portfolio value")
        print("  add <sym> <shares> <price>  - Add holding")
        print("  sell <sym> <shares> <price> - Sell holding")
        print("  alert <sym> above/below <price> - Set alert")
        print("  alerts             - Check alerts")
        print("  summary            - Performance summary")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "value":
        portfolio = tracker.get_portfolio_value()
        print(f"\nPortfolio Value: ${portfolio['total_value']:,.2f}")
        print(f"Total P&L: ${portfolio['total_pnl']:+,.2f} ({portfolio['total_pnl_pct']:+.1f}%)")
        print(f"Cash: ${portfolio['cash']:,.2f}")
        print("\nHoldings:")
        for h in portfolio["holdings"]:
            print(f"  {h['symbol']}: {h['shares']} shares @ ${h['current_price']:.2f} "
                  f"(P&L: ${h['pnl']:+,.2f} {h['pnl_pct']:+.1f}%)")

    elif cmd == "add" and len(sys.argv) >= 5:
        tracker.add_holding(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))

    elif cmd == "sell" and len(sys.argv) >= 5:
        tracker.remove_holding(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))

    elif cmd == "alert" and len(sys.argv) >= 5:
        tracker.set_alert(sys.argv[2], sys.argv[3], float(sys.argv[4]))

    elif cmd == "alerts":
        triggered = tracker.check_alerts()
        if not triggered:
            print("No alerts triggered")

    elif cmd == "summary":
        summary = tracker.get_performance_summary()
        print(f"\nPerformance Summary:")
        print(f"  Transactions: {summary['total_transactions']}")
        print(f"  Total invested: ${summary['total_invested']:,.2f}")
        print(f"  Realized profit: ${summary['realized_profit']:+,.2f}")
        print(f"  Active alerts: {summary['active_alerts']}")

    else:
        print("Unknown command. Run without args for help.")


import sys
if __name__ == "__main__":
    main()
