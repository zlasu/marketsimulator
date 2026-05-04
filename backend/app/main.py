from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .simulator import PRESETS, MarketSimulator, preset_config


app = FastAPI(title="Market Simulator")
simulator = MarketSimulator(config=preset_config("BTCUSD"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
