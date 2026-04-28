function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

/**
 * Format twelfths-of-a-cup as a reduced human-readable string.
 *   1  → "1/12"
 *   6  → "1/2"
 *   12 → "1"
 *   18 → "1 1/2"
 *   48 → "4"
 *
 * PetLibro's manual-feed select exposes 48 options at 1/12-cup increments,
 * so option index `i` (0-based) always equals `(i + 1)` twelfths.
 */
export function formatTwelfths(t: number): string {
  if (t <= 0) return "0";
  const whole = Math.floor(t / 12);
  const num = t % 12;
  if (num === 0) return String(whole);
  const g = gcd(num, 12);
  const frac = `${num / g}/${12 / g}`;
  return whole === 0 ? frac : `${whole} ${frac}`;
}
