import type { DealCandidate, DealDecision, DealRow, Lane, Store } from "./types";
import { dealKey, discountPercent, normalizeCandidate, nowTs, safeJsonParse } from "./util";

export class D1Repository {
  constructor(private readonly db: D1Database) {}

  async event(event: string, store = "", dealKeyValue = "", payload: unknown = {}): Promise<void> {
    await this.db.prepare(
      "INSERT INTO events(ts,event,store,deal_key,payload_json) VALUES(?,?,?,?,?)"
    ).bind(nowTs(), event, store, dealKeyValue, JSON.stringify(payload || {})).run();
  }

  async upsertCandidate(input: DealCandidate, preliminary: DealDecision): Promise<{new_or_reopened: boolean; deal_key: string}> {
    const deal = normalizeCandidate(input);
    const key = await dealKey(deal);
    const now = nowTs();
    const metadata = { ...(deal.metadata || {}), preliminary_reasons: preliminary.reasons };
    const old = await this.db.prepare("SELECT * FROM deals WHERE deal_key=? LIMIT 1").bind(key).first<DealRow>();

    if (old) {
      const oldPriceNow = Number(old.current_price || 0);
      const oldLane = String(old.lane || "normal");
      const incomingLane: Lane = deal.store === "noon" ? "normal" : preliminary.lane;
      const priceImproved = deal.current_price > 0 && (oldPriceNow <= 0 || deal.current_price <= oldPriceNow * 0.985);
      const laneUpgrade = deal.store === "amazon" && oldLane !== "ultra" && incomingLane === "ultra";
      let storedLane: Lane = incomingLane;
      let storedScore = Number(preliminary.score || 0);
      if (deal.store === "amazon" && oldLane === "ultra" && incomingLane !== "ultra") {
        storedLane = "ultra";
        storedScore = Math.max(Number(old.score || 0), storedScore);
      }
      const staleSent = old.state === "sent" && priceImproved;
      let shouldReopen = laneUpgrade || staleSent;
      let state = shouldReopen ? "pending" : old.state;
      if ((state === "rejected" || state === "retry") && priceImproved) {
        state = "pending";
        shouldReopen = true;
      }
      await this.db.prepare(`
        UPDATE deals SET
          external_id=?, title=?, url=?, image_url=?, category=?, source=?,
          current_price=?, old_price=?, visible_discount=?, lane=?, score=?,
          confidence=?, state=?, updated_at=?, next_attempt_at=?,
          last_error=CASE WHEN ? THEN '' ELSE last_error END,
          metadata_json=?
        WHERE deal_key=?
      `).bind(
        deal.external_id, deal.title, deal.url, deal.image_url || "", deal.category || "unknown", deal.source || "",
        deal.current_price, deal.old_price ?? null, discountPercent(deal), storedLane, storedScore,
        preliminary.confidence, state, now, shouldReopen ? 0 : Number(old.next_attempt_at || 0),
        shouldReopen ? 1 : 0, JSON.stringify(metadata), key,
      ).run();
      return { new_or_reopened: shouldReopen, deal_key: key };
    }

    const lane: Lane = deal.store === "noon" ? "normal" : preliminary.lane;
    await this.db.prepare(`
      INSERT INTO deals(
        deal_key,store,external_id,title,url,image_url,category,source,
        current_price,old_price,visible_discount,lane,score,confidence,
        state,discovered_at,updated_at,metadata_json
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `).bind(
      key, deal.store, deal.external_id, deal.title, deal.url, deal.image_url || "", deal.category || "unknown", deal.source || "",
      deal.current_price, deal.old_price ?? null, discountPercent(deal), lane, preliminary.score, preliminary.confidence,
      "pending", deal.discovered_at || now, now, JSON.stringify(metadata),
    ).run();
    return { new_or_reopened: true, deal_key: key };
  }

