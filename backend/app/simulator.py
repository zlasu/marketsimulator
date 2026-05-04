from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Literal


Side = Literal["buy", "sell"]


@dataclass
class Candle:
    index: int
    start_tick: int
    end_tick: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def update(self, price: float, quantity: int) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += quantity


@dataclass
class Trade:
    tick: int
    price: float
    quantity: int
    side: Side


@dataclass
class LiquidityLine:
    id: int
    start_tick: int
    end_tick: int | None
    price: float
    initial_quantity: int
    remaining_quantity: int
    side: Side
    close_reason: str | None = None


@dataclass
class MarketConfig:
    symbol: str = "BTCUSD"
    traders: int = 1000
    trader_activity_rate: float = 0.0008
    candle_ticks: int = 10
    max_order_quantity: int = 25
    price_band: float = 0.003
    initial_price: float = 65000.0
    tick_size: float = 1.0
    taker_probability: float = 0.6
    liquidity_provider_rate: float = 0.3
    cancellation_rate: float = 0.005
    reference_volatility: float = 0.0005
    mean_reversion_strength: float = 11.0
    order_flow_persistence: float = 0.986
    order_flow_volatility: float = 0.014
    shock_probability: float = 0.008
    shock_size: float = 0.16
    history_limit: int = 180
    liquidity_levels: int = 32


