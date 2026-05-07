<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Pause, Play, RefreshCw, RotateCcw, StepForward, Wifi } from "lucide-vue-next";

const state = ref(null);
const loading = ref(false);
const error = ref("");
const runTicks = ref(10);
const presets = ref(["BTCUSD"]);
const selectedPreset = ref("BTCUSD");
const mode = ref("live");
const autoplay = ref(false);
const liveMarkets = ref({ binance: [], hyperliquid: [] });
const liveExchange = ref("hyperliquid");
const liveSymbol = ref("BTC");
let autoplayTimer = null;
let autoplayBusy = false;

const chartWidth = 1080;
const chartHeight = 650;
const volumeHeight = 96;
const priceTop = 26;
const priceBottom = chartHeight - volumeHeight - 28;
const priceHeight = priceBottom - priceTop;
const visibleTickWindow = 520;

const candles = computed(() => state.value?.candles ?? []);
const trades = computed(() => state.value?.trades ?? []);
const liquidity = computed(() => state.value?.liquidity ?? []);
const analytics = computed(() => state.value?.analytics ?? null);
const prediction = computed(() => analytics.value?.prediction ?? null);
const liveSymbols = computed(() => liveMarkets.value?.[liveExchange.value] ?? []);
const isLive = computed(() => mode.value === "live");

const chartTimeline = computed(() => {
  const latestTick = state.value?.tick ?? 0;
  const minTick = Math.max(0, latestTick - visibleTickWindow);
  const maxTick = Math.max(latestTick, minTick + 1);
  return { minTick, maxTick, tickSpan: Math.max(1, maxTick - minTick) };
});

const priceRange = computed(() => {
  const { minTick } = chartTimeline.value;
  const marketPrices = [];
  candles.value
    .filter((candle) => (candle.endTick ?? candle.startTick ?? 0) >= minTick)
    .forEach((candle) => marketPrices.push(candle.high, candle.low, candle.open, candle.close));
  trades.value.filter((trade) => trade.tick >= minTick).forEach((trade) => marketPrices.push(trade.price));

  const prices = marketPrices.length
    ? marketPrices
    : liquidity.value
        .filter((line) => (line.endTick ?? state.value?.tick ?? 0) >= minTick)
        .map((line) => line.price);

  if (!prices.length) return { min: 95, max: 105 };
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const tickSize = state.value?.config?.tick_size ?? 0.01;
  const rawRange = Math.max(tickSize, max - min);
  const minimumVisibleRange = tickSize <= 0.0001 ? tickSize * 18 : tickSize * 10;
  const targetRange = Math.max(rawRange * 1.18, minimumVisibleRange);
  const mid = (min + max) / 2;
  return { min: mid - targetRange / 2, max: mid + targetRange / 2 };
});

const maxVolume = computed(() => Math.max(1, ...candles.value.map((candle) => candle.volume)));
const maxLiquidity = computed(() => Math.max(1, ...liquidity.value.map((line) => line.initialQuantity)));

const chartCandles = computed(() => {
  const { minTick, maxTick, tickSpan } = chartTimeline.value;
  const tickWidth = chartWidth / tickSpan;

  return candles.value
    .map((candle) => {
      const startTick = candle.startTick ?? candle.index * (state.value?.ticksPerCandle ?? 10);
      const endTick = candle.endTick ?? startTick + (state.value?.ticksPerCandle ?? 10);
      return { candle, startTick, endTick };
    })
    .filter(({ startTick, endTick }) => endTick >= minTick && startTick <= maxTick)
    .map(({ candle, startTick, endTick }) => {
      const x = xForTick((startTick + endTick) / 2);
      const bodyWidth = Math.max(4, Math.min(14, (endTick - startTick || 1) * tickWidth * 0.58));
      const openY = yForPrice(candle.open);
      const closeY = yForPrice(candle.close);
      const highY = yForPrice(candle.high);
      const lowY = yForPrice(candle.low);
      const up = candle.close >= candle.open;
      return {
        ...candle,
        x,
        openY,
        closeY,
        highY,
        lowY,
        up,
        bodyWidth,
        bodyY: Math.min(openY, closeY),
        bodyHeight: Math.max(3, Math.abs(closeY - openY)),
        volumeHeight: Math.max(2, (candle.volume / maxVolume.value) * (volumeHeight - 12))
      };
    });
});

