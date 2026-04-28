<template>
  <div
    v-if="visible"
    class="splash"
    role="presentation"
  >
    <div class="frame">
      <div class="head">
        <span class="date shared-vt-date">
          <Ticker :value="dateLine" />
        </span>
        <span class="clock serif-italic shared-vt-clock">
          <Ticker :value="clockLine" />
        </span>
      </div>

      <div class="hero">
        <template v-if="alarm">
          <span class="label">A note</span>
          <span class="time alarm-line">{{ alarm }}</span>
          <span class="amount serif-italic">tap to attend</span>
        </template>
        <template v-else-if="paused">
          <span class="label">Today is paused</span>
          <span class="time-paused serif-italic">No plates are scheduled.</span>
        </template>
        <template v-else-if="nextLine">
          <span class="label shared-vt-upnext-label">Up next at</span>
          <div class="time shared-vt-hero-time">
            <Ticker :value="`${nextLine.hour} ${nextLine.meridiem}`">
              <span class="time-row">
                <span class="hour">{{ nextLine.hour }}</span>
                <span class="meridiem">{{ nextLine.meridiem }}</span>
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
            class="relative shared-vt-relative"
          >
            <Ticker :value="relativeLine" />
          </span>
        </template>
        <template v-else>
          <span class="label">Today's menu</span>
          <span class="time-paused serif-italic">Awaiting the next plate.</span>
        </template>
      </div>

      <div class="footer">
        <span class="ornament">&#x276E; &#x2756; &#x276F;</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useFeeder } from "@/composables/useFeeder";
import { formatTwelfths } from "@/utils/fractions";
import Ticker from "./Ticker.vue";

defineProps<{ visible: boolean }>();

const feeder = useFeeder();
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

const dateLine = computed(() =>
  now.value
    .toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    })
    .toUpperCase(),
);

const clockLine = computed(() => {
  const h = now.value.getHours();
  const m = now.value.getMinutes();
  const ampm = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
});

const paused = computed(() => !feeder.scheduleEnabled.value);

const alarm = computed(() => {
  if (feeder.alarms.value.dispenserJam) return "The dispenser is jammed";
  if (feeder.alarms.value.outOfFood) return "The food bin is low";
  return "";
});

const nextPlan = computed(() => {
  const id = feeder.status.value.nextPlanId;
  if (id === null) return null;
  return feeder.schedule.value.find((p) => p.planID === id) ?? null;
});

const nextLine = computed(() => {
  const at = feeder.status.value.nextFeedAt;
  if (!at) return null;
  const h = at.getHours();
  const m = at.getMinutes();
  const meridiem = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return {
    hour: `${h12}:${String(m).padStart(2, "0")}`,
    meridiem,
  };
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
  const at = feeder.status.value.nextFeedAt;
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
.splash {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: stretch;
  justify-content: stretch;
  background:
    radial-gradient(circle at 22% -10%, var(--ambient-glow-1), transparent 55%),
    radial-gradient(circle at 92% 105%, var(--ambient-glow-2), transparent 55%),
    var(--ink-bg);
  transition: var(--theme-transition);
}

.frame {
  flex: 1;
  display: grid;
  grid-template-rows: auto 1fr auto;
  padding: clamp(1.2rem, 2.4vw, 2rem) clamp(1.6rem, 3.5vw, 3.4rem);
  position: relative;
}

.frame::before,
.frame::after {
  content: "";
  position: absolute;
  left: clamp(1.6rem, 3.5vw, 3.4rem);
  right: clamp(1.6rem, 3.5vw, 3.4rem);
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    var(--hairline-strong) 12%,
    var(--hairline-strong) 88%,
    transparent
  );
}

.frame::before {
  top: clamp(3.4rem, 5.4vw, 4.8rem);
}

.frame::after {
  bottom: clamp(3.4rem, 5.4vw, 4.8rem);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.date {
  font-family: var(--body);
  font-size: 0.78rem;
  letter-spacing: 0.32em;
  color: var(--cream-muted);
}

.clock {
  font-size: 1rem;
  color: var(--cream-soft);
  letter-spacing: 0.01em;
}

.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: clamp(0.85rem, 2vw, 1.5rem);
  text-align: center;
  padding: clamp(1.5rem, 3vw, 2.5rem) 0;
}

.label {
  font-family: var(--body);
  font-size: 0.78rem;
  font-weight: 500;
  letter-spacing: 0.34em;
  text-transform: uppercase;
  color: var(--cream-muted);
}

.time {
  display: inline-flex;
  align-items: baseline;
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 50, "WONK" 1;
  font-feature-settings: "lnum", "tnum";
  color: var(--cream);
  line-height: 0.9;
  letter-spacing: -0.02em;
}

.time-row {
  display: inline-flex;
  align-items: baseline;
  gap: 0.4em;
}

.hour {
  font-size: clamp(7rem, 16vw, 13rem);
  font-weight: 320;
}

.meridiem {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: clamp(2rem, 4vw, 3.4rem);
  color: var(--cream-muted);
  letter-spacing: 0.01em;
}

.amount {
  font-size: clamp(1.4rem, 2.4vw, 2rem);
  color: var(--cream-soft);
  letter-spacing: 0.01em;
}

.relative {
  font-family: var(--body);
  font-size: 0.95rem;
  font-style: italic;
  letter-spacing: 0.05em;
  color: var(--cream-muted);
}

.alarm-line {
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 60, "WONK" 1;
  font-size: clamp(2.6rem, 5vw, 4.2rem);
  color: var(--rust);
  font-weight: 360;
  line-height: 1;
  letter-spacing: -0.01em;
}

.time-paused {
  font-size: clamp(1.6rem, 2.6vw, 2.2rem);
  color: var(--cream-muted);
}

.footer {
  display: flex;
  justify-content: center;
  padding-top: 0.4rem;
}

.ornament {
  font-family: var(--display);
  font-variation-settings: "opsz" 14, "SOFT" 100, "WONK" 1;
  font-size: 1rem;
  letter-spacing: 0.4em;
  color: var(--brass);
}
</style>
