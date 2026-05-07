from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal


Side = Literal["buy", "sell"]


class MarketDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveMarket:
    exchange: str
    symbol: str
    label: str


LIVE_MARKETS: dict[str, list[LiveMarket]] = {
    "binance": [
        LiveMarket("binance", "BTCUSDT", "BTC/USDT"),
        LiveMarket("binance", "ETHUSDT", "ETH/USDT"),
        LiveMarket("binance", "SOLUSDT", "SOL/USDT"),
        LiveMarket("binance", "BNBUSDT", "BNB/USDT"),
    ],
    "hyperliquid": [
        LiveMarket("hyperliquid", "BTC", "BTC perp"),
        LiveMarket("hyperliquid", "ETH", "ETH perp"),
        LiveMarket("hyperliquid", "SOL", "SOL perp"),
        LiveMarket("hyperliquid", "HYPE", "HYPE perp"),
        LiveMarket("hyperliquid", "XRP", "XRP perp"),
        LiveMarket("hyperliquid", "DOGE", "DOGE perp"),
        LiveMarket("hyperliquid", "FARTCOIN", "FARTCOIN perp"),
        LiveMarket("hyperliquid", "PUMP", "PUMP perp"),
        LiveMarket("hyperliquid", "ENA", "ENA perp"),
        LiveMarket("hyperliquid", "LINK", "LINK perp"),
    ],
}