const chartLiquidity = computed(() => {
  const latestTick = state.value?.tick ?? 0;
  const { minTick } = chartTimeline.value;
  const fadeTicks = 34;

  return liquidity.value
    .filter((line) => {
      const endTick = line.endTick ?? latestTick;
      return endTick >= minTick && line.startTick <= latestTick;
    })
    .map((line) => {
      const endTick = line.endTick ?? latestTick;
      const closedAge = line.endTick === null ? 0 : latestTick - line.endTick;
      const fade = line.endTick === null ? 1 : Math.max(0, 1 - closedAge / fadeTicks);
      const size = line.initialQuantity / maxLiquidity.value;
      const x1 = Math.max(0, xForTick(line.startTick));
      const x2 = Math.min(chartWidth, xForTick(endTick));
      const width = Math.max(2, x2 - x1);
      const alpha = Math.max(0.1, Math.min(0.78, size)) * fade;
      const y = yForPrice(line.price);
      return {
        ...line,
        x: x1,
        y,
        width,
        height: Math.max(3, Math.min(8, 2 + size * 7)),
        alpha
      };
    })
    .filter((line) => line.alpha > 0.02 && line.y >= priceTop - 12 && line.y <= priceBottom + 12);
});

const chartTrades = computed(() => {
  const { minTick } = chartTimeline.value;

  return trades.value
    .filter((trade) => trade.tick >= minTick)
    .map((trade) => ({
      ...trade,
      x: xForTick(trade.tick),
      y: yForPrice(trade.price)
    }));
});

const priceTicks = computed(() => {
  const { min, max } = priceRange.value;
  const steps = 6;
  return Array.from({ length: steps + 1 }, (_, index) => {
    const price = max - ((max - min) * index) / steps;
    return { price, y: yForPrice(price) };
  });
});

function yForPrice(price) {
  const { min, max } = priceRange.value;
  const normalized = (max - price) / Math.max(Number.EPSILON, max - min);
  return priceTop + normalized * priceHeight;
}

function xForTick(tick) {
  const { minTick, tickSpan } = chartTimeline.value;
  return ((tick - minTick) / tickSpan) * chartWidth;
}

function formatPrice(price) {
  if (price === null || price === undefined) return "-";
  const tickSize = state.value?.config?.tick_size ?? 0.01;
  const decimals = Math.max(0, Math.min(6, Math.ceil(-Math.log10(tickSize))));
  return Number(price).toFixed(decimals);
}

function formatQuantity(quantity) {
  if (quantity === null || quantity === undefined) return "-";
  const number = Number(quantity);
  if (number >= 1000) return number.toFixed(0);
  if (number >= 10) return number.toFixed(2);
  return number.toFixed(4);
}

function formatOrders(row) {
  if (!row?.orders) return "";
  return ` / ${row.orders}o`;
}

function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatSignedPercent(value) {
  if (value === null || value === undefined) return "-";
  const number = Number(value) * 100;
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function formatSpread(spread) {
  if (spread === null || spread === undefined) return "-";
  return formatPrice(spread);
}

function predictionLabel(value) {
  if (!value) return "-";
  if (value.direction === "up") return "UP";
  if (value.direction === "down") return "DOWN";
  return "FLAT";
}

async function request(path, options = {}) {
  error.value = "";
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `API ${response.status}`);
  }
  state.value = await response.json();
}

