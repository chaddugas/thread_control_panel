<template>
  <section class="card">
    <header class="head">
      <span class="eyebrow">The day so far</span>
    </header>

    <div class="hero">
      <span class="label shared-vt-upnext-label">Up next at</span>
      <template v-if="status.nextFeedAt">
        <div class="time shared-vt-hero-time">
          <Ticker
            :value="`${formatHourMinute(status.nextFeedAt)} ${formatMeridiem(status.nextFeedAt)}`"
          >
            <span class="time-row">
              <span class="hour">{{ formatHourMinute(status.nextFeedAt) }}</span>
              <span class="meridiem">{{ formatMeridiem(status.nextFeedAt) }}</span>
            </span>
          </Ticker>
        </div>
        <span
          v-if="amountLine"
          class="amount serif-italic shared-vt-amount"
        >
          &mdash;&nbsp;<Ticker :value="amountLine" />&nbsp;&mdash;
        </span>
        <span
          v-if="relativeLine"
          class="relative serif-italic shared-vt-relative"
        >
          <Ticker :value="relativeLine" />
        </span>
      </template>
      <span
        v-else
        class="time-empty serif-italic"
      >no plates ahead</span>
    </div>

    <div class="rule" />

    <div class="lines">
      <div class="line">
        <span class="line-label eyebrow">Last served</span>
        <span class="line-value">
          <template v-if="status.lastFeedAt">
            <Ticker
              :value="`${formatHourMinute(status.lastFeedAt)} ${formatMeridiem(status.lastFeedAt)}`"
            >
              <span class="time-line">
                <span class="hour-sm">{{ formatHourMinute(status.lastFeedAt) }}</span>
                <span class="meridiem-sm">{{ formatMeridiem(status.lastFeedAt) }}</span>
              </span>
            </Ticker>
          </template>
          <span
            v-else
            class="serif-italic muted"
          >not yet today</span>
        </span>
      </div>
      <div class="line">
        <span class="line-label eyebrow">Today</span>
        <span class="line-value">
          <span class="tally serif-italic">
            <Ticker
              :value="status.todayFeedCount"
              direction="up"
            >
              <span class="tally-num">{{ status.todayFeedCount }}</span>
            </Ticker>
            {{ status.todayFeedCount === 1 ? "plate" : "plates" }}
          </span>
        </span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useFeeder } from "@/composables/useFeeder";
import { formatTwelfths } from "@/utils/fractions";
import Ticker from "./Ticker.vue";

const feeder = useFeeder();
const status = feeder.status;

const now = ref(new Date());
let timer: number | undefined;

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = new Date();
  }, 30_000);
});

onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer);
});

function formatHourMinute(d: Date): string {
  const h = d.getHours();
  const m = d.getMinutes();
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")}`;
}

function formatMeridiem(d: Date): string {
  return d.getHours() >= 12 ? "pm" : "am";
}

const nextPlan = computed(() => {
  const id = status.value.nextPlanId;
  if (id === null) return null;
  return feeder.schedule.value.find((p) => p.planID === id) ?? null;
});

const amountLine = computed(() => {
  const plan = nextPlan.value;
  if (plan && plan.amount_raw > 0) {
    const cups = formatTwelfths(plan.amount_raw);
    return `${cups} ${plan.amount_raw === 12 ? "cup" : "cups"}`;
  }
  return "";
});

const relativeLine = computed(() => {
  const at = status.value.nextFeedAt;
  if (!at) return "";
  const minutes = Math.round((at.getTime() - now.value.getTime()) / 60_000);
  if (minutes <= 0) return "any moment now";
  if (minutes < 60) return `in ${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in about ${hours} hour${hours === 1 ? "" : "s"}`;
  return "";
});
</script>

<style scoped>
.card {
  padding: 1rem 1.25rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.head {
  margin-bottom: 0.2rem;
}

.hero {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.45rem;
  padding: 0.6rem 0 0.6rem;
}

.label {
  font-family: var(--body);
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--cream-muted);
}

.time {
  display: inline-flex;
  align-items: baseline;
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 40, "WONK" 1;
  font-feature-settings: "lnum", "tnum";
  color: var(--cream);
  line-height: 0.95;
  letter-spacing: -0.015em;
}

.time-row {
  display: inline-flex;
  align-items: baseline;
  gap: 0.32rem;
}

.hour {
  font-size: clamp(3.2rem, 5vw, 4.6rem);
  font-weight: 340;
}

.meridiem {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: clamp(1.05rem, 1.6vw, 1.4rem);
  color: var(--cream-muted);
  letter-spacing: 0.02em;
}

.amount {
  font-size: 1rem;
  color: var(--cream-soft);
  letter-spacing: 0.005em;
}

.relative {
  font-size: 0.9rem;
  color: var(--cream-muted);
  letter-spacing: 0.005em;
}

.time-empty {
  font-size: 1.6rem;
  color: var(--cream-faint);
}

.rule {
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    var(--hairline-strong) 12%,
    var(--hairline-strong) 88%,
    transparent
  );
  margin: 0.2rem 0;
}

.lines {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}

.line-label {
  font-size: 0.65rem;
  letter-spacing: 0.28em;
}

.line-value {
  font-family: var(--display);
  font-size: 1rem;
  color: var(--cream);
}

.time-line {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
  font-feature-settings: "lnum", "tnum";
}

.hour-sm {
  font-size: 1.25rem;
  font-variation-settings: "opsz" 60, "SOFT" 30, "WONK" 1;
  letter-spacing: -0.005em;
}

.meridiem-sm {
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: 0.85rem;
  color: var(--cream-muted);
  letter-spacing: 0.02em;
}

.tally {
  font-size: 1.1rem;
  color: var(--cream-soft);
}

.tally-num {
  font-style: normal;
  font-variation-settings: "opsz" 60, "SOFT" 30, "WONK" 1;
  font-feature-settings: "lnum", "tnum";
  font-size: 1.3rem;
  color: var(--cream);
  margin-right: 0.18rem;
}

.muted {
  color: var(--cream-faint);
}
</style>
