<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Pause, Play, RotateCcw, StepForward } from "lucide-vue-next";

const state = ref(null);
const loading = ref(false);
const runTicks = ref(10);
const presets = ref(["BTCUSD"]);
const selectedPreset = ref("BTCUSD");
const autoplay = ref(false);
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
  const { minTick, maxTick } = chartTimeline.value;
  const { tickSpan } = chartTimeline.value;
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
  const decimals = Math.max(0, Math.min(5, Math.ceil(-Math.log10(tickSize))));
  return Number(price).toFixed(decimals);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  state.value = await response.json();
}

async function loadState() {
  const presetResponse = await fetch("/api/presets");
  if (presetResponse.ok) {
    const payload = await presetResponse.json();
    presets.value = payload.presets ?? presets.value;
  }
  await request("/api/state");
  selectedPreset.value = state.value?.config?.symbol ?? selectedPreset.value;
}

async function nextTick(ticks = 1) {
  loading.value = true;
  try {
    await request("/api/tick", {
      method: "POST",
      body: JSON.stringify({ ticks })
    });
  } finally {
    loading.value = false;
  }
}

async function autoplayStep() {
  if (!autoplay.value || autoplayBusy) return;
  autoplayBusy = true;
  try {
    await nextTick(1);
  } finally {
    autoplayBusy = false;
  }
}

function startAutoplay() {
  if (autoplayTimer) return;
  autoplay.value = true;
  autoplayTimer = window.setInterval(autoplayStep, 320);
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

async function reset() {
  stopAutoplay();
  loading.value = true;
  try {
    await request("/api/reset", {
      method: "POST",
      body: JSON.stringify({ seed: Date.now() % 100000, preset: selectedPreset.value })
    });
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
        <p class="eyebrow">Orderbook simulation</p>
        <h1>Market Simulator</h1>
      </div>
      <div class="stats" v-if="state">
        <div>
          <span>Last</span>
          <strong>{{ formatPrice(state.lastPrice) }}</strong>
        </div>
        <div>
          <span>Spread</span>
          <strong>{{ state.spread ?? "-" }}</strong>
        </div>
        <div>
          <span>Tick</span>
          <strong>{{ state.tick }}</strong>
        </div>
        <div>
          <span>Imbalance</span>
          <strong>{{ state.imbalance }}</strong>
        </div>
      </div>
      <div class="actions">
        <select v-model="selectedPreset" class="preset-select" title="Instrument" @change="reset">
          <option v-for="preset in presets" :key="preset" :value="preset">{{ preset }}</option>
        </select>
        <button class="icon-button" type="button" title="Reset" :disabled="loading" @click="reset">
          <RotateCcw :size="18" />
        </button>
        <button class="autoplay-button" type="button" :class="{ active: autoplay }" :title="autoplay ? 'Pause autoplay' : 'Start autoplay'" @click="toggleAutoplay">
          <Pause v-if="autoplay" :size="18" />
          <Play v-else :size="18" />
          {{ autoplay ? "Pause" : "Autoplay" }}
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
      </div>
    </section>

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
            <g v-for="candle in chartCandles" :key="`${candle.index}-${candle.volume}`">
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
                {{ ask.quantity }}
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
                {{ bid.quantity }}
              </td>
            </tr>
          </tbody>
        </table>
      </aside>
    </section>
  </main>
</template>
