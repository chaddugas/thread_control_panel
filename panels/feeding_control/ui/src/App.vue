<template>
  <div class="app">
    <div class="app-shell">
      <header class="header">
        <Masthead />
        <div class="tools">
          <ManualFeed />
          <button
            class="settings"
            type="button"
            aria-label="Open settings"
            @click="settingsOpen = true"
          >
            <span class="dot" />
            <span class="dot" />
            <span class="dot" />
          </button>
        </div>
      </header>
      <AlarmBanner />
      <main>
        <section class="col schedule">
          <ScheduleList />
        </section>
        <section class="col day">
          <StatusPanel />
        </section>
      </main>
    </div>
    <SettingsDrawer
      :open="settingsOpen"
      @close="settingsOpen = false"
    />
    <Splash :visible="showSplash" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { usePanelStore } from "@thread-panel/ui-core";
import { useTheme } from "@/composables/useTheme";
import { usePresence } from "@/composables/usePresence";
import AlarmBanner from "@/components/AlarmBanner.vue";
import Masthead from "@/components/Masthead.vue";
import ScheduleList from "@/components/ScheduleList.vue";
import StatusPanel from "@/components/StatusPanel.vue";
import ManualFeed from "@/components/ManualFeed.vue";
import SettingsDrawer from "@/components/SettingsDrawer.vue";
import Splash from "@/components/Splash.vue";

const panel = usePanelStore();
const settingsOpen = ref(false);

useTheme();
const { showSplash } = usePresence();

onMounted(() => panel.connect());
onUnmounted(() => panel.disconnect());
</script>

<style scoped>
.app {
  height: 100vh;
  overflow: hidden;
}

.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: clamp(1.2rem, 3vw, 2.4rem);
  padding: clamp(1rem, 2vw, 1.6rem) var(--pad) clamp(0.85rem, 1.6vw, 1.15rem);
  position: relative;
}

.header::after {
  content: "";
  position: absolute;
  left: var(--pad);
  right: var(--pad);
  bottom: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    var(--hairline-strong) 8%,
    var(--hairline-strong) 92%,
    transparent
  );
}

.tools {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.settings {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.85rem 0.95rem;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  border-radius: 999px;
  cursor: pointer;
  transition:
    background 160ms ease,
    border-color 160ms ease;
}

.settings:hover {
  background: var(--brass-veil);
  border-color: var(--brass-veil-strong);
}

.dot {
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: var(--cream-soft);
}

main {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  gap: clamp(1.4rem, 3vw, 2.6rem);
  padding: 0 var(--pad) var(--pad);
  min-height: 0;
}

.col {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.col.schedule {
  overflow: hidden;
}
</style>
