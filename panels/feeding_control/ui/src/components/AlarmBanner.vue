<template>
  <Transition name="fade">
    <div
      v-if="message"
      :class="['banner', kind]"
      role="alert"
    >
      <span
        class="sigil"
        aria-hidden="true"
      >&#x2756;</span>
      <span class="message">{{ message }}</span>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useFeeder } from "@/composables/useFeeder";

const { alarms } = useFeeder();

const message = computed(() => {
  if (alarms.value.dispenserJam) return "The dispenser is jammed.";
  if (alarms.value.outOfFood) return "The food bin is running low.";
  return "";
});

const kind = computed(() =>
  alarms.value.dispenserJam ? "critical" : "warn",
);
</script>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin: 0 var(--pad) var(--pad);
  padding: 0.95rem 1.15rem;
  border-radius: 4px;
  border-left: 2px solid var(--brass);
  background: var(--brass-veil);
  color: var(--cream);
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 60, "WONK" 1;
  font-size: 1rem;
  letter-spacing: 0.005em;
  transition: var(--theme-transition);
}

.banner.critical {
  border-left-color: var(--rust);
  background: var(--rust-veil);
}

.sigil {
  font-style: normal;
  color: var(--brass);
  font-size: 0.95rem;
  letter-spacing: 0;
  transform: translateY(-1px);
}

.banner.critical .sigil {
  color: var(--rust);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 240ms ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
