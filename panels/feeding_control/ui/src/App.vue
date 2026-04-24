<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { usePanelStore } from '@thread-panel/ui-core';

const panel = usePanelStore();

// Refresh "X seconds ago" labels by ticking a reactive `now` every second.
const now = ref(Date.now());
let nowTimer: number | null = null;

onMounted(() => {
  panel.connect();
  nowTimer = window.setInterval(() => {
    now.value = Date.now();
  }, 1000);
});

onUnmounted(() => {
  panel.disconnect();
  if (nowTimer !== null) {
    window.clearInterval(nowTimer);
    nowTimer = null;
  }
});

const proximityAge = computed(() =>
  panel.proximity
    ? Math.max(0, Math.round((now.value - panel.proximity.receivedAt) / 1000))
    : null,
);

const ambientAge = computed(() =>
  panel.ambient
    ? Math.max(0, Math.round((now.value - panel.ambient.receivedAt) / 1000))
    : null,
);

const toggleLight = (): void => {
  panel.callService('light.chad_s_office_desk_lamp', 'light.toggle', {});
};
</script>

<template>
  <main>
    <header>
      <h1>Pet Feeder Panel</h1>
      <p class="subtitle">scaffold smoke test</p>
    </header>

    <button
      @click="toggleLight"
      :disabled="!panel.connected"
    >
      Toggle Light
    </button>

    <section class="card status">
      <h2>Connection</h2>
      <p :class="['pill', panel.connected ? 'pill-ok' : 'pill-warn']">
        {{ panel.connected ? 'connected' : 'disconnected' }}
      </p>
      <p class="meta">{{ panel.wsUrl }}</p>
      <p
        v-if="panel.lastError"
        class="error"
      >
        {{ panel.lastError }}
      </p>
    </section>

    <section class="card">
      <h2>Proximity</h2>
      <template v-if="panel.proximity">
        <p class="value">
          {{ panel.proximity.value }}<span class="unit">cm</span>
        </p>
        <p class="meta">
          strength {{ panel.proximity.strength }} · {{ proximityAge }}s ago
        </p>
      </template>
      <p
        v-else
        class="placeholder"
      >
        awaiting first reading…
      </p>
    </section>

    <section class="card">
      <h2>Ambient brightness</h2>
      <template v-if="panel.ambient">
        <p class="value">
          {{ panel.ambient.value }}<span class="unit">%</span>
        </p>
        <p class="meta">
          raw {{ panel.ambient.raw }} · {{ panel.ambient.mv }} mV ·
          {{ ambientAge }}s ago
        </p>
      </template>
      <p
        v-else
        class="placeholder"
      >
        awaiting first reading…
      </p>
    </section>
  </main>
</template>

<style scoped>
main {
  max-width: 720px;
  margin: 0 auto;
  padding: 2rem 1rem 4rem;
}

header {
  margin-bottom: 1.5rem;
}

h1 {
  font-size: 1.6rem;
  font-weight: 600;
  margin: 0;
}

.subtitle {
  margin: 0.25rem 0 0;
  color: #6b7280;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.card {
  background: #1a1a22;
  border: 1px solid #262633;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}

h2 {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #9ca3af;
}

.value {
  font-size: 2.25rem;
  font-weight: 300;
  margin: 0;
  line-height: 1;
}

.unit {
  font-size: 1rem;
  color: #6b7280;
  margin-left: 0.35rem;
  font-weight: 400;
}

.meta {
  margin: 0.5rem 0 0;
  font-size: 0.8rem;
  color: #6b7280;
}

.placeholder {
  color: #4b5563;
  font-style: italic;
  margin: 0;
}

.pill {
  display: inline-block;
  padding: 0.2rem 0.65rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: lowercase;
  letter-spacing: 0.04em;
}

.pill-ok {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
}

.pill-warn {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

.error {
  margin: 0.5rem 0 0;
  color: #f87171;
  font-size: 0.85rem;
}

button {
  padding: 0.6rem 1.1rem;
  background: #3b82f6;
  color: white;
  border: 0;
  border-radius: 6px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.12s;
}

button:hover:not(:disabled) {
  background: #2563eb;
}

button:disabled {
  background: #374151;
  cursor: not-allowed;
  color: #6b7280;
}
</style>
