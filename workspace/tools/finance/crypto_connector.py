#!/usr/bin/env python3
"""
Crypto Exchange Connector for Elysia
Connect to Binance/Coinbase APIs - order placement, balance, market data.
"""
import hashlib
import hmac
import json
import time
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path


class BinanceConnector:
    """Binance exchange connector."""

    BASE_URL = "https://api.binance.com"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, params: Dict[str, Any]) -> str:
        """Create HMAC signature."""
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

    def _request(self, endpoint: str, params: Dict[str, Any] = None,
                 signed: bool = False) -> Dict[str, Any]:
        """Make API request."""
        url = f"{self.BASE_URL}{endpoint}"

        if signed and self.api_key:
            params = params or {}
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
            headers = {"X-MBX-APIKEY": self.api_key}
        else:
            headers = {}

        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def get_ticker(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """Get 24hr ticker price."""
        return self._request("/api/v3/ticker/24hr", {"symbol": symbol})

    def get_price(self, symbol: str = "BTCUSDT") -> float:
        """Get current price."""
        data = self._request("/api/v3/ticker/price", {"symbol": symbol})
        return float(data.get("price", 0))

    def get_klines(self, symbol: str = "BTCUSDT", interval: str = "1h",
                   limit: int = 100) -> List[List]:
        """Get kline/candlestick data."""
        return self._request("/api/v3/klines", {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        })

    def get_account(self) -> Dict[str, Any]:
        """Get account info (requires API key)."""
        return self._request("/api/v3/account", signed=True)

    def get_balance(self, asset: str = "USDT") -> float:
        """Get balance for specific asset."""
        account = self.get_account()
        if "balances" in account:
            for balance in account["balances"]:
                if balance["asset"] == asset:
                    return float(balance["free"])
        return 0.0

    def place_order(self, symbol: str, side: str, order_type: str,
                    quantity: float, price: float = None) -> Dict[str, Any]:
        """Place an order."""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity
        }
        if price:
            params["price"] = price
            params["timeInForce"] = "GTC"

        return self._request("/api/v3/order", params, signed=True)

    def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("/api/v3/openOrders", params, signed=True)


class CryptoPortfolio:
    """Track crypto portfolio across exchanges."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "crypto_portfolio.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """Load portfolio data."""
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {
            "holdings": {},
            "transactions": [],
            "exchanges": {}
        }

    def _save_data(self):
        """Save portfolio data."""
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_holding(self, exchange: str, asset: str, amount: float,
                    cost_basis: float):
        """Add a crypto holding."""
        key = f"{exchange}:{asset}"
        if key in self.data["holdings"]:
            h = self.data["holdings"][key]
            total_amount = h["amount"] + amount
            h["cost_basis"] = (h["cost_basis"] * h["amount"] + cost_basis * amount) / total_amount
            h["amount"] = total_amount
        else:
            self.data["holdings"][key] = {
                "exchange": exchange,
                "asset": asset,
                "amount": amount,
                "cost_basis": cost_basis,
                "added_date": datetime.now().isoformat()
            }

        self._save_data()
        print(f"[+] Added {amount} {asset} on {exchange}")

    def get_portfolio_value(self, prices: Dict[str, float]) -> Dict[str, Any]:
        """Calculate portfolio value using current prices."""
        total_value = 0
        total_cost = 0
        holdings_detail = []

        for key, h in self.data["holdings"].items():
            current_price = prices.get(h["asset"], 0)
            value = h["amount"] * current_price
            cost = h["amount"] * h["cost_basis"]
            pnl = value - cost

            total_value += value
            total_cost += cost

            holdings_detail.append({
                "exchange": h["exchange"],
                "asset": h["asset"],
                "amount": h["amount"],
                "current_price": current_price,
                "value": value,
                "cost_basis": h["cost_basis"],
                "pnl": pnl,
                "pnl_pct": (pnl / cost * 100) if cost > 0 else 0
            })

        return {
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_value - total_cost,
            "holdings": holdings_detail
        }


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Crypto Exchange Connector")
        print("=" * 40)
        print("\nCommands:")
        print("  price <symbol>        - Get price (e.g., BTCUSDT)")
        print("  ticker <symbol>       - Get 24hr ticker")
        print("  portfolio             - Show portfolio")
        print("  add <exchange> <asset> <amount> <cost> - Add holding")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "price" and len(sys.argv) >= 3:
        binance = BinanceConnector()
        price = binance.get_price(sys.argv[2])
        print(f"\n{sys.argv[2]}: ${price:,.2f}")

    elif cmd == "ticker" and len(sys.argv) >= 3:
        binance = BinanceConnector()
        ticker = binance.get_ticker(sys.argv[2])
        print(f"\n24hr Ticker for {sys.argv[2]}:")
        print(f"  Price: ${float(ticker.get('lastPrice', 0)):,.2f}")
        print(f"  24h High: ${float(ticker.get('highPrice', 0)):,.2f}")
        print(f"  24h Low: ${float(ticker.get('lowPrice', 0)):,.2f}")
        print(f"  Volume: {float(ticker.get('volume', 0)):,.2f}")

    elif cmd == "add" and len(sys.argv) >= 6:
        portfolio = CryptoPortfolio()
        portfolio.add_holding(sys.argv[2], sys.argv[3],
                             float(sys.argv[4]), float(sys.argv[5]))

    elif cmd == "portfolio":
        portfolio = CryptoPortfolio()
        # Get current prices
        binance = BinanceConnector()
        prices = {}
        for key, h in portfolio.data["holdings"].items():
            try:
                prices[h["asset"]] = binance.get_price(f"{h['asset']}USDT")
            except Exception:
                prices[h["asset"]] = 0

        result = portfolio.get_portfolio_value(prices)
        print(f"\nCrypto Portfolio:")
        print(f"  Total Value: ${result['total_value']:,.2f}")
        print(f"  Total P&L: ${result['total_pnl']:+,.2f}")
        print("\nHoldings:")
        for h in result["holdings"]:
            print(f"  {h['amount']:.6f} {h['asset']} @ ${h['current_price']:,.2f} "
                  f"(P&L: ${h['pnl']:+,.2f})")

    else:
        print("Unknown command. Run without args for help.")


if __name__ == "__main__":
    main()
