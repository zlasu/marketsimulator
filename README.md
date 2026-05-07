# Market Simulator / Market Live

Random Market Simulator inspired by the Krafter Youtube video: random traders place orders near the latest traded price, the order book stores maker liquidity, and takers consume that liquidity. Any unfilled remainder stays in the book as a limit order, creating visible liquidity walls on the chart.

The app also includes Market Live mode. It polls public Binance Spot or Hyperliquid market data, renders the live order book with recent candles, tracks visible liquidity levels, and calculates short-horizon market pressure from depth, top-of-book imbalance, microprice, momentum, trade flow, and nearby liquidity walls.

## Running

Backend:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://127.0.0.1:5173`.
If that port is already in use, Vite will automatically pick the next available port and print it in the terminal.

## Live Mode

- The app opens in Hyperliquid live mode by default.
- Binance markets: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`.
- Hyperliquid markets: `BTC`, `ETH`, `SOL`, `HYPE`, `XRP`, `DOGE`, `FARTCOIN`, `PUMP`, `ENA`, `LINK`.
- Live backend endpoints:
  - `GET /api/live/markets`
  - `GET /api/live/state?exchange=binance&symbol=BTCUSDT`
- The prediction is a local signal model, not trading advice. It combines orderbook imbalance, top 5 levels, microprice edge, recent candle momentum, aggressor flow where available, Hyperliquid order counts, and bid/ask wall skew.

## Model Assumptions

- The default instrument is `BTCUSD`; `EURUSD` and `XAUUSD` are also available.
- Each preset has its own `tick_size`, volatility, liquidity, and taker activity settings.
- The simulation runs 1000 traders per tick.
- Each trader has a random chance to place an order on each tick.
- Order prices are sampled around the latest traded price and rounded to the instrument tick size.
- Order quantity is sampled from a preset-specific range.
- A candle closes every 10 ticks.
- A buy above the best ask or a sell below the best bid executes as a taker order.
- Any unfilled remainder is added back to the order book as maker liquidity.
- Passive liquidity providers continuously rebuild both sides of the book, while some stale orders are cancelled.
- A slow reference price and persistent order flow create both trending and quiet regimes without one-way drift.
