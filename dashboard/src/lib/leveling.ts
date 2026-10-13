/** Same XP curve as the bot (services/leveling.py, MEE6-compatible). */
export const xpToNext = (level: number) => 5 * level * level + 50 * level + 100;

export function levelFromXp(xp: number): { level: number; current: number; needed: number } {
  let level = 0;
  let floor = 0;
  while (level < 500 && xp >= floor + xpToNext(level)) {
    floor += xpToNext(level);
    level += 1;
  }
  return { level, current: xp - floor, needed: xpToNext(level) };
}
