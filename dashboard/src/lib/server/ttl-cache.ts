/** Small TTL + LRU cache (bounded so it can't grow without limit). */
export class TtlCache<T> {
  private store = new Map<string, { value: T; expires: number }>();

  constructor(private ttlMs: number, private maxEntries: number) {}

  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;
    if (entry.expires < Date.now()) {
      this.store.delete(key);
      return undefined;
    }
    this.store.delete(key);
    this.store.set(key, entry); // refresh LRU position
    return entry.value;
  }

  set(key: string, value: T, ttlMs = this.ttlMs): void {
    this.store.delete(key);
    this.store.set(key, { value, expires: Date.now() + ttlMs });
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (oldest === undefined) break;
      this.store.delete(oldest);
    }
  }

  delete(key: string): void {
    this.store.delete(key);
  }
}
