/**
 * Domain types for the feeding_control panel UI. These shape PetLibro's
 * raw HA attributes into something the components can consume directly.
 */

export type FeedState = "Pending" | "Completed" | "Skipped" | string;

export interface Plan {
  /** Stable today's-schedule key from HA: "plan_1", "plan_2", ... */
  key: string;
  /** PetLibro plan ID, used to match the "next feed" sensor */
  planID: number;
  /** "HH:MM" 24h, as PetLibro emits it */
  time: string;
  amount_g: number;
  amount_cups: number;
  amount_oz: number;
  amount_ml: number;
  /** Raw twelfths-of-a-cup count (1..48) */
  amount_raw: number;
  enabled: boolean;
  repeat: boolean;
  repeat_days: string;
  sound: boolean;
  feed_state: FeedState;
}

export interface FeederStatus {
  nextFeedAt: Date | null;
  /** PlanID of the upcoming feed, for highlighting in the schedule list */
  nextPlanId: number | null;
  nextQuantityG: number | null;
  lastFeedAt: Date | null;
  lastQuantityG: number | null;
  todayFeedCount: number;
  todayQuantityG: number;
}

export interface FeederAlarms {
  outOfFood: boolean;
  dispenserJam: boolean;
}

export interface ManualFeedState {
  options: string[];
  current: string;
}