async function loadState() {
  loading.value = true;
  try {
    const [presetResponse, marketResponse] = await Promise.all([
      fetch("/api/presets"),
      fetch("/api/live/markets")
    ]);
    if (presetResponse.ok) {
      const payload = await presetResponse.json();
      presets.value = payload.presets ?? presets.value;
    }
    if (marketResponse.ok) {
      liveMarkets.value = await marketResponse.json();
    }
    await loadCurrentMode();
  } catch (caught) {
    error.value = caught.message;
  } finally {
    loading.value = false;
  }
}

async function loadCurrentMode() {
  if (isLive.value) {
    await refreshLive();
  } else {
    await request("/api/state");
    selectedPreset.value = state.value?.config?.symbol ?? selectedPreset.value;
  }
}

async function nextTick(ticks = 1) {
  loading.value = true;
  try {
    await request("/api/tick", {
      method: "POST",
      body: JSON.stringify({ ticks })
    });
  } catch (caught) {
    error.value = caught.message;
  } finally {
    loading.value = false;
  }
}

async function refreshLive() {
  loading.value = true;
  try {
    await request(`/api/live/state?exchange=${encodeURIComponent(liveExchange.value)}&symbol=${encodeURIComponent(liveSymbol.value)}`);
  } catch (caught) {
    error.value = caught.message;
  } finally {
    loading.value = false;
  }
}

async function autoplayStep() {
  if (!autoplay.value || autoplayBusy) return;
  autoplayBusy = true;
  try {
    if (isLive.value) {
      await refreshLive();
    } else {
      await nextTick(1);
    }
  } finally {
    autoplayBusy = false;
  }
}

function startAutoplay() {
  if (autoplayTimer) return;
  autoplay.value = true;
  autoplayTimer = window.setInterval(autoplayStep, isLive.value ? 3500 : 320);
}

function stopAutoplay() {
  autoplay.value = false;
  if (autoplayTimer) {
    window.clearInterval(autoplayTimer);
    autoplayTimer = null;
  }
}

function toggleAutoplay() {
  if (autoplay.value) {
    stopAutoplay();
  } else {
    startAutoplay();
  }
}

async function switchMode(nextMode) {
  if (mode.value === nextMode) return;
  stopAutoplay();
  mode.value = nextMode;
  await loadCurrentMode();
}

async function changeExchange() {
  stopAutoplay();
  liveSymbol.value = liveSymbols.value[0]?.symbol ?? liveSymbol.value;
  await refreshLive();
}

async function reset() {
  stopAutoplay();
  loading.value = true;
  try {
    if (isLive.value) {
      await refreshLive();
    } else {
      await request("/api/reset", {
        method: "POST",
        body: JSON.stringify({ seed: Date.now() % 100000, preset: selectedPreset.value })
      });
    }
  } catch (caught) {
    error.value = caught.message;
  } finally {
    loading.value = false;
  }
}

onMounted(loadState);
onBeforeUnmount(stopAutoplay);
</script>

