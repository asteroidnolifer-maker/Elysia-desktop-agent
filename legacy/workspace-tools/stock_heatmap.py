#!/usr/bin/env python3
"""Task #24: Stock heat map visualization."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def generate_heatmap_data():
    """Generate stock heatmap data."""
    sectors = {
        "Technology": ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AVGO", "CRM", "AMD"],
        "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT"],
        "Financial": ["JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "BLK"],
        "Consumer": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW"],
        "Energy": ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO"],
    }
    data = []
    for sector, stocks in sectors.items():
        for sym in stocks:
            change = random.uniform(-4, 5)
            market_cap = random.uniform(50, 3000)
            data.append({
                "symbol": sym,
                "sector": sector,
                "change_pct": round(change, 2),
                "market_cap_b": round(market_cap, 1),
                "color": f"#{min(255,max(0,int(128+change*25))):02x}{min(255,max(0,int(128-change*25))):02x}80"
            })
    return data

def render_heatmap_html(data, output_path):
    """Render stock heatmap as HTML."""
    sectors = {}
    for d in data:
        if d["sector"] not in sectors:
            sectors[d["sector"]] = []
        sectors[d["sector"]].append(d)
    html = '<!DOCTYPE html><html><head><title>Stock Heatmap</title>'
    html += '<style>body{background:#1a1a2e;color:#fff;font-family:monospace;padding:20px}'
    html += '.sector{margin:10px 0}.sector-title{font-size:14px;color:#888;margin:5px 0}'
    html += '.grid{display:flex;flex-wrap:wrap;gap:2px}'
    html += '.stock{padding:8px;border-radius:4px;text-align:center;font-size:11px;cursor:pointer;transition:transform 0.2s}'
    html += '.stock:hover{transform:scale(1.1);z-index:1}'
    html += '</style></head><body><h1>Market Heatmap</h1>'
    for sector, stocks in sectors.items():
        html += f'<div class="sector"><div class="sector-title">{sector}</div><div class="grid">'
        for s in sorted(stocks, key=lambda x: x["market_cap_b"], reverse=True):
            bg = f"rgb({max(0,min(255,int(128+s['change_pct']*25)))},{max(0,min(255,int(128-s['change_pct']*25)))},80)"
            size = max(60, min(120, int(s["market_cap_b"] / 20)))
            html += f'<div class="stock" style="background:{bg};width:{size}px;height:{size}px">'
            html += f'{s["symbol"]}<br>{s["change_pct"]:+.1f}%</div>'
        html += '</div></div>'
    html += '</body></html>'
    with open(output_path, 'w') as f:
        f.write(html)
    return output_path

if __name__ == "__main__":
    data = generate_heatmap_data()
    html_path = render_heatmap_html(data, os.path.join(WORKSPACE, "stock_heatmap.html"))
    print(f"[+] Heatmap saved to {html_path}")
    output = os.path.join(WORKSPACE, "stock_heatmap.json")
    with open(output, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[+] Data saved to {output}")
