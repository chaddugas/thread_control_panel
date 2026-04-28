<template>
  <span
    class="ticker"
    :data-dir="dir"
  >
    <Transition :name="`ticker-${dir}`">
      <span
        :key="String(value)"
        class="ticker-slot"
      >
        <slot :value="value">{{ value }}</slot>
      </span>
    </Transition>
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = defineProps<{
  /** Driving value — also used as the transition key. */
  value: string | number;
  /** Force a slide direction. Otherwise auto-detected for numeric values. */
  direction?: "up" | "down";
}>();

const detected = ref<"up" | "down">("up");

watch(
  () => props.value,
  (newVal, oldVal) => {
    if (props.direction) return;
    if (typeof newVal === "number" && typeof oldVal === "number") {
      detected.value = newVal >= oldVal ? "up" : "down";
    }
    // For non-numeric values we leave detected as-is — slide direction
    // is mostly a tactile concern and "up" reads as forward motion.
  },
);

const dir = computed(() => props.direction ?? detected.value);
</script>

<style scoped>
.ticker {
  display: inline-flex;
  position: relative;
  overflow: hidden;
  vertical-align: baseline;
  align-items: baseline;
  line-height: inherit;
}

.ticker-slot {
  display: inline-block;
  white-space: nowrap;
}

.ticker-up-enter-active,
.ticker-up-leave-active,
.ticker-down-enter-active,
.ticker-down-leave-active {
  transition:
    transform 380ms cubic-bezier(0.32, 0.05, 0.2, 1),
    opacity 320ms ease;
}

.ticker-up-leave-active,
.ticker-down-leave-active {
  position: absolute;
  inset: 0;
}

.ticker-up-enter-from {
  transform: translateY(85%);
  opacity: 0;
}

.ticker-up-leave-to {
  transform: translateY(-85%);
  opacity: 0;
}

.ticker-down-enter-from {
  transform: translateY(-85%);
  opacity: 0;
}

.ticker-down-leave-to {
  transform: translateY(85%);
  opacity: 0;
}
</style>