class MarketLive:
    def __init__(self) -> None:
        self.tick_index = 0
        self.market_key: tuple[str, str] | None = None
        self.next_liquidity_line_id = 1
        self.liquidity_lines: dict[int, dict[str, Any]] = {}
        self.active_line_ids: dict[str, int] = {}

    def state(self, exchange: str = "binance", symbol: str = "BTCUSDT") -> dict:
        exchange = exchange.lower()
        symbol = symbol.upper()
        source = _source_for(exchange)

        if self.market_key != (exchange, symbol):
            self._reset_liquidity()
            self.market_key = (exchange, symbol)

        snapshot = source.fetch(symbol)
        candle_ticks = 10
        self.tick_index = max(self.tick_index + 1, len(snapshot["candles"]) * candle_ticks)

        candles = self._anchored_candles(snapshot["candles"], candle_ticks)
        orderbook = _orderbook_payload(snapshot["bids"], snapshot["asks"], 18)
        self._update_liquidity(snapshot["bids"][:28], snapshot["asks"][:28])

        best_bid = snapshot["bids"][0]["price"] if snapshot["bids"] else None
        best_ask = snapshot["asks"][0]["price"] if snapshot["asks"] else None
        last_price = snapshot["lastPrice"] or _mid_price(best_bid, best_ask) or 0.0
        spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
        tick_size = _infer_tick_size(snapshot["bids"], snapshot["asks"])
        trades = self._anchored_trades(snapshot["trades"], snapshot["time"], candle_ticks)
        analytics = _analytics(snapshot["bids"], snapshot["asks"], candles, trades, last_price, spread)

        return {
            "mode": "live",
            "source": {"exchange": exchange, "symbol": symbol, "label": source.label(symbol)},
            "tick": self.tick_index,
            "ticksPerCandle": candle_ticks,
            "liveTick": self.tick_index % candle_ticks,
            "lastPrice": last_price,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "spread": spread,
            "imbalance": round(analytics["orderbook"]["imbalance"], 4),
            "candles": candles,
            "orderbook": orderbook,
            "trades": trades[-120:],
            "liquidity": self._liquidity_payload(),
            "config": {
                "symbol": symbol,
                "exchange": exchange,
                "tick_size": tick_size,
                "candle_ticks": candle_ticks,
                "history_limit": 180,
            },
            "analytics": analytics,
            "updatedAt": snapshot["time"],
        }

    def markets(self) -> dict:
        return {
            exchange: [
                {"exchange": market.exchange, "symbol": market.symbol, "label": market.label}
                for market in markets
            ]
            for exchange, markets in LIVE_MARKETS.items()
        }

    def _reset_liquidity(self) -> None:
        self.tick_index = 0
        self.next_liquidity_line_id = 1
        self.liquidity_lines = {}
        self.active_line_ids = {}

    def _anchored_candles(self, source_candles: list[dict], candle_ticks: int) -> list[dict]:
        candles = source_candles[-180:]
        candle_count = len(candles)
        anchored = []
        for index, candle in enumerate(candles):
            end_tick = self.tick_index - (candle_count - 1 - index) * candle_ticks
            start_tick = end_tick - candle_ticks
            anchored.append(
                {
                    "index": max(0, end_tick // candle_ticks),
                    "startTick": start_tick,
                    "endTick": end_tick,
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                }
            )
        return anchored

    def _anchored_trades(self, trades: list[dict], now_ms: int, candle_ticks: int) -> list[dict]:
        anchored = []
        for trade in trades[-120:]:
            age_ms = max(0, now_ms - int(trade.get("time", now_ms)))
            age_ticks = min(520, int(age_ms / 60_000 * candle_ticks))
            anchored.append(
                {
                    "tick": max(0, self.tick_index - age_ticks),
                    "price": trade["price"],
                    "quantity": trade["quantity"],
                    "side": trade["side"],
                }
            )
        return anchored

    def _update_liquidity(self, bids: list[dict], asks: list[dict]) -> None:
        present_keys: set[str] = set()

        for side, rows in (("buy", bids), ("sell", asks)):
            for row in rows:
                key = self._liquidity_key(side, row["price"])
                present_keys.add(key)
                quantity = row["quantity"]
                if key not in self.active_line_ids:
                    line_id = self.next_liquidity_line_id
                    self.next_liquidity_line_id += 1
                    self.active_line_ids[key] = line_id
                    self.liquidity_lines[line_id] = {
                        "id": line_id,
                        "startTick": self.tick_index,
                        "endTick": None,
                        "price": row["price"],
                        "initialQuantity": quantity,
                        "remainingQuantity": quantity,
                        "side": side,
                        "closeReason": None,
                    }
                    continue

                line = self.liquidity_lines[self.active_line_ids[key]]
                line["remainingQuantity"] = quantity
                line["initialQuantity"] = max(line["initialQuantity"], quantity)

        for key, line_id in list(self.active_line_ids.items()):
            if key in present_keys:
                continue
            line = self.liquidity_lines.get(line_id)
            if line is not None:
                line["endTick"] = self.tick_index
                line["closeReason"] = "snapshot_removed"
            del self.active_line_ids[key]

        min_tick = self.tick_index - 1860
        for line_id, line in list(self.liquidity_lines.items()):
            if line["endTick"] is not None and line["endTick"] < min_tick:
                del self.liquidity_lines[line_id]

    def _liquidity_payload(self) -> list[dict]:
        min_tick = self.tick_index - 1860
        lines = [
            line
            for line in self.liquidity_lines.values()
            if line["startTick"] >= min_tick or line["endTick"] is None or line["endTick"] >= min_tick
        ]
        return sorted(lines, key=lambda line: (line["startTick"], line["id"]))[-1800:]

    @staticmethod
    def _liquidity_key(side: str, price: float) -> str:
        return f"{side}:{price:.12g}"


class BinanceSource:
    base_url = "https://api.binance.com"

    def fetch(self, symbol: str) -> dict:
        depth = _get_json(f"{self.base_url}/api/v3/depth", {"symbol": symbol, "limit": 100})
        klines = _get_json(
            f"{self.base_url}/api/v3/klines",
            {"symbol": symbol, "interval": "1m", "limit": 120},
        )
        trades = _get_json(f"{self.base_url}/api/v3/aggTrades", {"symbol": symbol, "limit": 80})
        now_ms = int(time.time() * 1000)

        bids = _parse_levels(depth.get("bids", []), reverse=True)
        asks = _parse_levels(depth.get("asks", []), reverse=False)
        candles = [
            {
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in klines
        ]
        parsed_trades = [
            {
                "time": int(row["T"]),
                "price": float(row["p"]),
                "quantity": float(row["q"]),
                "side": "sell" if row.get("m") else "buy",
            }
            for row in trades
        ]

        return {
            "time": now_ms,
            "bids": bids,
            "asks": asks,
            "candles": candles,
            "trades": parsed_trades,
            "lastPrice": candles[-1]["close"] if candles else _mid_price(_price(bids), _price(asks)),
        }

    def label(self, symbol: str) -> str:
        return f"Binance {symbol}"


class HyperliquidSource:
    base_url = "https://api.hyperliquid.xyz/info"

    def fetch(self, symbol: str) -> dict:
        now_ms = int(time.time() * 1000)
        depth = _post_json(self.base_url, {"type": "l2Book", "coin": symbol, "nSigFigs": 5})
        candles = _post_json(
            self.base_url,
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": "1m",
                    "startTime": now_ms - 120 * 60_000,
                    "endTime": now_ms,
                },
            },
        )
        trades = _post_json(self.base_url, {"type": "recentTrades", "coin": symbol})
        levels = depth.get("levels", depth) if isinstance(depth, dict) else depth
        bids = _parse_hyperliquid_levels(levels[0] if levels else [], reverse=True)
        asks = _parse_hyperliquid_levels(levels[1] if len(levels) > 1 else [], reverse=False)
        parsed_candles = [
            {
                "time": int(row["t"]),
                "open": float(row["o"]),
                "high": float(row["h"]),
                "low": float(row["l"]),
                "close": float(row["c"]),
                "volume": float(row["v"]),
            }
            for row in candles
        ]
        parsed_trades = [
            {
                "time": int(row["time"]),
                "price": float(row["px"]),
                "quantity": float(row["sz"]),
                "side": "buy" if row.get("side") == "B" else "sell",
            }
            for row in trades[-120:]
        ]

        return {
            "time": int(depth.get("time", now_ms)) if isinstance(depth, dict) else now_ms,
            "bids": bids,
            "asks": asks,
            "candles": parsed_candles,
            "trades": parsed_trades,
            "lastPrice": parsed_candles[-1]["close"] if parsed_candles else _mid_price(_price(bids), _price(asks)),
        }

    def label(self, symbol: str) -> str:
        return f"Hyperliquid {symbol}"


