<template>
  <section
    class="menu"
    :class="{ 'is-paused': !enabled }"
  >
    <header class="head">
      <span class="eyebrow">The day's plates</span>
      <Transition name="paused">
        <span
          v-if="!enabled"
          class="paused"
          >paused</span
        >
      </Transition>
    </header>
    <ol class="rows">
      <ScheduleRow
        v-for="(plan, i) in plans"
        :key="plan.key"
        :plan="plan"
        :is-next="plan.planID === nextPlanId"
        :open="openKey === plan.key"
        :row-index="i"
        @toggle="onToggle(plan.key)"
        @close="openKey = null"
        @skip="onSkip"
        @unskip="onUnskip"
      />
      <li
        v-if="!plans.length"
        class="placeholder"
      >
        <em>The schedule has not arrived yet.</em>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useFeeder } from '@/composables/useFeeder';
import type { Plan } from '@/types';
import ScheduleRow from './ScheduleRow.vue';

const feeder = useFeeder();
const plans = feeder.schedule;
const enabled = feeder.scheduleEnabled;
const nextPlanId = computed(() => feeder.status.value.nextPlanId);

const openKey = ref<string | null>(null);

const AUTO_CLOSE_MS = 10_000;
let autoCloseTimer: number | null = null;

function clearAutoClose(): void {
  if (autoCloseTimer !== null) {
    window.clearTimeout(autoCloseTimer);
    autoCloseTimer = null;
  }
}

function armAutoClose(): void {
  clearAutoClose();
  if (openKey.value === null) return;
  autoCloseTimer = window.setTimeout(() => {
    openKey.value = null;
    autoCloseTimer = null;
  }, AUTO_CLOSE_MS);
}

watch(openKey, armAutoClose);

function onToggle(key: string): void {
  openKey.value = openKey.value === key ? null : key;
}

function onSkip(plan: Plan): void {
  feeder.skipPlan(plan.key);
  openKey.value = null;
}

function onUnskip(plan: Plan): void {
  feeder.unskipPlan(plan.key);
  openKey.value = null;
}

/**
 * When the next-up plan changes (a meal completes, the upcoming plan
 * advances), wrap the resulting DOM update in a View Transition so the
 * brass lozenge appears to travel from the served row to the new "next"
 * row instead of snapping. Pre-flush watch keeps the old `.row.next`
 * class in place when we snapshot, so OLD has the lozenge at the old
 * position and NEW has it at the new position — the API morphs.
 */
type DocWithVT = Document & {
  startViewTransition?: (cb: () => void | Promise<void>) => {
    finished: Promise<void>;
  };
};

watch(
  () => feeder.status.value.nextPlanId,
  (newId, oldId) => {
    if (newId === oldId) return;
    const start = (document as DocWithVT).startViewTransition;
    if (typeof start !== 'function') return;
    document.documentElement.classList.add('vt-next-marker');
    const t = start.call(document, async () => {
      await nextTick();
    });
    t.finished.finally(() => {
      document.documentElement.classList.remove('vt-next-marker');
    });
  },
  { flush: 'pre' },
);

/**
 * Close the open row whenever a pointerdown lands outside it. We use
 * capture so this fires before per-row toggles — taps inside the
 * currently-open row (its action buttons or dimmed face) are ignored
 * and reset the auto-close timer so a touched row stays alive.
 */
function onDocumentPointerDown(ev: PointerEvent): void {
  if (openKey.value === null) return;
  const target = ev.target as Element | null;
  if (!target) return;
  const openRow = document.querySelector(`[data-row-key="${openKey.value}"]`);
  if (openRow && openRow.contains(target)) {
    armAutoClose();
    return;
  }
  openKey.value = null;
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown, {
    capture: true,
  });
});

onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, {
    capture: true,
  });
  clearAutoClose();
});
</script>

<style scoped>
.menu {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 1rem 0.25rem 0.5rem;
}

.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 0 1rem 0.85rem;
}

.paused {
  font-family: var(--display);
  font-style: italic;
  font-variation-settings:
    'opsz' 14,
    'SOFT' 80,
    'WONK' 1;
  font-size: 0.95rem;
  color: var(--brass);
  letter-spacing: 0.02em;
  display: inline-block;
}

.paused-enter-active,
.paused-leave-active {
  transition:
    opacity 320ms ease,
    transform 380ms cubic-bezier(0.32, 0.05, 0.2, 1);
}

.paused-enter-from,
.paused-leave-to {
  opacity: 0;
  transform: translateX(10px);
}

.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  gap: 0.5rem;
  transition: opacity 380ms ease;
}

.menu.is-paused .rows {
  opacity: 0.55;
}

.placeholder {
  padding: 1.5rem 1rem;
  font-family: var(--display);
  color: var(--cream-faint);
  font-size: 1rem;
}
</style>
