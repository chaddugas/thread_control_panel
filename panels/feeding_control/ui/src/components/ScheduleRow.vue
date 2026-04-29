<template>
  <li
    :data-row-key="plan.key"
    :data-row-index="rowIndex"
    :class="[
      'row vt-row',
      {
        open,
        next: isNext,
        skipped: plan.feed_state === 'Skipped',
        served: plan.feed_state === 'Completed',
      },
    ]"
  >
    <button
      class="head"
      type="button"
      :tabindex="open || isLocked ? -1 : 0"
      :aria-hidden="open ? 'true' : undefined"
      :disabled="isLocked"
      @click="onHeadClick"
    >
      <span class="marker">
        <span class="lozenge" />
      </span>
      <span class="time">
        <span class="hour">{{ hourMinute }}</span>
        <span class="meridiem">{{ meridiem }}</span>
      </span>
      <span class="separator">&mdash;</span>
      <span class="amount">
        <span class="qty frac">{{ formatTwelfths(plan.amount_raw) }}</span>
        <span class="unit">cup</span>
      </span>
      <span class="state-label">
        <Ticker :value="stateLabel" />
      </span>
    </button>
    <div
      class="actions"
      :inert="!open"
      @click.self="$emit('close')"
    >
      <button
        class="action skip"
        type="button"
        :disabled="plan.feed_state === 'Skipped'"
        @click="$emit('skip', plan)"
      >
        Skip this plate
      </button>
      <button
        class="action unskip"
        type="button"
        :disabled="plan.feed_state !== 'Skipped'"
        @click="$emit('unskip', plan)"
      >
        Put it back
      </button>
    </div>
  </li>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { Plan } from "@/types";
import { formatTwelfths } from "@/utils/fractions";
import Ticker from "./Ticker.vue";

const props = defineProps<{
  plan: Plan;
  isNext?: boolean;
  open?: boolean;
  rowIndex?: number;
}>();
const emit = defineEmits<{
  (e: "toggle"): void;
  (e: "close"): void;
  (e: "skip", plan: Plan): void;
  (e: "unskip", plan: Plan): void;
}>();

const parsed = computed(() => {
  const [hStr, mStr] = props.plan.time.split(":");
  const h = Number(hStr);
  const m = Number(mStr);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  const ampm = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return { h12, m, ampm };
});

const hourMinute = computed(() => {
  if (!parsed.value) return props.plan.time;
  return `${parsed.value.h12}:${String(parsed.value.m).padStart(2, "0")}`;
});

const meridiem = computed(() => parsed.value?.ampm ?? "");

const stateLabel = computed(() => {
  if (props.plan.feed_state === "Skipped") return "skipped";
  if (props.plan.feed_state === "Completed") return "served";
  if (props.isNext) return "next";
  return "";
});

const isLocked = computed(() => props.plan.feed_state === "Completed");

function onHeadClick(): void {
  if (isLocked.value) return;
  emit("toggle");
}
</script>

<style scoped>
.row {
  position: relative;
  list-style: none;
  background: transparent;
  transition: background 220ms ease;
}


.head {
  display: grid;
  grid-template-columns: 1.6rem auto auto auto 1fr;
  align-items: baseline;
  width: 100%;
  gap: 0.85rem;
  padding: 0.85rem 1rem;
  background: transparent;
  border: 0;
  text-align: left;
  cursor: pointer;
  color: inherit;
  transition: opacity 240ms ease;
}

.row.open .head {
  opacity: 0;
  pointer-events: none;
}

.marker {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  height: 1em;
}

.lozenge {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: transparent;
  border: 1px solid var(--cream-faint);
  transition:
    background 200ms ease,
    border-color 200ms ease,
    transform 200ms ease;
}

.row.next .lozenge {
  background: var(--brass);
  border-color: var(--brass);
  box-shadow: 0 0 0 4px var(--brass-veil);
  animation: lozenge-breath 2.6s ease-in-out infinite;
}

@keyframes lozenge-breath {
  0%,
  100% {
    box-shadow: 0 0 0 4px var(--brass-veil);
    transform: scale(1);
  }
  50% {
    box-shadow: 0 0 0 7px var(--brass-veil-strong);
    transform: scale(1.08);
  }
}

.time {
  display: inline-flex;
  align-items: baseline;
  gap: 0.32rem;
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 30, "WONK" 1;
  color: var(--cream);
  font-feature-settings: "lnum", "tnum";
  transition:
    color 380ms ease,
    text-decoration-color 380ms ease;
}

.hour {
  font-size: clamp(1.85rem, 3.6vw, 2.6rem);
  font-weight: 360;
  letter-spacing: -0.01em;
  line-height: 1;
  transition: color 380ms ease;
}

.meridiem {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: 0.95rem;
  color: var(--cream-muted);
  letter-spacing: 0.02em;
  transition: color 380ms ease;
}

.separator {
  font-family: var(--display);
  color: var(--cream-faint);
  font-size: 1.6rem;
  line-height: 1;
  align-self: center;
}

.amount {
  display: inline-flex;
  align-items: baseline;
  gap: 0.4rem;
}

.qty {
  font-family: var(--display);
  font-variation-settings: "opsz" 60, "SOFT" 40, "WONK" 1;
  font-feature-settings: "frac";
  font-size: 1.45rem;
  font-weight: 380;
  color: var(--cream);
  transition:
    color 380ms ease,
    text-decoration-color 380ms ease;
}

.unit {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: 0.95rem;
  color: var(--cream-muted);
  letter-spacing: 0.02em;
  transition:
    color 380ms ease,
    text-decoration-color 380ms ease;
}

.state-label {
  justify-self: end;
  align-self: center;
  font-family: var(--body);
  font-size: 0.66rem;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--cream-muted);
}

.row.next .state-label {
  color: var(--brass);
}

.row.served .head {
  cursor: default;
}

.row.served .time,
.row.served .qty,
.row.served .meridiem,
.row.served .unit {
  color: var(--cream-muted);
}

.row.skipped .time,
.row.skipped .qty,
.row.skipped .meridiem,
.row.skipped .unit {
  color: var(--cream-faint);
  text-decoration: line-through;
  text-decoration-color: var(--hairline-strong);
  text-decoration-thickness: 1px;
}

.actions {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: stretch;
  justify-content: stretch;
  gap: 0.5rem;
  padding: 0.4rem 0.6rem;
  opacity: 0;
  pointer-events: none;
  transition: opacity 240ms ease;
}

.row.open .actions {
  opacity: 1;
  pointer-events: auto;
}

.action {
  flex: 1;
  padding: 0 1rem;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  border-radius: 6px;
  color: var(--cream);
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 60, "WONK" 1;
  font-size: 1.15rem;
  font-weight: 380;
  letter-spacing: 0.005em;
  cursor: pointer;
  transition:
    background 160ms ease,
    border-color 160ms ease,
    color 160ms ease;
}

.action.skip:not(:disabled) {
  border-color: var(--brass-veil-strong);
  color: var(--brass);
}

.action.unskip:not(:disabled) {
  border-color: rgba(147, 167, 145, 0.45);
  color: var(--sage);
}

.action:hover:not(:disabled),
.action:active:not(:disabled) {
  background: var(--row-active);
}

.action:disabled {
  opacity: 0.28;
  cursor: not-allowed;
}
</style>
