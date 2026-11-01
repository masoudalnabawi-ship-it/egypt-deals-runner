export async function ensureWatchTable(db: D1Database): Promise<void> {
  await db.prepare(`
    CREATE TABLE IF NOT EXISTS v14_product_watchlist (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id TEXT NOT NULL,
      bot_route TEXT NOT NULL CHECK(bot_route IN ('main','noon')),
      store TEXT NOT NULL CHECK(store IN ('amazon','noon')),
      product_url TEXT NOT NULL,
      external_id TEXT NOT NULL,
      title TEXT NOT NULL DEFAULT '',
      target_price REAL,
      target_discount REAL,
      last_price REAL,
      last_discount REAL,
      last_checked_at INTEGER,
      last_alert_price REAL,
      last_alert_at INTEGER,
      active INTEGER NOT NULL DEFAULT 1,
      created_at INTEGER NOT NULL DEFAULT (unixepoch()),
      CHECK(target_price IS NOT NULL OR target_discount IS NOT NULL),
      UNIQUE(chat_id, bot_route, store, external_id)
    )
  `).run();
}

export interface WatchSubscription {
  chatId: string;
  botRoute: "main" | "noon";
  store: "amazon" | "noon";
  productUrl: string;
  externalId: string;
  targetPrice: number | null;
  targetDiscount: number | null;
}

export async function saveWatch(
  db: D1Database,
  watch: WatchSubscription
): Promise<void> {
  const price = watch.targetPrice;
  const discount = watch.targetDiscount;

  if (
    (price === null && discount === null) ||
    (price !== null && (!Number.isFinite(price) || price <= 0)) ||
    (discount !== null && (!Number.isFinite(discount) || discount <= 0 || discount > 100))
  ) {
    throw new Error("invalid_watch_target");
  }

  await ensureWatchTable(db);

  await db.prepare(`
    INSERT INTO v14_product_watchlist
      (chat_id, bot_route, store, product_url, external_id,
       target_price, target_discount)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(chat_id, bot_route, store, external_id)
    DO UPDATE SET
      product_url = excluded.product_url,
      target_price = excluded.target_price,
      target_discount = excluded.target_discount,
      active = 1,
      last_alert_price = NULL,
      last_alert_at = NULL
  `).bind(
    watch.chatId,
    watch.botRoute,
    watch.store,
    watch.productUrl,
    watch.externalId,
    price,
    discount
  ).run();
}

export interface WatchListItem {
  id: number;
  store: "amazon" | "noon";
  external_id: string;
  product_url: string;
  target_price: number | null;
  target_discount: number | null;
  last_price: number | null;
  active: number;
}

export async function listWatches(
  db: D1Database,
  chatId: string,
  route: "main" | "noon"
): Promise<WatchListItem[]> {
  await ensureWatchTable(db);

  const result = await db.prepare(`
    SELECT id, store, external_id, product_url,
           target_price, target_discount, last_price, active
    FROM v14_product_watchlist
    WHERE chat_id = ? AND bot_route = ? AND active = 1
    ORDER BY id DESC
    LIMIT 50
  `).bind(chatId, route).all<WatchListItem>();

  return result.results || [];
}

export async function removeWatch(
  db: D1Database,
  chatId: string,
  route: "main" | "noon",
  id: number
): Promise<boolean> {
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new Error("invalid_watch_id");
  }

  await ensureWatchTable(db);

  const result = await db.prepare(`
    UPDATE v14_product_watchlist
    SET active = 0
    WHERE id = ? AND chat_id = ? AND bot_route = ? AND active = 1
  `).bind(id, chatId, route).run();

  return Number(result.meta.changes || 0) > 0;
}
