from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .live_market import MarketDataError, MarketLive
from .simulator import PRESETS, MarketSimulator, preset_config


app = FastAPI(title="Market Simulator")
simulator = MarketSimulator(config=preset_config("BTCUSD"))
live_market = MarketLive()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TickRequest(BaseModel):
    ticks: int = 1


class ResetRequest(BaseModel):
    seed: int | None = 7
    preset: str = "BTCUSD"


@app.get("/api/state")
def state() -> dict:
    return simulator.state()


@app.get("/api/live/state")
def live_state(
    exchange: str = Query("binance", pattern="^(binance|hyperliquid)$"),
    symbol: str = "BTCUSDT",
) -> dict:
    try:
        return live_market.state(exchange, symbol)
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/live/markets")
def live_markets() -> dict:
    return live_market.markets()


@app.get("/api/presets")
def presets() -> dict:
    return {"presets": list(PRESETS)}


@app.post("/api/tick")
def tick(request: TickRequest) -> dict:
    return simulator.step(request.ticks)


@app.post("/api/reset")
def reset(request: ResetRequest) -> dict:
    simulator.reset(request.seed, preset_config(request.preset))
    return simulator.state()
