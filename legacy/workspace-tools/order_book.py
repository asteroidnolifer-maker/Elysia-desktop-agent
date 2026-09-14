#!/usr/bin/env python3
"""Task #27: Order book depth visualizer."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def generate_order_book(mid_price=100, levels=10):
    """Generate simulated order book data."""
    bids = []
    asks = []
    for i in range(levels):
        bid_price = mid_price - (i + 1) * 0.1
        ask_price = mid_price + (i + 1) * 0.1
        bid_vol = random.randint(100, 5000)
        ask_vol = random.randint(100, 5000)
        bids.append({"price": round(bid_price, 2), "volume": bid_vol, "total": sum(b["volume"] for b in bids) + bid_vol})
        asks.append({"price": round(ask_price, 2), "volume": ask_vol, "total": sum(a["volume"] for a in asks) + ask_vol})
    spread = asks[0]["price"] - bids[0]["price"]
    bid_depth = bids[-1]["total"]
    ask_depth = asks[-1]["total"]
    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    return {
        "bids": bids, "asks": asks,
        "spread": round(spread, 2),
        "spread_pct": round(spread / mid_price * 100, 4),
        "bid_depth": bid_depth, "ask_depth": ask_depth,
        "imbalance": round(imbalance, 4),
        "signal": "buying_pressure" if imbalance > 0.1 else "selling_pressure" if imbalance < -0.1 else "balanced"
    }

def visualize_order_book(book):
    """Create ASCII visualization of order book."""
    max_vol = max(max(b["volume"] for b in book["bids"]), max(a["volume"] for a in book["asks"]))
    lines = []
    for ask in reversed(book["asks"][:5]):
        bar_len = int(ask["volume"] / max_vol * 30)
        lines.append(f"  {ask['price']:>8.2f} |{'█' * bar_len}{'░' * (30-bar_len)}| {ask['volume']:>6}")
    lines.append(f"  {'Spread':>8} |{'─' * 30}| {book['spread']:.2f}")
    for bid in book["bids"][:5]:
        bar_len = int(bid["volume"] / max_vol * 30)
        lines.append(f"  {bid['price']:>8.2f} |{'█' * bar_len}{'░' * (30-bar_len)}| {bid['volume']:>6}")
    return "\n".join(lines)

if __name__ == "__main__":
    book = generate_order_book(178.50)
    print("Order Book Depth:")
    print(visualize_order_book(book))
    print(f"\n  Spread: ${book['spread']} ({book['spread_pct']}%)")
    print(f"  Signal: {book['signal']}")
    output = os.path.join(WORKSPACE, "order_book.json")
    with open(output, 'w') as f:
        json.dump(book, f, indent=2)
    print(f"[+] Saved to {output}")