@dataclass
class MarketSimulator:
    config: MarketConfig = field(default_factory=MarketConfig)
    seed: int | None = 7

    def __post_init__(self) -> None:
        self.rng = Random(self.seed)
        self.buy_book: dict[float, int] = {}
        self.sell_book: dict[float, int] = {}
        self.total_buy_volume = 0
        self.total_sell_volume = 0
        self.last_price = self._round_price(self.config.initial_price)
        self.reference_price = self.last_price
        self.flow_bias = 0.0
        self.tick_index = 0
        self.current_candle_tick = 0
        self.next_candle_index = 0
        self.candles: list[Candle] = []
        self.live_candle = self._new_candle()
        self.trades: list[Trade] = []
        self.liquidity_lines: dict[int, LiquidityLine] = {}
        self.active_line_ids: dict[tuple[Side, float], list[int]] = {}
        self.next_liquidity_line_id = 1

        # Seed a realistic two-sided book around the first traded price.
        for level in range(1, 42, 2):
            quantity = self.rng.randint(4, 18)
            offset = level * self.config.tick_size
            self._make_order(self.last_price - offset, quantity, True)
            self._make_order(self.last_price + offset, quantity, False)

    def reset(self, seed: int | None = None, config: MarketConfig | None = None) -> None:
        if config is not None:
            self.config = config
        self.seed = seed
        self.__post_init__()

    @property
    def best_bid(self) -> float | None:
        return max(self.buy_book) if self.buy_book else None

    @property
    def best_ask(self) -> float | None:
        return min(self.sell_book) if self.sell_book else None

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def imbalance(self) -> float:
        total = self.total_buy_volume + self.total_sell_volume
        if total <= 0:
            return 0.0
        return (self.total_buy_volume - self.total_sell_volume) / total

    def step(self, ticks: int = 1) -> dict:
        for _ in range(max(1, ticks)):
            self._process_tick()
        return self.state()

    def state(self) -> dict:
        self.live_candle.end_tick = self.tick_index
        visible_candles = self.candles[-self.config.history_limit :] + [self.live_candle]
        return {
            "tick": self.tick_index,
            "ticksPerCandle": self.config.candle_ticks,
            "liveTick": self.current_candle_tick,
            "lastPrice": self.last_price,
            "bestBid": self.best_bid,
            "bestAsk": self.best_ask,
            "spread": self.spread,
            "imbalance": round(self.imbalance, 4),
            "candles": [self._candle_payload(candle) for candle in visible_candles],
            "orderbook": self._orderbook_payload(18),
            "trades": [trade.__dict__ for trade in self.trades[-120:]],
            "liquidity": self._liquidity_payload(),
            "config": self.config.__dict__,
        }

    def _process_tick(self) -> None:
        self.tick_index += 1
        self.current_candle_tick += 1
        self._evolve_reference_price()
        self._evolve_order_flow()
        self._cancel_stale_orders()
        self._refresh_liquidity()

        for _ in range(self.config.traders):
            if self.rng.random() < self.config.trader_activity_rate:
                self._place_random_order()

        if self.live_candle.volume == 0:
            self.live_candle.update(self.last_price, 0)

        if self.current_candle_tick >= self.config.candle_ticks:
            self.live_candle.end_tick = self.tick_index
            self.candles.append(self.live_candle)
            self.candles = self.candles[-self.config.history_limit :]
            self.live_candle = self._new_candle()
            self.current_candle_tick = 0

    def _place_random_order(self) -> None:
        is_buy = self._determine_side()
        price = self._determine_price(is_buy)
        quantity = self.rng.randint(1, self.config.max_order_quantity)
        self.place_order(price, quantity, is_buy)

    def _determine_side(self) -> bool:
        mispricing = (self.reference_price - self.last_price) / max(self.last_price, self.config.tick_size)
        buy_probability = 0.5 + mispricing * self.config.mean_reversion_strength
        buy_probability += self.flow_bias
        buy_probability += self.rng.uniform(-0.035, 0.035)
        buy_probability = min(0.68, max(0.32, buy_probability))
        return self.rng.random() < buy_probability

    def _determine_price(self, is_buy: bool) -> float:
        aggressive = self.rng.random() < self.config.taker_probability
        spread_anchor = self.best_ask if is_buy else self.best_bid
        base = spread_anchor if aggressive and spread_anchor is not None else self.last_price
        max_distance = max(self.config.tick_size, self.last_price * self.config.price_band)
        distance = max(
            self.config.tick_size,
            abs(self.rng.gauss(max_distance * 0.34, max_distance * 0.38)),
        )

        if aggressive:
            raw_price = base + distance if is_buy else base - distance
        else:
            raw_price = self.last_price - distance if is_buy else self.last_price + distance

        return self._round_price(raw_price)

    def place_order(self, price: float, quantity: int, is_buy: bool) -> None:
        if price <= 0 or quantity <= 0:
            return

        if is_buy:
            best_ask = self.best_ask
            if best_ask is not None and price >= best_ask:
                self._take_order(price, quantity, True)
            else:
                self._make_order(price, quantity, True)
        else:
            best_bid = self.best_bid
            if best_bid is not None and price <= best_bid:
                self._take_order(price, quantity, False)
            else:
                self._make_order(price, quantity, False)

    def _make_order(self, price: float, quantity: int, is_buy: bool) -> None:
        price = self._round_price(price)
        book = self.buy_book if is_buy else self.sell_book
        book[price] = book.get(price, 0) + quantity
        self._open_liquidity_line(price, quantity, is_buy)
        if is_buy:
            self.total_buy_volume += quantity
        else:
            self.total_sell_volume += quantity

    def _take_order(self, limit_price: float, quantity: int, is_buy: bool) -> None:
        remaining = quantity

        while remaining > 0:
            if is_buy:
                best_ask = self.best_ask
                if best_ask is None or limit_price < best_ask:
                    break
                traded_quantity = min(self.sell_book[best_ask], remaining)
                self.sell_book[best_ask] -= traded_quantity
                self.total_sell_volume -= traded_quantity
                self._consume_liquidity(best_ask, traded_quantity, False, "filled")
                if self.sell_book[best_ask] <= 0:
                    del self.sell_book[best_ask]
                self._record_trade(best_ask, traded_quantity, "buy")
            else:
                best_bid = self.best_bid
                if best_bid is None or limit_price > best_bid:
                    break
                traded_quantity = min(self.buy_book[best_bid], remaining)
                self.buy_book[best_bid] -= traded_quantity
                self.total_buy_volume -= traded_quantity
                self._consume_liquidity(best_bid, traded_quantity, True, "filled")
                if self.buy_book[best_bid] <= 0:
                    del self.buy_book[best_bid]
                self._record_trade(best_bid, traded_quantity, "sell")

            remaining -= traded_quantity

        if remaining > 0:
            self._make_order(limit_price, remaining, is_buy)

    def _record_trade(self, price: float, quantity: int, side: Side) -> None:
        self.last_price = price
        self.live_candle.update(price, quantity)
        self.trades.append(Trade(self.tick_index, price, quantity, side))
        self.trades = self.trades[-500:]

    def _evolve_reference_price(self) -> None:
        shock = self.rng.gauss(0, self.config.reference_volatility)
        shock += self.flow_bias * self.config.reference_volatility * 0.35
        self.reference_price = self._round_price(self.reference_price * (1 + shock))

    def _evolve_order_flow(self) -> None:
        self.flow_bias *= self.config.order_flow_persistence
        self.flow_bias += self.rng.gauss(0, self.config.order_flow_volatility)
        if self.rng.random() < self.config.shock_probability:
            direction = 1 if self.rng.random() < 0.5 else -1
            self.flow_bias += direction * self.rng.uniform(self.config.shock_size * 0.45, self.config.shock_size)
        self.flow_bias = min(0.18, max(-0.18, self.flow_bias))

    def _refresh_liquidity(self) -> None:
        if self.rng.random() > self.config.liquidity_provider_rate:
            return

        max_distance = max(self.config.tick_size, self.last_price * self.config.price_band)
        distance = max(self.config.tick_size, abs(self.rng.gauss(max_distance * 0.55, max_distance * 0.45)))
        quantity = self.rng.randint(2, max(3, self.config.max_order_quantity // 2))
        self._make_order(self.last_price - distance, quantity, True)
        self._make_order(self.last_price + distance, quantity, False)

    def _cancel_stale_orders(self) -> None:
        self._cancel_from_book(self.buy_book, True)
        self._cancel_from_book(self.sell_book, False)

    def _cancel_from_book(self, book: dict[float, int], is_buy: bool) -> None:
        if not book:
            return

        for price, quantity in list(book.items()):
            distance = abs(price - self.last_price) / max(self.last_price, self.config.tick_size)
            distance_factor = min(5.0, distance / max(self.config.price_band * 6, 0.0001))
            cancel_probability = self.config.cancellation_rate * (1 + distance_factor)
            if self.rng.random() >= cancel_probability:
                continue

            cancelled = self.rng.randint(1, min(quantity, self.config.max_order_quantity))
            next_quantity = quantity - cancelled
            if next_quantity <= 0:
                del book[price]
            else:
                book[price] = next_quantity

            self._consume_liquidity(price, cancelled, is_buy, "cancelled")

            if is_buy:
                self.total_buy_volume -= cancelled
            else:
                self.total_sell_volume -= cancelled

    def _open_liquidity_line(self, price: float, quantity: int, is_buy: bool) -> None:
        side: Side = "buy" if is_buy else "sell"
        line_id = self.next_liquidity_line_id
        self.next_liquidity_line_id += 1
        line = LiquidityLine(
            id=line_id,
            start_tick=self.tick_index,
            end_tick=None,
            price=price,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            side=side,
        )
        self.liquidity_lines[line_id] = line
        self.active_line_ids.setdefault((side, price), []).append(line_id)

    def _consume_liquidity(self, price: float, quantity: int, is_buy: bool, reason: str) -> None:
        side: Side = "buy" if is_buy else "sell"
        active_ids = self.active_line_ids.get((side, price), [])
        remaining = quantity

        while remaining > 0 and active_ids:
            line = self.liquidity_lines[active_ids[0]]
            consumed = min(line.remaining_quantity, remaining)
            line.remaining_quantity -= consumed
            remaining -= consumed

            if line.remaining_quantity <= 0:
                line.remaining_quantity = 0
                line.end_tick = self.tick_index
                line.close_reason = reason
                active_ids.pop(0)

        if active_ids:
            self.active_line_ids[(side, price)] = active_ids
        else:
            self.active_line_ids.pop((side, price), None)

        self._prune_liquidity_lines()

    def _prune_liquidity_lines(self) -> None:
        min_tick = self.tick_index - self.config.history_limit * self.config.candle_ticks - 40
        for line_id, line in list(self.liquidity_lines.items()):
            if line.end_tick is not None and line.end_tick < min_tick:
                del self.liquidity_lines[line_id]

    def _new_candle(self) -> Candle:
        index = self.next_candle_index
        self.next_candle_index += 1
        return Candle(
            index=index,
            start_tick=self.tick_index,
            end_tick=self.tick_index,
            open=self.last_price,
            high=self.last_price,
            low=self.last_price,
            close=self.last_price,
        )

    def _top_bids(self, limit: int) -> list[tuple[float, int]]:
        return sorted(self.buy_book.items(), reverse=True)[:limit]

    def _top_asks(self, limit: int) -> list[tuple[float, int]]:
        return sorted(self.sell_book.items())[:limit]

    def _orderbook_payload(self, depth: int) -> dict:
        asks = [{"price": price, "quantity": quantity} for price, quantity in self._top_asks(depth)]
        bids = [{"price": price, "quantity": quantity} for price, quantity in self._top_bids(depth)]
        max_quantity = max([1] + [row["quantity"] for row in asks + bids])
        return {"asks": asks, "bids": bids, "maxQuantity": max_quantity}

    def _liquidity_payload(self) -> list[dict]:
        min_tick = max(0, self.tick_index - self.config.history_limit * self.config.candle_ticks - 20)
        lines = [
            line
            for line in self.liquidity_lines.values()
            if line.start_tick >= min_tick or line.end_tick is None or line.end_tick >= min_tick
        ]
        lines = sorted(lines, key=lambda line: (line.start_tick, line.id))[-1800:]
        return [
            {
                "id": line.id,
                "startTick": line.start_tick,
                "endTick": line.end_tick,
                "price": line.price,
                "initialQuantity": line.initial_quantity,
                "remainingQuantity": line.remaining_quantity,
                "side": line.side,
                "closeReason": line.close_reason,
            }
            for line in lines
        ]

    @staticmethod
    def _candle_payload(candle: Candle) -> dict:
        return {
            "index": candle.index,
            "startTick": candle.start_tick,
            "endTick": candle.end_tick,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }

    def _round_price(self, price: float) -> float:
        ticks = round(price / self.config.tick_size)
        return round(max(self.config.tick_size, ticks * self.config.tick_size), 8)


PRESETS: dict[str, MarketConfig] = {
    "BTCUSD": MarketConfig(
        symbol="BTCUSD",
        initial_price=65000.0,
        tick_size=1.0,
        price_band=0.003,
        taker_probability=0.6,
        liquidity_provider_rate=0.3,
        cancellation_rate=0.005,
        reference_volatility=0.0005,
        order_flow_volatility=0.014,
        shock_size=0.16,
    ),
    "EURUSD": MarketConfig(
        symbol="EURUSD",
        initial_price=1.08500,
        tick_size=0.00001,
        price_band=0.00028,
        taker_probability=0.46,
        liquidity_provider_rate=0.72,
        cancellation_rate=0.0018,
        reference_volatility=0.000035,
        mean_reversion_strength=15.0,
        order_flow_volatility=0.0045,
        shock_probability=0.004,
        shock_size=0.035,
        max_order_quantity=45,
    ),
    "XAUUSD": MarketConfig(
        symbol="XAUUSD",
        initial_price=2350.0,
        tick_size=0.1,
        price_band=0.001,
        taker_probability=0.52,
        liquidity_provider_rate=0.5,
        cancellation_rate=0.003,
        reference_volatility=0.00022,
        order_flow_volatility=0.009,
        shock_size=0.09,
        max_order_quantity=30,
    ),
}


def preset_config(symbol: str) -> MarketConfig:
    template = PRESETS.get(symbol, PRESETS["BTCUSD"])
    return MarketConfig(**template.__dict__)
