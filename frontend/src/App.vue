<script setup>
import { computed, onMounted, ref } from "vue";
import { Play, RotateCcw, StepForward } from "lucide-vue-next";

const state = ref(null);
const loading = ref(false);
const runTicks = ref(10);
const presets = ref(["BTCUSD"]);
const selectedPreset = ref("BTCUSD");

const chartWidth = 1080;
const chartHeight = 650;
const volumeHeight = 96;
const pricePad = 34;

const candles = computed(() => state.value?.candles ?? []);
const trades = computed(() => state.value?.trades ?? []);
const liquidity = computed(() => state.value?.liquidity ?? []);

const priceRange = computed(() => {
  const prices = [];
  candles.value.forEach((candle) => prices.push(candle.high, candle.low));
  trades.value.forEach((trade) => prices.push(trade.price));
  liquidity.value.slice(-800).forEach((line) => prices.push(line.price));
  if (!prices.length) return { min: 95, max: 105 };
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const mid = (min + max) / 2;
  const tickSize = state.value?.config?.tick_size ?? 0.01;
  const pad = Math.max(tickSize * 20, mid * 0.0002, (max - min) * 0.18);
  return { min: min - pad, max: max + pad };
});

const maxVolume = computed(() => Math.max(1, ...candles.value.map((candle) => candle.volume)));
const maxLiquidity = computed(() => Math.max(1, ...liquidity.value.map((line) => line.initialQuantity)));

const chartCandles = computed(() => {
  const count = Math.max(1, candles.value.length);
  const step = (chartWidth - 48) / count;
  const bodyWidth = Math.max(5, Math.min(14, step * 0.58));

  return candles.value.map((candle, index) => {
    const x = 24 + index * step + step / 2;
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
  const minTick = Math.max(0, latestTick - 170);
  const tickSpan = Math.max(1, latestTick - minTick);
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
      const x1 = Math.max(0, ((line.startTick - minTick) / tickSpan) * chartWidth);
      const x2 = Math.min(chartWidth, ((endTick - minTick) / tickSpan) * chartWidth);
      const width = Math.max(2, x2 - x1);
      const alpha = Math.max(0.1, Math.min(0.78, size)) * fade;
      return {
        ...line,
        x: x1,
        y: yForPrice(line.price),
        width,
        height: Math.max(3, Math.min(8, 2 + size * 7)),
        alpha
      };
    })
    .filter((line) => line.alpha > 0.02);
});

const chartTrades = computed(() => {
  const latestTick = state.value?.tick ?? 0;
  const minTick = Math.max(0, latestTick - 170);
  const tickSpan = Math.max(1, latestTick - minTick);

  return trades.value
    .filter((trade) => trade.tick >= minTick)
    .map((trade) => ({
      ...trade,
      x: ((trade.tick - minTick) / tickSpan) * chartWidth,
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
  const usableHeight = chartHeight - volumeHeight - pricePad;
  return pricePad + ((max - price) / Math.max(1, max - min)) * usableHeight;
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

async function reset() {
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
