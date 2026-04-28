<template>
  <Transition name="drawer">
    <aside
      v-if="open"
      class="overlay"
      @click.self="$emit('close')"
    >
      <div class="drawer">
        <header class="head">
          <div>
            <span class="eyebrow">Panel</span>
            <h2 class="title">
              Settings
            </h2>
          </div>
          <button
            class="close"
            type="button"
            aria-label="Close"
            @click="$emit('close')"
          >
            <span aria-hidden="true">&times;</span>
          </button>
        </header>

        <section class="section">
          <span class="eyebrow">The schedule</span>
          <p class="prose">
            <em v-if="enabled">Today's plates are running on schedule.</em>
            <em v-else>Today's plates are paused.</em>
          </p>
          <button
            v-if="enabled"
            class="btn"
            type="button"
            @click="onPause"
          >
            Pause for today
          </button>
          <button
            v-else
            class="btn primary"
            type="button"
            @click="onResume"
          >
            Resume today
          </button>
        </section>

        <section class="section">
          <span class="eyebrow">The wires</span>
          <div class="status-line">
            <span>Connection to feeder</span>
            <span :class="['note', panel.connected ? 'ok' : 'warn']">
              <em>{{ panel.connected ? "good" : "not reachable" }}</em>
            </span>
          </div>
          <div class="status-line">
            <span>Home Assistant</span>
            <span :class="['note', panel.haAvailability === 'online' ? 'ok' : 'warn']">
              <em>{{ haCopy }}</em>
            </span>
          </div>
        </section>
      </div>
    </aside>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { usePanelStore } from "@thread-panel/ui-core";
import { useFeeder } from "@/composables/useFeeder";

defineProps<{ open: boolean }>();
defineEmits<{ (e: "close"): void }>();

const panel = usePanelStore();
const feeder = useFeeder();
const enabled = feeder.scheduleEnabled;

const haCopy = computed(() => {
  if (panel.haAvailability === "online") return "online";
  if (panel.haAvailability === "offline") return "offline";
  return "waiting";
});

function onPause(): void {
  feeder.pauseToday();
}

function onResume(): void {
  feeder.resumeToday();
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(8, 6, 3, 0.55);
  backdrop-filter: blur(2px);
  display: flex;
  justify-content: flex-end;
  z-index: 100;
}

.drawer {
  width: min(420px, 80vw);
  height: 100%;
  background: var(--ink-bg-soft);
  border-left: 1px solid var(--hairline-strong);
  padding: 1.5rem 1.5rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  overflow-y: auto;
  transition: var(--theme-transition);
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--hairline);
}

.title {
  margin: 0.18rem 0 0;
  font-family: var(--display);
  font-variation-settings: "opsz" 144, "SOFT" 40, "WONK" 1;
  font-weight: 380;
  font-size: 2rem;
  line-height: 1;
  letter-spacing: -0.015em;
  color: var(--cream);
}

.close {
  background: transparent;
  border: 1px solid var(--hairline-strong);
  border-radius: 999px;
  color: var(--cream-soft);
  width: 2.4rem;
  height: 2.4rem;
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
  transition:
    background 160ms ease,
    border-color 160ms ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.close:hover {
  background: var(--brass-veil);
  border-color: var(--brass-veil-strong);
  color: var(--brass);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.prose {
  margin: 0;
  font-family: var(--display);
  font-size: 1.05rem;
  font-variation-settings: "opsz" 30, "SOFT" 60, "WONK" 1;
  color: var(--cream-soft);
}

.btn {
  width: 100%;
  padding: 1rem;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  border-radius: 4px;
  color: var(--cream);
  font-family: var(--display);
  font-style: italic;
  font-variation-settings: "opsz" 14, "SOFT" 70, "WONK" 1;
  font-size: 1rem;
  cursor: pointer;
  transition:
    background 160ms ease,
    border-color 160ms ease,
    color 160ms ease;
}

.btn:hover {
  background: var(--brass-veil);
  border-color: var(--brass-veil-strong);
  color: var(--brass);
}

.btn.primary {
  background: var(--brass);
  border-color: var(--brass);
  color: var(--ink-bg);
  font-style: normal;
  font-weight: 460;
  box-shadow: 0 6px 18px -10px rgba(212, 162, 88, 0.6);
}

.btn.primary:hover {
  background: #e3b46a;
}

.status-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 0.45rem 0;
  font-family: var(--body);
  font-size: 0.92rem;
  color: var(--cream-soft);
  border-bottom: 1px solid var(--hairline);
}

.status-line:last-of-type {
  border-bottom: 0;
}

.note {
  font-family: var(--display);
  font-variation-settings: "opsz" 14, "SOFT" 80, "WONK" 1;
  font-size: 0.95rem;
  letter-spacing: 0.005em;
}

.note.ok {
  color: var(--sage);
}

.note.warn {
  color: var(--rose);
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 200ms ease;
}

.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform 240ms ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(100%);
}
</style>
