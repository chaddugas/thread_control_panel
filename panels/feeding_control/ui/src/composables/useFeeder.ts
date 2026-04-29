import { computed } from "vue";
import { usePanelStore } from "@thread-panel/ui-core";
import type {
  FeederAlarms,
  FeederStatus,
  ManualFeedState,
  Plan,
} from "@/types";

/**
 * Hardcoded entity IDs matching panels/feeding_control/ha/manifest.yaml.
 * One feeder, one panel — if we ever multi-feeder, parameterize this.
 */
export const ENTITIES = {
  schedule: "binary_sensor.front_room_smart_feeder_today_s_feeding_schedule",
  nextFeedTime: "sensor.front_room_smart_feeder_next_feed_time",
  nextFeedQty: "sensor.front_room_smart_feeder_next_feed_quantity_weight",
  lastFeedTime: "sensor.front_room_smart_feeder_last_feed_time",
  lastFeedQty: "sensor.front_room_smart_feeder_last_feed_quantity_weight",
  todayCount: "sensor.front_room_smart_feeder_today_s_feeding_times",
  todayQty: "sensor.front_room_smart_feeder_today_s_feeding_quantity_weight",
  alarmFood: "binary_sensor.front_room_smart_feeder_food_status",
  alarmDispenser: "binary_sensor.front_room_smart_feeder_food_dispenser",
  manualFeedQtySelect: "select.front_room_smart_feeder_manual_feed_quantity",
  manualFeedButton: "button.front_room_smart_feeder_manual_feed",
  todayPlanSelect: "select.front_room_smart_feeder_today_s_feeding_schedule",
  skipButton: "button.front_room_smart_feeder_skip_selected_plan_today",
  unskipButton: "button.front_room_smart_feeder_un_skip_selected_plan_today",
  pauseButton:
    "button.front_room_smart_feeder_disable_today_s_feeding_schedule",
  resumeButton:
    "button.front_room_smart_feeder_enable_today_s_feeding_schedule",
} as const;

