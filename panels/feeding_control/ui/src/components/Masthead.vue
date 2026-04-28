<template>
  <div class="masthead">
    <div class="meta">
      <span class="date shared-vt-date">
        <Ticker :value="dateLine" />
      </span>
      <span
        class="bullet"
        aria-hidden="true"
      >&middot;</span>
      <span class="clock serif-italic shared-vt-clock">
        <Ticker :value="clockLine" />
      </span>
    </div>
    <h1 class="title">
      Today's <em>Menu</em>
    </h1>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import Ticker from "./Ticker.vue";

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
</script>

<style scoped>
.masthead {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  line-height: 1;
}

.meta {
  display: inline-flex;
  align-items: baseline;
  gap: 0.55rem;
  white-space: nowrap;
}

.date {
  font-family: var(--body);
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.28em;
  color: var(--cream-muted);
}

.bullet {
  font-family: var(--display);
  font-size: 0.85rem;
  color: var(--brass);
  transform: translateY(-1px);
}

.clock {
  font-size: 0.95rem;
  color: var(--cream-soft);
  letter-spacing: 0.01em;
  font-feature-settings: "lnum", "tnum";
}

.title {
  margin: 0;
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 40, "WONK" 1;
  font-weight: 380;
  font-size: clamp(2.4rem, 4.5vw, 3.4rem);
  line-height: 0.95;
  letter-spacing: -0.015em;
  color: var(--cream);
}

.title em {
  font-style: italic;
  font-variation-settings: "opsz" 144, "SOFT" 100, "WONK" 1;
  color: var(--brass);
  font-weight: 360;
}
</style>
