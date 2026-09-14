#!/usr/bin/env python3
"""Task #1: Real-time stock price dashboard with candlestick charts."""
import json, os, time
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

class StockDashboard:
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 60

    def get_stock_data(self, symbol, period="1d", interval="1m"):
        """Fetch stock data (simulated for demo, replace with real API)."""
        import random
        base_price = {"AAPL": 178, "GOOGL": 141, "MSFT": 378, "AMZN": 178, "TSLA": 248}.get(symbol, 100)
        data = []
        now = datetime.now()
        for i in range(390):  # Trading day minutes
            t = now - timedelta(minutes=390-i)
            change = random.uniform(-2, 2)
            base_price = max(base_price + change, 1)
            data.append({
                "time": t.strftime("%Y-%m-%d %H:%M"),
                "open": round(base_price + random.uniform(-1, 1), 2),
                "high": round(base_price + random.uniform(0, 3), 2),
                "low": round(base_price - random.uniform(0, 3), 2),
                "close": round(base_price, 2),
                "volume": random.randint(100000, 5000000)
            })
        return data

    def render_candlestick_svg(self, data, width=800, height=400):
        """Generate SVG candlestick chart."""
        if not data:
            return ""
        closes = [d["close"] for d in data]
        min_p, max_p = min(closes), max(closes)
        price_range = max_p - min_p or 1
        candle_w = max(width // len(data) - 1, 2)

        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        svg += f'<rect width="{width}" height="{height}" fill="#1a1a2e"/>'

        for i, d in enumerate(data):
            x = i * (candle_w + 1)
            y_open = height - ((d["open"] - min_p) / price_range * (height - 40)) - 20
            y_close = height - ((d["close"] - min_p) / price_range * (height - 40)) - 20
            y_high = height - ((d["high"] - min_p) / price_range * (height - 40)) - 20
            y_low = height - ((d["low"] - min_p) / price_range * (height - 40)) - 20
            color = "#00d4aa" if d["close"] >= d["open"] else "#ff4757"
            svg += f'<line x1="{x+candle_w//2}" y1="{y_high}" x2="{x+candle_w//2}" y2="{y_low}" stroke="{color}" stroke-width="1"/>'
            svg += f'<rect x="{x}" y="{min(y_open,y_close)}" width="{candle_w}" height="{max(abs(y_open-y_close),1)}" fill="{color}"/>'

        svg += '</svg>'
        return svg

    def get_dashboard(self, symbols=None):
        """Generate complete dashboard data."""
        if not symbols:
            symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]
        dashboard = {"generated": datetime.now().isoformat(), "stocks": {}}
        for sym in symbols:
            data = self.get_stock_data(sym)
            dashboard["stocks"][sym] = {
                "current": data[-1]["close"],
                "change": round(data[-1]["close"] - data[0]["close"], 2),
                "change_pct": round((data[-1]["close"] - data[0]["close"]) / data[0]["close"] * 100, 2),
                "high": max(d["high"] for d in data),
                "low": min(d["low"] for d in data),
                "volume": sum(d["volume"] for d in data),
                "chart_svg": self.render_candlestick_svg(data[-60:])
            }
        return dashboard

    def save_dashboard(self, output_path=None):
        if not output_path:
            output_path = os.path.join(WORKSPACE, "stock_dashboard.json")
        dashboard = self.get_dashboard()
        with open(output_path, 'w') as f:
            json.dump(dashboard, f, indent=2)
        # Also save HTML version
        html_path = output_path.replace('.json', '.html')
        with open(html_path, 'w') as f:
            f.write('<!DOCTYPE html><html><head><title>Stock Dashboard</title>')
            f.write('<style>body{background:#0f0f23;color:#fff;font-family:monospace;padding:20px}')
            f.write('.stock{background:#1a1a2e;border-radius:8px;padding:15px;margin:10px 0}')
            f.write('.up{color:#00d4aa}.down{color:#ff4757}</style></head><body>')
            f.write('<h1>Elysia Stock Dashboard</h1>')
            for sym, info in dashboard["stocks"].items():
                cls = "up" if info["change"] >= 0 else "down"
                sign = "+" if info["change"] >= 0 else ""
                f.write(f'<div class="stock"><h2>{sym}</h2>')
                f.write(f'<p class="{cls}">${info["current"]} ({sign}{info["change_pct"]}%)</p>')
                f.write(f'<p>High: ${info["high"]} | Low: ${info["low"]} | Vol: {info["volume"]:,}</p>')
                f.write(f'{info["chart_svg"]}</div>')
            f.write('</body></html>')
        return {"json": output_path, "html": html_path}

if __name__ == "__main__":
    dash = StockDashboard()
    result = dash.save_dashboard()
    print(f"[+] Dashboard saved to {result['html']}")
