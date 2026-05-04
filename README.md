# Market Simulator

Market simulator inspired by the source materials in `materials/`: random traders place orders near the latest traded price, the order book stores maker liquidity, and takers consume that liquidity. Any unfilled remainder stays in the book as a limit order, creating visible liquidity walls on the chart.

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