function num(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function bool(v: unknown): boolean {
  return v === "on" || v === true;
}

function date(v: unknown): Date | null {
  if (typeof v !== "string" || !v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

function stringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === "string");
}

function timeToToday(hhmm: string): Date {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d;
}

export function useFeeder() {
  const panel = usePanelStore();

  const schedule = computed<Plan[]>(() => {
    const e = panel.entity(ENTITIES.schedule);
    if (!e) return [];
    const out: Plan[] = [];
    for (const [key, value] of Object.entries(e.attributes)) {
      if (!key.startsWith("plan_")) continue;
      if (typeof value !== "object" || value === null) continue;
      const v = value as Record<string, unknown>;
      out.push({
        key,
        planID: Number(v.planID) || 0,
        time: String(v.time ?? ""),
        amount_g: Number(v.amount_g) || 0,
        amount_cups: Number(v.amount_cups) || 0,
        amount_oz: Number(v.amount_oz) || 0,
        amount_ml: Number(v.amount_ml) || 0,
        amount_raw: Number(v.amount_raw) || 0,
        enabled: Boolean(v.enabled),
        repeat: Boolean(v.repeat),
        repeat_days: String(v.repeat_days ?? ""),
        sound: Boolean(v.sound),
        feed_state: String(v.feed_state ?? ""),
      });
    }
    out.sort((a, b) => Number(a.key.slice(5)) - Number(b.key.slice(5)));
    return out;
  });

  const scheduleEnabled = computed(
    () => panel.entity(ENTITIES.schedule)?.state === "on",
  );

  const status = computed<FeederStatus>(() => {
    const next = panel.entity(ENTITIES.nextFeedTime);
    const nextQty = panel.entity(ENTITIES.nextFeedQty);
    const last = panel.entity(ENTITIES.lastFeedTime);
    const lastQty = panel.entity(ENTITIES.lastFeedQty);
    const cnt = panel.entity(ENTITIES.todayCount);
    const qty = panel.entity(ENTITIES.todayQty);

    let nextFeedAt = date(next?.state);
    let nextPlanId = next ? num(next.attributes.id) : null;
    let nextQuantityG = nextQty ? num(nextQty.state) : null;

    // PetLibro's next_feed_time sensor goes stale right after a skip while
    // the device round-trips through the cloud — the per-plan feed_state
    // already shows "Skipped", but the sensor still points to the skipped
    // plan. Cross-reference: if the sensor's plan is no longer Pending,
    // fall through to the next Pending plan after it in today's schedule.
    if (nextPlanId !== null) {
      const plans = schedule.value;
      const target = plans.find((p) => p.planID === nextPlanId);
      if (target && target.feed_state !== "Pending") {
        const replacement = plans.find(
          (p) => p.feed_state === "Pending" && p.time > target.time,
        );
        if (replacement) {
          nextPlanId = replacement.planID;
          nextFeedAt = timeToToday(replacement.time);
          nextQuantityG = replacement.amount_g;
        } else {
          nextPlanId = null;
          nextFeedAt = null;
          nextQuantityG = null;
        }
      }
    }

    return {
      nextFeedAt,
      nextPlanId,
      nextQuantityG,
      lastFeedAt: date(last?.state),
      lastQuantityG: lastQty ? num(lastQty.state) : null,
      todayFeedCount: num(cnt?.state) ?? 0,
      todayQuantityG: num(qty?.state) ?? 0,
    };
  });

  const alarms = computed<FeederAlarms>(() => ({
    outOfFood: bool(panel.entity(ENTITIES.alarmFood)?.state),
    dispenserJam: bool(panel.entity(ENTITIES.alarmDispenser)?.state),
  }));

  /**
   * PetLibro emits 48 options at 1/12-cup increments (index 0 → 1 twelfth,
   * index 47 → 48 twelfths / 4 cups). We surface only multiples of 3 — the
   * quarter-cup steps — by keeping every third entry starting at index 2.
   */
  const manualFeedQty = computed<ManualFeedState>(() => {
    const e = panel.entity(ENTITIES.manualFeedQtySelect);
    const all = stringArray(e?.attributes.options);
    const options = all.filter((_, i) => (i + 1) % 3 === 0);
    return {
      options,
      current: e?.state ?? "",
    };
  });

  // ---- actions ----

  function manualFeed(option: string): void {
    panel.callService(
      ENTITIES.manualFeedQtySelect,
      "select.select_option",
      { option },
    );
    panel.callService(ENTITIES.manualFeedButton, "button.press");
  }

  /**
   * The today's-schedule select uses options like "plan_1 - 2747466".
   * We resolve `planKey` → matching option string before firing.
   */
  function selectPlanOption(planKey: string): string | null {
    const sel = panel.entity(ENTITIES.todayPlanSelect);
    const opts = stringArray(sel?.attributes.options);
    return opts.find((o) => o.startsWith(`${planKey} `)) ?? null;
  }

  function skipPlan(planKey: string): void {
    const option = selectPlanOption(planKey);
    if (!option) return;
    panel.callService(ENTITIES.todayPlanSelect, "select.select_option", {
      option,
    });
    panel.callService(ENTITIES.skipButton, "button.press");
  }

  function unskipPlan(planKey: string): void {
    const option = selectPlanOption(planKey);
    if (!option) return;
    panel.callService(ENTITIES.todayPlanSelect, "select.select_option", {
      option,
    });
    panel.callService(ENTITIES.unskipButton, "button.press");
  }

  function pauseToday(): void {
    panel.callService(ENTITIES.pauseButton, "button.press");
  }

  function resumeToday(): void {
    panel.callService(ENTITIES.resumeButton, "button.press");
  }

  return {
    schedule,
    scheduleEnabled,
    status,
    alarms,
    manualFeedQty,
    manualFeed,
    skipPlan,
    unskipPlan,
    pauseToday,
    resumeToday,
  };
}
