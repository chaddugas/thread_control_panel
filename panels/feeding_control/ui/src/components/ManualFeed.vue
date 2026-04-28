<template>
  <section class="manual-feed">
    <div class="stepper">
      <button
        class="step"
        type="button"
        :disabled="!canPrev"
        aria-label="Decrease portion"
        @click="prev"
      >
        <span class="sign">&minus;</span>
      </button>
      <div class="qty-block">
        <span class="qty frac">{{ formatTwelfths(twelfths) }}</span>
        <span class="unit">{{ unit }}</span>
      </div>
      <button
        class="step"
        type="button"
        :disabled="!canNext"
        aria-label="Increase portion"
        @click="next"
      >
        <span class="sign">&plus;</span>
      </button>
    </div>
    <button
      class="feed-btn"
      type="button"
      :disabled="!options.length"
      @click="feed"
    >
      <span class="label">Feed now</span>
      <span
        class="ornament"
        aria-hidden="true"
      >&#x276F;</span>
    </button>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useFeeder } from "@/composables/useFeeder";
import { formatTwelfths } from "@/utils/fractions";

const feeder = useFeeder();
const options = computed(() => feeder.manualFeedQty.value.options);
const idx = ref(0);

let synced = false;
watch(
  () => feeder.manualFeedQty.value,
  (cur) => {
    if (synced || cur.options.length === 0) return;
    const i = cur.options.indexOf(cur.current);
    idx.value = i >= 0 ? i : 0;
    synced = true;
  },
  { immediate: true },
);

const max = computed(() => Math.max(0, options.value.length - 1));
const canPrev = computed(() => idx.value > 0);
const canNext = computed(() => idx.value < max.value);

const twelfths = computed(() => (idx.value + 1) * 3);
const unit = computed(() => (twelfths.value === 12 ? "cup" : "cups"));

function prev(): void {
  if (canPrev.value) idx.value -= 1;
}

function next(): void {
  if (canNext.value) idx.value += 1;
}

function feed(): void {
  const opt = options.value[idx.value];
  if (opt) feeder.manualFeed(opt);
}
</script>

<style scoped>
.manual-feed {
  display: inline-flex;
  align-items: stretch;
  gap: 0.85rem;
}

.stepper {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.4rem;
  border: 1px solid var(--hairline-strong);
  border-radius: 999px;
  transition: var(--theme-transition);
}

.step {
  width: 2.6rem;
  height: 2.6rem;
  border-radius: 999px;
  border: 0;
  background: transparent;
  color: var(--cream);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background 160ms ease,
    color 160ms ease;
}

.step:hover:not(:disabled) {
  background: var(--brass-veil);
  color: var(--brass);
}

.step:disabled {
  opacity: 0.32;
  cursor: not-allowed;
}

.sign {
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 30, "WONK" 1;
  font-size: 1.45rem;
  line-height: 1;
  font-weight: 320;
}

.qty-block {
  min-width: 5rem;
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.32rem;
  padding: 0 0.4rem;
}

.qty {
  font-family: var(--display);
  font-variation-settings: "opsz" 60, "SOFT" 30, "WONK" 1;
  font-feature-settings: "frac";
  font-size: 1.6rem;
  font-weight: 380;
  line-height: 1;
  color: var(--cream);
  letter-spacing: -0.01em;
}

.unit {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: 0.9rem;
  color: var(--cream-muted);
  letter-spacing: 0.02em;
}

.feed-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0 1.4rem;
  height: 3.1rem;
  background: var(--brass);
  border: 0;
  border-radius: 999px;
  color: var(--feed-button-fg);
  font-family: var(--display);
  font-variation-settings: "opsz" 14, "SOFT" 50, "WONK" 1;
  font-size: 1.05rem;
  font-weight: 460;
  letter-spacing: 0.005em;
  cursor: pointer;
  transition:
    background 160ms ease,
    transform 160ms ease,
    box-shadow 200ms ease,
    color 600ms ease,
    filter 160ms ease;
  box-shadow: 0 6px 18px -10px var(--brass-veil-strong);
}

.feed-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}

.feed-btn:active:not(:disabled) {
  transform: translateY(1px);
}

.feed-btn:disabled {
  background: var(--hairline);
  color: var(--cream-faint);
  cursor: not-allowed;
  box-shadow: none;
}

.ornament {
  font-family: var(--display);
  font-variation-settings: "opsz" 14, "SOFT" 100, "WONK" 1;
  font-size: 0.9rem;
  letter-spacing: 0.02em;
  opacity: 0.7;
}
</style>