<template>
  <main class="shell">
    <section class="topbar">
      <div>
        <p class="eyebrow">{{ isLive ? "Live orderbook" : "Orderbook simulation" }}</p>
        <h1>{{ isLive ? "Market Live" : "Market Simulator" }}</h1>
      </div>
      <div class="stats" v-if="state">
        <div>
          <span>Last</span>
          <strong>{{ formatPrice(state.lastPrice) }}</strong>
        </div>
        <div>
          <span>Spread</span>
          <strong>{{ formatSpread(state.spread) }}</strong>
        </div>
        <div>
          <span>{{ isLive ? "Source" : "Tick" }}</span>
          <strong>{{ isLive ? state.source?.label : state.tick }}</strong>
        </div>
        <div>
          <span>Imbalance</span>
          <strong>{{ state.imbalance }}</strong>
        </div>
        <div>
          <span>Signal</span>
          <strong :class="['signal-text', prediction?.direction]">{{ predictionLabel(prediction) }}</strong>
        </div>
      </div>
      <div class="actions">
        <div class="mode-toggle" role="group" aria-label="Mode">
          <button type="button" :class="{ active: !isLive }" @click="switchMode('simulation')">Sim</button>
          <button type="button" :class="{ active: isLive }" @click="switchMode('live')">
            <Wifi :size="16" />
            Live
          </button>
        </div>
        <template v-if="isLive">
          <select v-model="liveExchange" class="preset-select" title="Exchange" @change="changeExchange">
            <option value="binance">Binance</option>
            <option value="hyperliquid">Hyperliquid</option>
          </select>
          <select v-model="liveSymbol" class="preset-select" title="Market" @change="refreshLive">
            <option v-for="market in liveSymbols" :key="market.symbol" :value="market.symbol">{{ market.label }}</option>
          </select>
          <button class="primary-button" type="button" :disabled="loading" @click="refreshLive">
            <RefreshCw :size="18" />
            Refresh
          </button>
        </template>
        <template v-else>
          <select v-model="selectedPreset" class="preset-select" title="Instrument" @change="reset">
            <option v-for="preset in presets" :key="preset" :value="preset">{{ preset }}</option>
          </select>
          <button class="icon-button" type="button" title="Reset" :disabled="loading" @click="reset">
            <RotateCcw :size="18" />
          </button>
          <button class="primary-button" type="button" :disabled="loading" @click="nextTick(1)">
            <StepForward :size="18" />
            Next tick
          </button>
          <label class="run-control">
            <input v-model.number="runTicks" type="number" min="2" max="200" step="1" />
            <button type="button" :disabled="loading" title="Run ticks" @click="nextTick(runTicks)">
              <Play :size="17" />
            </button>
          </label>
        </template>
        <button class="autoplay-button" type="button" :class="{ active: autoplay }" :title="autoplay ? 'Pause autoplay' : 'Start autoplay'" @click="toggleAutoplay">
          <Pause v-if="autoplay" :size="18" />
          <Play v-else :size="18" />
          {{ autoplay ? "Pause" : "Auto" }}
        </button>
      </div>
    </section>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <section class="workspace" v-if="state">
      <div class="chart-panel">
        <svg class="chart" :viewBox="`0 0 ${chartWidth} ${chartHeight}`" role="img" aria-label="Candlestick and order chart">
          <rect width="100%" height="100%" class="chart-bg" />

          <g class="grid">
            <line
              v-for="tick in priceTicks"
              :key="tick.price"
              x1="0"
              :y1="tick.y"
              :x2="chartWidth"
              :y2="tick.y"
            />
            <text
              v-for="tick in priceTicks"
              :key="`label-${tick.price}`"
              :x="chartWidth - 58"
              :y="tick.y - 5"
            >
              {{ formatPrice(tick.price) }}
            </text>
          </g>

          <g class="liquidity-layer">
            <rect
              v-for="line in chartLiquidity"
              :key="line.id"
              :x="line.x"
              :y="line.y - line.height / 2"
              :width="line.width"
              :height="line.height"
              :class="line.side === 'buy' ? 'bid-liquidity' : 'ask-liquidity'"
              :opacity="line.alpha"
            />
          </g>

          <g class="candles">
            <g v-for="candle in chartCandles" :key="`${candle.index}-${candle.endTick}-${candle.volume}`">
              <line :x1="candle.x" :x2="candle.x" :y1="candle.highY" :y2="candle.lowY" :class="candle.up ? 'up-stroke' : 'down-stroke'" />
              <rect
                :x="candle.x - candle.bodyWidth / 2"
                :y="candle.bodyY"
                :width="candle.bodyWidth"
                :height="candle.bodyHeight"
                :rx="1"
                :class="candle.up ? 'up-fill' : 'down-fill'"
              />
              <rect
                :x="candle.x - candle.bodyWidth / 2"
                :y="chartHeight - candle.volumeHeight"
                :width="candle.bodyWidth"
                :height="candle.volumeHeight"
                :class="candle.up ? 'up-volume' : 'down-volume'"
              />
            </g>
          </g>

          <g class="trade-layer">
            <circle
              v-for="(trade, index) in chartTrades"
              :key="`${trade.tick}-${trade.price}-${index}`"
              :cx="trade.x"
              :cy="trade.y"
              :r="Math.min(8, 2 + trade.quantity / 4)"
              :class="trade.side === 'buy' ? 'buy-trade' : 'sell-trade'"
            />
          </g>
        </svg>
      </div>

      <aside class="book-panel">
        <div class="book-header">
          <span>Orderbook</span>
          <strong>{{ formatPrice(state.bestBid) }} / {{ formatPrice(state.bestAsk) }}</strong>
        </div>

        <section v-if="analytics" class="signal-panel">
          <div class="signal-card" :class="prediction?.direction">
            <span>Prediction {{ prediction?.horizon }}</span>
            <strong>{{ predictionLabel(prediction) }} {{ prediction?.confidence }}%</strong>
          </div>
          <div class="metric-grid">
            <div>
              <span>Microprice</span>
              <strong>{{ formatPrice(analytics.orderbook.microprice) }}</strong>
            </div>
            <div>
              <span>Spread %</span>
              <strong>{{ formatPercent(analytics.orderbook.spreadPct) }}</strong>
            </div>
            <div>
              <span>Momentum</span>
              <strong>{{ formatSignedPercent(analytics.flow.momentumShort) }}</strong>
            </div>
            <div>
              <span>Flow</span>
              <strong>{{ analytics.flow.tradeFlow.toFixed(3) }}</strong>
            </div>
            <div>
              <span>Order pressure</span>
              <strong>{{ analytics.orderbook.orderPressure.toFixed(3) }}</strong>
            </div>
            <div>
              <span>Orders bid/ask</span>
              <strong>{{ analytics.orderbook.bidOrders }} / {{ analytics.orderbook.askOrders }}</strong>
            </div>
          </div>
          <div class="reason-list" v-if="prediction?.reasons?.length">
            <span v-for="reason in prediction.reasons" :key="reason">{{ reason }}</span>
          </div>
          <div class="depth-bands">
            <div v-for="band in analytics.depthBands" :key="band.label">
              <span>{{ band.label }}</span>
              <strong>{{ formatQuantity(band.bid) }} / {{ formatQuantity(band.ask) }}</strong>
              <small>{{ band.imbalance.toFixed(3) }}</small>
            </div>
          </div>
        </section>

        <table>
          <thead>
            <tr>
              <th>Side</th>
              <th>Price</th>
              <th>Qty</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ask in [...state.orderbook.asks].reverse()" :key="`ask-${ask.price}`" class="ask-row">
              <td>Ask</td>
              <td>{{ formatPrice(ask.price) }}</td>
              <td>
                <span class="depth-bar ask-depth" :style="{ width: `${(ask.quantity / state.orderbook.maxQuantity) * 100}%` }"></span>
                {{ formatQuantity(ask.quantity) }}{{ formatOrders(ask) }}
              </td>
            </tr>
            <tr class="mid-row">
              <td colspan="3">Last {{ formatPrice(state.lastPrice) }}</td>
            </tr>
            <tr v-for="bid in state.orderbook.bids" :key="`bid-${bid.price}`" class="bid-row">
              <td>Bid</td>
              <td>{{ formatPrice(bid.price) }}</td>
              <td>
                <span class="depth-bar bid-depth" :style="{ width: `${(bid.quantity / state.orderbook.maxQuantity) * 100}%` }"></span>
                {{ formatQuantity(bid.quantity) }}{{ formatOrders(bid) }}
              </td>
            </tr>
          </tbody>
        </table>
      </aside>
    </section>
  </main>
</template>