  async claimForVerification(store: Store, lane: Lane, workerId: string, leaseSeconds: number): Promise<DealRow | null> {
    const now = nowTs();
    const row = await this.db.prepare(`
      SELECT * FROM deals
      WHERE store=? AND lane=?
        AND state IN ('pending','retry')
        AND next_attempt_at<=?
        AND (lease_until=0 OR lease_until<?)
      ORDER BY
        /*
         * AMAZON ULTRA:
         * Absolute priority = highest discovered discount first.
         * 90 > 89 > 80 > 75 > 70 > 65
         */
        CASE
          WHEN store='amazon' AND lane='ultra'
          THEN visible_discount
          ELSE -1
        END DESC,

        /*
         * Amazon normal lane keeps its intelligent
         * coupon / flash / Goldbox priority.
         */
        CASE
          WHEN store='amazon' AND lane='normal' AND (
            metadata_json LIKE '%"coupon_hint":true%'
            OR metadata_json LIKE '%"coupon_hint": true%'
            OR metadata_json LIKE '%"promo_hint":"coupon"%'
            OR metadata_json LIKE '%"promo_hint": "coupon"%'
            OR metadata_json LIKE '%"flash_hint":true%'
            OR metadata_json LIKE '%"flash_hint": true%'
          ) THEN 0

          WHEN store='amazon' AND lane='normal' AND (
            metadata_json LIKE '%"coupon_probe":true%'
            OR metadata_json LIKE '%"coupon_probe": true%'
          ) THEN 1

          WHEN store='amazon' AND lane='normal'
            AND source='goldbox'
          THEN 2

          WHEN store='amazon' AND lane='normal'
            AND source IN ('limited_time','clearance')
          THEN 3

          ELSE 4
        END ASC,

        score DESC,
        discovered_at ASC
      LIMIT 1
    `).bind(store, lane, now, now).first<DealRow>();
    if (!row) return null;
    const result = await this.db.prepare(`
      UPDATE deals SET state='verifying', lease_owner=?, lease_until=?, updated_at=?
      WHERE deal_key=? AND state IN ('pending','retry') AND (lease_until=0 OR lease_until<?)
    `).bind(workerId, now + leaseSeconds, now, row.deal_key, now).run();
    return Number(result.meta.changes || 0) > 0 ? row : null;
  }

  async markVerified(key: string, dealInput: DealCandidate, decision: DealDecision, metadata: Record<string, unknown>): Promise<void> {
    const deal = normalizeCandidate(dealInput);
    const now = nowTs();
    await this.db.batch([
      this.db.prepare(`
        UPDATE deals SET
          external_id=?, title=?, url=?, image_url=?, category=?, source=?,
          current_price=?, old_price=?, effective_price=?, visible_discount=?,
          real_discount=?, lane=?, score=?, confidence=?, state='verified',
          verified_at=?, updated_at=?, attempts=0, next_attempt_at=0,
          lease_owner=NULL, lease_until=0, last_error='', metadata_json=?
        WHERE deal_key=?
      `).bind(
        deal.external_id, deal.title, deal.url, deal.image_url || "", deal.category || "unknown", deal.source || "",
        deal.current_price, deal.old_price ?? null, decision.effective_price, discountPercent(deal),
        decision.real_discount, deal.store === "noon" ? "normal" : decision.lane,
        decision.score, decision.confidence, now, now, JSON.stringify(metadata), key,
      ),
      this.db.prepare(
        "INSERT INTO price_history(deal_key,store,price,old_price,observed_at) VALUES(?,?,?,?,?)"
      ).bind(key, deal.store, deal.current_price, deal.old_price ?? null, now),
      this.db.prepare(
        "UPDATE source_health SET verified=verified+1 WHERE store=? AND source=?"
      ).bind(deal.store, deal.source || ""),
    ]);
  }

  async markRejected(key: string, reason: string): Promise<void> {
    await this.db.prepare(`
      UPDATE deals SET state='rejected', last_error=?, updated_at=?, lease_owner=NULL, lease_until=0
      WHERE deal_key=?
    `).bind(reason.slice(0, 500), nowTs(), key).run();
  }

  async markRetry(key: string, reason: string, baseSeconds: number, maxAttempts: number): Promise<void> {
    const row = await this.db.prepare("SELECT attempts FROM deals WHERE deal_key=?").bind(key).first<{attempts: number}>();
    const attempts = Number(row?.attempts || 0) + 1;
    if (attempts >= maxAttempts) {
      await this.markRejected(key, `max_attempts:${reason}`);
      return;
    }
    const delay = Math.min(3600, baseSeconds * (2 ** Math.max(0, attempts - 1)));
    const now = nowTs();
    await this.db.prepare(`
      UPDATE deals SET state='retry', attempts=?, next_attempt_at=?, last_error=?, updated_at=?, lease_owner=NULL, lease_until=0
      WHERE deal_key=?
    `).bind(attempts, now + delay, reason.slice(0, 500), now, key).run();
  }