def _source_for(exchange: str) -> BinanceSource | HyperliquidSource:
    if exchange == "binance":
        return BinanceSource()
    if exchange == "hyperliquid":
        return HyperliquidSource()
    raise MarketDataError(f"Unsupported exchange: {exchange}")


def _get_json(url: str, params: dict[str, Any], timeout: float = 4.5) -> Any:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "MarketLive/0.1"})
    return _urlopen_json(request, timeout)


def _post_json(url: str, payload: dict[str, Any], timeout: float = 4.5) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "MarketLive/0.1"},
        method="POST",
    )
    return _urlopen_json(request, timeout)


def _urlopen_json(request: urllib.request.Request, timeout: float) -> Any:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise MarketDataError(f"Market data API returned HTTP {exc.code}: {details[:240]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"Market data API request failed: {exc}") from exc


def _parse_levels(levels: list[list[str]], reverse: bool) -> list[dict]:
    parsed = [{"price": float(price), "quantity": float(quantity)} for price, quantity, *_ in levels]
    return sorted(parsed, key=lambda row: row["price"], reverse=reverse)


def _parse_hyperliquid_levels(levels: list[dict], reverse: bool) -> list[dict]:
    parsed = [
        {"price": float(row["px"]), "quantity": float(row["sz"]), "orders": int(row.get("n", 0))}
        for row in levels
    ]
    return sorted(parsed, key=lambda row: row["price"], reverse=reverse)


def _orderbook_payload(bids: list[dict], asks: list[dict], depth: int) -> dict:
    rows = asks[:depth] + bids[:depth]
    max_quantity = max([1.0] + [row["quantity"] for row in rows])
    max_orders = max([1] + [row.get("orders", 0) for row in rows])
    return {"asks": asks[:depth], "bids": bids[:depth], "maxQuantity": max_quantity, "maxOrders": max_orders}


def _analytics(
    bids: list[dict],
    asks: list[dict],
    candles: list[dict],
    trades: list[dict],
    last_price: float,
    spread: float | None,
) -> dict:
    bid_depth = sum(row["quantity"] for row in bids)
    ask_depth = sum(row["quantity"] for row in asks)
    total_depth = bid_depth + ask_depth
    imbalance = _safe_ratio(bid_depth - ask_depth, total_depth)

    top_bid_depth = sum(row["quantity"] for row in bids[:5])
    top_ask_depth = sum(row["quantity"] for row in asks[:5])
    top_imbalance = _safe_ratio(top_bid_depth - top_ask_depth, top_bid_depth + top_ask_depth)
    bid_orders = sum(row.get("orders", 0) for row in bids)
    ask_orders = sum(row.get("orders", 0) for row in asks)
    order_pressure = _safe_ratio(bid_orders - ask_orders, bid_orders + ask_orders)
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    mid = _mid_price(best_bid, best_ask) or last_price
    microprice = _microprice(best_bid, best_ask, bids[0]["quantity"] if bids else 0, asks[0]["quantity"] if asks else 0)
    half_spread = max((spread or 0) / 2, mid * 0.00002, 1e-12)
    microprice_edge = _clamp(((microprice or mid) - mid) / half_spread, -1, 1)
    momentum_short = _momentum(candles, 5)
    momentum_medium = _momentum(candles, 15)
    trade_flow = _trade_flow(trades)
    wall_skew = _wall_skew(bids, asks, mid)
    spread_penalty = min(0.18, ((spread or 0) / max(mid, 1e-12)) * 45)

    score = (
        imbalance * 0.38
        + top_imbalance * 0.18
        + microprice_edge * 0.16
        + _clamp(momentum_short / 0.0016, -1, 1) * 0.14
        + _clamp(momentum_medium / 0.0035, -1, 1) * 0.06
        + trade_flow * 0.05
        + order_pressure * 0.04
        + wall_skew * 0.03
    )
    score = _clamp(score - math.copysign(spread_penalty, score), -1, 1)
    direction = "flat"
    if score > 0.12:
        direction = "up"
    elif score < -0.12:
        direction = "down"

    confidence = round(min(92, 34 + abs(score) * 58))
    if direction == "flat":
        confidence = round(max(38, 64 - abs(score) * 100))

    return {
        "orderbook": {
            "bidDepth": bid_depth,
            "askDepth": ask_depth,
            "imbalance": imbalance,
            "topImbalance": top_imbalance,
            "microprice": microprice,
            "micropriceEdge": microprice_edge,
            "spreadPct": (spread or 0) / mid if mid else 0,
            "bidOrders": bid_orders,
            "askOrders": ask_orders,
            "orderPressure": order_pressure,
        },
        "depthBands": _depth_bands(bids, asks, mid),
        "walls": {"bid": _strongest_wall(bids, mid, "buy"), "ask": _strongest_wall(asks, mid, "sell")},
        "flow": {
            "tradeFlow": trade_flow,
            "momentumShort": momentum_short,
            "momentumMedium": momentum_medium,
            "wallSkew": wall_skew,
        },
        "prediction": {
            "direction": direction,
            "score": score,
            "confidence": confidence,
            "horizon": "1-5m",
            "reasons": _prediction_reasons(
                imbalance,
                top_imbalance,
                microprice_edge,
                momentum_short,
                trade_flow,
                order_pressure,
            ),
        },
    }


def _depth_bands(bids: list[dict], asks: list[dict], mid: float) -> list[dict]:
    distances = [
        abs(row["price"] - mid) / mid
        for row in bids + asks
        if mid > 0 and row["price"] > 0
    ]
    visible_distance = max(distances, default=0.01)
    base_bands = [0.001, 0.0025, 0.005, 0.01]
    if visible_distance <= base_bands[0]:
        bands_to_use = [visible_distance * factor for factor in (0.25, 0.5, 0.75, 1.0)]
    else:
        bands_to_use = [band for band in base_bands if band < visible_distance]
        bands_to_use.append(visible_distance)
        bands_to_use = bands_to_use[-4:]

    bands = []
    for percent in bands_to_use:
        min_bid = mid * (1 - percent)
        max_ask = mid * (1 + percent)
        bid_quantity = sum(row["quantity"] for row in bids if row["price"] >= min_bid)
        ask_quantity = sum(row["quantity"] for row in asks if row["price"] <= max_ask)
        bands.append(
            {
                "label": _format_band_label(percent),
                "bid": bid_quantity,
                "ask": ask_quantity,
                "imbalance": _safe_ratio(bid_quantity - ask_quantity, bid_quantity + ask_quantity),
            }
        )
    return bands


def _format_band_label(percent: float) -> str:
    value = percent * 100
    if value < 0.1:
        return f"{value:.3f}%"
    return f"{value:.2f}%"


def _strongest_wall(rows: list[dict], mid: float, side: Side) -> dict | None:
    if not rows:
        return None
    row = max(rows[:24], key=lambda level: level["quantity"] * math.sqrt(max(1, level.get("orders", 1))))
    distance = (row["price"] - mid) / mid if mid else 0
    return {
        "side": side,
        "price": row["price"],
        "quantity": row["quantity"],
        "orders": row.get("orders", 0),
        "distancePct": distance,
    }


def _prediction_reasons(
    imbalance: float,
    top_imbalance: float,
    microprice_edge: float,
    momentum_short: float,
    trade_flow: float,
    order_pressure: float,
) -> list[str]:
    factors = [
        ("Book imbalance", imbalance),
        ("Top 5 levels", top_imbalance),
        ("Microprice", microprice_edge),
        ("1m momentum", _clamp(momentum_short / 0.0016, -1, 1)),
        ("Aggressor flow", trade_flow),
        ("Order count", order_pressure),
    ]
    ranked = sorted(factors, key=lambda item: abs(item[1]), reverse=True)
    return [f"{name}: {'bullish' if value > 0 else 'bearish'}" for name, value in ranked if abs(value) > 0.08][:3]


def _trade_flow(trades: list[dict]) -> float:
    total = sum(trade["quantity"] for trade in trades)
    signed = sum(trade["quantity"] if trade["side"] == "buy" else -trade["quantity"] for trade in trades)
    return _safe_ratio(signed, total)


def _momentum(candles: list[dict], lookback: int) -> float:
    if len(candles) <= lookback:
        return 0.0
    previous = candles[-lookback - 1]["close"]
    current = candles[-1]["close"]
    return (current - previous) / previous if previous else 0.0


def _wall_skew(bids: list[dict], asks: list[dict], mid: float) -> float:
    bid_wall = _strongest_wall(bids, mid, "buy")
    ask_wall = _strongest_wall(asks, mid, "sell")
    if not bid_wall or not ask_wall:
        return 0.0
    bid_weight = bid_wall["quantity"] / max(abs(bid_wall["distancePct"]), 0.00015)
    ask_weight = ask_wall["quantity"] / max(abs(ask_wall["distancePct"]), 0.00015)
    return _safe_ratio(bid_weight - ask_weight, bid_weight + ask_weight)


def _microprice(best_bid: float | None, best_ask: float | None, bid_qty: float, ask_qty: float) -> float | None:
    if best_bid is None or best_ask is None or bid_qty + ask_qty <= 0:
        return _mid_price(best_bid, best_ask)
    return (best_ask * bid_qty + best_bid * ask_qty) / (bid_qty + ask_qty)


def _mid_price(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2


def _price(rows: list[dict]) -> float | None:
    return rows[0]["price"] if rows else None


def _infer_tick_size(bids: list[dict], asks: list[dict]) -> float:
    prices = sorted({row["price"] for row in bids[:12] + asks[:12]})
    differences = [round(b - a, 12) for a, b in zip(prices, prices[1:]) if b > a]
    if differences:
        return max(min(differences), 0.00000001)
    if prices and prices[0] > 1000:
        return 0.01
    return 0.0001


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return _clamp(numerator / denominator, -1, 1)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
