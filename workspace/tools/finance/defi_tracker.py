#!/usr/bin/env python3
"""
DeFi Tracker for Elysia Finance
Track DeFi positions, yields, and liquidity.
"""
import json
import urllib.request
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class DeFiTracker:
    """Track DeFi positions across protocols."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "defi_portfolio.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"positions": [], "transactions": [], "protocols": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_position(self, protocol: str, asset: str, amount: float,
                     value_usd: float, apy: float = 0) -> Dict[str, Any]:
        position = {
            "id": f"pos_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "protocol": protocol, "asset": asset, "amount": amount,
            "value_usd": value_usd, "apy": apy,
            "added": datetime.now().isoformat()
        }
        self.data["positions"].append(position)
        self._save_data()
        return position

    def remove_position(self, position_id: str):
        self.data["positions"] = [p for p in self.data["positions"] if p["id"] != position_id]
        self._save_data()

    def get_portfolio_value(self) -> Dict[str, Any]:
        total_value = sum(p.get("value_usd", 0) for p in self.data["positions"])
        total_apy = 0
        weighted_apy = 0
        for p in self.data["positions"]:
            value = p.get("value_usd", 0)
            apy = p.get("apy", 0)
            weighted_apy += value * apy
            total_apy = weighted_apy / total_value if total_value > 0 else 0

        protocols = {}
        for p in self.data["positions"]:
            proto = p.get("protocol", "unknown")
            if proto not in protocols:
                protocols[proto] = {"value": 0, "positions": 0}
            protocols[proto]["value"] += p.get("value_usd", 0)
            protocols[proto]["positions"] += 1

        return {
            "total_value_usd": total_value,
            "average_apy": total_apy,
            "protocol_breakdown": protocols,
            "position_count": len(self.data["positions"])
        }

    def get_positions_by_protocol(self, protocol: str) -> List[Dict[str, Any]]:
        return [p for p in self.data["positions"] if p.get("protocol") == protocol]

    def calculate_yield(self, days: int = 365) -> float:
        portfolio = self.get_portfolio_value()
        avg_apy = portfolio.get("average_apy", 0)
        daily_rate = avg_apy / 365 / 100
        total_value = portfolio.get("total_value_usd", 0)
        daily_yield = total_value * daily_rate
        return daily_yield * days

    def add_transaction(self, protocol: str, action: str, asset: str,
                        amount: float, value_usd: float):
        self.data["transactions"].append({
            "protocol": protocol, "action": action, "asset": asset,
            "amount": amount, "value_usd": value_usd,
            "timestamp": datetime.now().isoformat()
        })
        self._save_data()

    def get_yield_opportunities(self) -> List[Dict[str, Any]]:
        return [
            {"protocol": "Aave", "asset": "USDC", "apy": 4.5, "risk": "low"},
            {"protocol": "Compound", "asset": "DAI", "apy": 3.8, "risk": "low"},
            {"protocol": "Uniswap V3", "asset": "ETH/USDC", "apy": 15.2, "risk": "medium"},
            {"protocol": "Curve", "asset": "3pool", "apy": 6.1, "risk": "low"},
            {"protocol": "Yearn", "asset": "yvUSDC", "apy": 5.8, "risk": "medium"}
        ]


class NFTTracker:
    """Track NFT holdings."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "nft_portfolio.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"nfts": [], "collections": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_nft(self, collection: str, name: str, token_id: str,
                purchase_price: float, current_value: float = 0) -> Dict[str, Any]:
        nft = {
            "id": f"nft_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "collection": collection, "name": name, "token_id": token_id,
            "purchase_price": purchase_price, "current_value": current_value,
            "added": datetime.now().isoformat()
        }
        self.data["nfts"].append(nft)
        if collection not in self.data["collections"]:
            self.data["collections"][collection] = {"count": 0, "total_value": 0}
        self.data["collections"][collection]["count"] += 1
        self.data["collections"][collection]["total_value"] += current_value
        self._save_data()
        return nft

    def get_portfolio_value(self) -> Dict[str, Any]:
        total_cost = sum(n.get("purchase_price", 0) for n in self.data["nfts"])
        total_value = sum(n.get("current_value", 0) for n in self.data["nfts"])
        return {
            "total_value": total_value, "total_cost": total_cost,
            "unrealized_pnl": total_value - total_cost,
            "nft_count": len(self.data["nfts"]),
            "collections": self.data.get("collections", {})
        }


def main():
    import sys

    if len(sys.argv) < 2:
        print("DeFi & NFT Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  defi-add <protocol> <asset> <amount> <value> <apy>")
        print("  defi-portfolio       - DeFi portfolio value")
        print("  defi-yields          - Yield opportunities")
        print("  nft-add <collection> <name> <token_id> <price>")
        print("  nft-portfolio        - NFT portfolio value")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "defi-add" and len(sys.argv) >= 6:
        tracker = DeFiTracker()
        tracker.add_position(sys.argv[2], sys.argv[3], float(sys.argv[4]),
                             float(sys.argv[5]), float(sys.argv[6]) if len(sys.argv) > 6 else 0)
        print("Position added")
    elif cmd == "defi-portfolio":
        tracker = DeFiTracker()
        p = tracker.get_portfolio_value()
        print(f"Total Value: ${p['total_value_usd']:,.2f}")
        print(f"Average APY: {p['average_apy']:.1f}%")
    elif cmd == "defi-yields":
        tracker = DeFiTracker()
        for y in tracker.get_yield_opportunities():
            print(f"  {y['protocol']} {y['asset']}: {y['apy']}% ({y['risk']})")
    elif cmd == "nft-add" and len(sys.argv) >= 6:
        tracker = NFTTracker()
        tracker.add_nft(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]))
        print("NFT added")
    elif cmd == "nft-portfolio":
        tracker = NFTTracker()
        p = tracker.get_portfolio_value()
        print(f"Total Value: ${p['total_value']:,.2f}")
        print(f"NFTs: {p['nft_count']}")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