  async claimForDelivery(lane: Lane, workerId: string, leaseSeconds: number): Promise<DealRow | null> {
    const now = nowTs();
    const row = await this.db.prepare(`
      SELECT d.* FROM deals d
      WHERE d.lane=? AND d.state='verified'
        AND (? != 'ultra' OR d.store='amazon')
        AND d.next_attempt_at<=?
        AND (d.lease_until=0 OR d.lease_until<?)
      ORDER BY
        /*
         * Once verified, Ultra uses REAL discount,
         * not the discovery estimate.
         *
         * Example:
         * verified 91% always beats verified 82%,
         * which always beats 70%, then 65%.
         */
        CASE
          WHEN d.store='amazon' AND d.lane='ultra'
          THEN d.real_discount
          ELSE -1
        END DESC,

        /*
         * If two Ultra deals have the same discount,
         * stronger verification wins.
         */
        CASE
          WHEN d.store='amazon' AND d.lane='ultra'
          THEN d.confidence
          ELSE 0
        END DESC,

        CASE
          WHEN d.store='amazon' AND d.lane='ultra'
          THEN d.score
          ELSE 0
        END DESC,

        /*
         * Diversity logic remains useful for the
         * normal lane, but can never push a lower
         * Ultra discount above a higher one.
         */
        (SELECT COUNT(*)
           FROM deals s
          WHERE s.state='sent'
            AND s.lane=d.lane
            AND s.store=d.store
            AND s.sent_at>?) ASC,

        (SELECT COUNT(*)
           FROM deals s
          WHERE s.state='sent'
            AND s.lane=d.lane
            AND s.category=d.category
            AND s.sent_at>?) ASC,

        d.score DESC,
        d.verified_at ASC
      LIMIT 1
    `).bind(lane, lane, now, now, now - 21600, now - 21600).first<DealRow>();
    if (!row) return null;
    const result = await this.db.prepare(`
      UPDATE deals SET state='delivering', lease_owner=?, lease_until=?, updated_at=?
      WHERE deal_key=? AND state='verified'
    `).bind(workerId, now + leaseSeconds, now, row.deal_key).run();
    return Number(result.meta.changes || 0) > 0 ? row : null;
  }

  async markSent(key: string): Promise<void> {
    const now = nowTs();
    const row = await this.db.prepare("SELECT store,source FROM deals WHERE deal_key=?").bind(key).first<{store: string; source: string}>();
    const statements: D1PreparedStatement[] = [
      this.db.prepare(`
        UPDATE deals SET state='sent', sent_at=?, updated_at=?, lease_owner=NULL, lease_until=0, last_error=''
        WHERE deal_key=?
      `).bind(now, now, key),
    ];
    if (row) {
      statements.push(this.db.prepare("UPDATE source_health SET sent=sent+1 WHERE store=? AND source=?").bind(row.store, row.source));
    }
    await this.db.batch(statements);
  }

  async deliveryRetry(key: string, reason: string, baseSeconds: number, maxAttempts: number): Promise<void> {
    const row = await this.db.prepare("SELECT attempts FROM deals WHERE deal_key=?").bind(key).first<{attempts: number}>();
    const attempts = Number(row?.attempts || 0) + 1;
    if (attempts >= maxAttempts) {
      await this.markRejected(key, `delivery_max_attempts:${reason}`);
      return;
    }
    const delay = Math.min(1800, baseSeconds * (2 ** Math.max(0, attempts - 1)));
    const now = nowTs();
    await this.db.prepare(`
      UPDATE deals SET state='verified', attempts=?, next_attempt_at=?, last_error=?, updated_at=?, lease_owner=NULL, lease_until=0
      WHERE deal_key=?
    `).bind(attempts, now + delay, reason.slice(0, 500), now, key).run();
  }

  async releaseStaleLeases(): Promise<number> {
    const now = nowTs();
    const result = await this.db.prepare(`
      UPDATE deals SET state=CASE WHEN state='delivering' THEN 'verified' ELSE 'retry' END,
        lease_owner=NULL, lease_until=0, updated_at=?
      WHERE state IN ('verifying','delivering') AND lease_until>0 AND lease_until<?
    `).bind(now, now).run();
    return Number(result.meta.changes || 0);
  }

  async recentPrices(key: string, limit = 30): Promise<number[]> {
    const rows = await this.db.prepare(`
      SELECT price FROM price_history WHERE deal_key=? AND price>0 ORDER BY observed_at DESC LIMIT ?
    `).bind(key, limit).all<{price: number}>();
    return (rows.results || []).map(r => Number(r.price)).filter(x => x > 0);
  }

  async recentOtherStore(store: Store, sinceSeconds = 7 * 86400, limit = 250): Promise<DealRow[]> {
    const cutoff = nowTs() - sinceSeconds;
    const rows = await this.db.prepare(`
      SELECT * FROM deals WHERE store<>? AND updated_at>=? AND current_price>0
        AND state IN ('verified','sent') AND confidence>=0.62
      ORDER BY updated_at DESC LIMIT ?
    `).bind(store, cutoff, limit).all<DealRow>();
    return rows.results || [];
  }

  async findByPrefix(shortKey: string): Promise<DealRow | null> {
    const key = String(shortKey || "").trim();
    if (!key) return null;
    const rows = await this.db.prepare(
      "SELECT * FROM deals WHERE deal_key LIKE ? ORDER BY updated_at DESC LIMIT 2"
    ).bind(key + "%").all<DealRow>();
    return rows.results?.length === 1 ? rows.results[0] : null;
  }

  async hasEvent(key: string, event: string): Promise<boolean> {
    const row = await this.db.prepare("SELECT 1 AS ok FROM events WHERE deal_key=? AND event=? LIMIT 1").bind(key, event).first<{ok: number}>();
    return Boolean(row);
  }

  async sourceResult(store: Store, source: string, category: string, fetched: number, candidates: number, latencyMs: number, error = ""): Promise<void> {
    const now = nowTs();
    await this.db.prepare(`
      INSERT INTO source_health(
        store,source,category,scans,fetched,candidates,errors,consecutive_errors,
        last_attempt_at,last_success_at,last_latency_ms,last_error
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(store,source) DO UPDATE SET
        category=excluded.category,
        scans=source_health.scans+1,
        fetched=source_health.fetched+excluded.fetched,
        candidates=source_health.candidates+excluded.candidates,
        errors=source_health.errors+excluded.errors,
        consecutive_errors=CASE WHEN excluded.errors>0 THEN source_health.consecutive_errors+1 ELSE 0 END,
        last_attempt_at=excluded.last_attempt_at,
        last_success_at=CASE WHEN excluded.errors=0 THEN excluded.last_attempt_at ELSE source_health.last_success_at END,
        last_latency_ms=excluded.last_latency_ms,
        last_error=excluded.last_error
    `).bind(
      store, source, category, 1, fetched, candidates, error ? 1 : 0, error ? 1 : 0,
      now, error ? 0 : now, latencyMs, error.slice(0, 500),
    ).run();
  }

  async stats(): Promise<Record<string, Record<string, Record<string, number>>>> {
    const rows = await this.db.prepare(
      "SELECT store,lane,state,COUNT(*) AS n FROM deals GROUP BY store,lane,state"
    ).all<{store: string; lane: string; state: string; n: number}>();
    const out: Record<string, Record<string, Record<string, number>>> = {};
    for (const r of rows.results || []) {
      out[r.store] ||= {};
      out[r.store][r.lane] ||= {};
      out[r.store][r.lane][r.state] = Number(r.n);
    }
    return out;
  }

  rowToCandidate(row: DealRow): DealCandidate {
    return normalizeCandidate({
      store: row.store,
      external_id: row.external_id || "",
      title: row.title,
      url: row.url,
      current_price: Number(row.current_price),
      old_price: row.old_price == null ? null : Number(row.old_price),
      image_url: row.image_url || "",
      category: row.category || "unknown",
      source: row.source || "",
      discovered_at: Number(row.discovered_at || nowTs()),
      metadata: safeJsonParse<Record<string, unknown>>(row.metadata_json, {}),
    });
  }

  async counterGet(key: string): Promise<number> {
    const row = await this.db.prepare("SELECT value FROM runtime_counters WHERE key=? LIMIT 1").bind(key).first<{value: number}>();
    return Number(row?.value || 0);
  }

  async counterSet(key: string, value: number): Promise<void> {
    await this.db.prepare(`
      INSERT INTO runtime_counters(key,value,updated_at) VALUES(?,?,?)
      ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    `).bind(key, Math.floor(value), nowTs()).run();
  }

  async counterAdd(key: string, amount: number): Promise<number> {
    const now = nowTs();
    await this.db.prepare(`
      INSERT INTO runtime_counters(key,value,updated_at) VALUES(?,?,?)
      ON CONFLICT(key) DO UPDATE SET value=runtime_counters.value+excluded.value, updated_at=excluded.updated_at
    `).bind(key, Math.max(0, Math.floor(amount)), now).run();
    return this.counterGet(key);
  }
}
