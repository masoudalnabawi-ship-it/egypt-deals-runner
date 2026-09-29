import tempfile
import unittest
from pathlib import Path

from deals_v13.config import Settings
from deals_v13.discovery.scheduler import AdaptiveSurfaceSelector, Surface
from deals_v13.infra.db import DealDatabase
from deals_v13.intelligence import IntelligenceEngine, title_similarity
from deals_v13.models import DealCandidate, Lane


def settings(db_path: str) -> Settings:
    return Settings(
        db_path=db_path,
        cloud_api_url="",
        cloud_api_key="",
        telegram_token="x",
        normal_chat_id="1",
        ultra_chat_id="2",
        noon_normal_chat_id="1",
        noon_ultra_chat_id="2",
        ultra_min_discount=50,
        normal_min_discount=10,
        min_confidence_normal=0.62,
        min_confidence_ultra=0.76,
        discovery_interval=20,
        verification_interval=2,
        delivery_interval=2,
        health_interval=60,
        verification_workers_per_store=1,
        max_attempts=5,
        retry_base_seconds=30,
        lease_seconds=180,
        amazon_proxy_first=False,
        noon_proxy_first=True,
        exploration_rate=0.2,
        surface_batch_size=5,
    )


class CoreTests(unittest.TestCase):
    def test_stable_key_same_amazon_asin(self):
        a = DealCandidate("amazon", "B0ABC12345", "A", "https://www.amazon.eg/dp/B0ABC12345?a=1", 100)
        b = DealCandidate("amazon", "B0ABC12345", "Different title", "https://www.amazon.eg/dp/B0ABC12345", 90)
        self.assertEqual(a.key, b.key)

    def test_real_ultra_requires_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            eng = IntelligenceEngine(settings(str(Path(td) / "x.db")))
            d = DealCandidate("amazon", "B0ABC12345", "Phone X100 256GB", "https://www.amazon.eg/dp/B0ABC12345", 4000, 10000)
            weak = eng.evaluate(d, verified=False)
            self.assertEqual(weak.lane, Lane.NORMAL)
            strong = eng.evaluate(d, verified=True, history=[10000, 9800, 9900], verification_signals=2)
            self.assertEqual(strong.lane, Lane.ULTRA)
            self.assertGreaterEqual(strong.confidence, 0.76)

    def test_accessory_anomaly_is_suppressed(self):
        with tempfile.TemporaryDirectory() as td:
            eng = IntelligenceEngine(settings(str(Path(td) / "x.db")))
            d = DealCandidate("amazon", "B0ABC12345", "Replacement remote control for TV", "https://www.amazon.eg/dp/B0ABC12345", 120, 5000)
            decision = eng.evaluate(d, verified=True, anomaly=True, verification_signals=1)
            self.assertFalse(decision.anomaly)

    def test_cross_store_title_similarity(self):
        sim = title_similarity(
            "Samsung Galaxy A55 5G 256GB 8GB",
            "Samsung Galaxy A55 5G Dual SIM 8GB RAM 256GB",
        )
        self.assertGreater(sim, 0.65)

    def test_db_lane_separation_and_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            db = DealDatabase(str(Path(td) / "v13.db"))
            st = settings(db.path)
            eng = IntelligenceEngine(st)

            d = DealCandidate("amazon", "B0ABC12345", "Phone X100", "https://www.amazon.eg/dp/B0ABC12345", 9000, 10000)
            pre = eng.evaluate(d, verified=False)
            db.upsert_candidate(d, pre)
            normal = db.claim_for_verification("amazon", Lane.NORMAL, "n", 60)
            self.assertIsNotNone(normal)

            db.mark_retry(d.key, "test", 1, 5)
            # A major new discount must reopen/promote instead of being suppressed as duplicate.
            d2 = DealCandidate("amazon", "B0ABC12345", "Phone X100", "https://www.amazon.eg/dp/B0ABC12345", 4000, 10000)
            pre2 = eng.evaluate(d2, verified=True, history=[10000, 10000, 10000], verification_signals=2)
            self.assertEqual(pre2.lane, Lane.ULTRA)
            db.upsert_candidate(d2, pre2)
            ultra = db.claim_for_verification("amazon", Lane.ULTRA, "u", 60)
            self.assertIsNotNone(ultra)


    def test_delivery_claim_balances_without_sql_error(self):
        with tempfile.TemporaryDirectory() as td:
            db = DealDatabase(str(Path(td) / "v13.db"))
            st = settings(db.path)
            eng = IntelligenceEngine(st)
            d = DealCandidate("amazon", "B0ABC12345", "Phone X100 256GB", "https://www.amazon.eg/dp/B0ABC12345", 4000, 10000)
            pre = eng.evaluate(d, verified=True, history=[10000, 9800, 9900], verification_signals=2)
            db.upsert_candidate(d, pre)
            db.mark_verified(d.key, d, pre, {"decision_reasons": pre.reasons})
            row = db.claim_for_delivery(pre.lane, "delivery-test", 60)
            self.assertIsNotNone(row)
            self.assertEqual(row["store"], "amazon")

    def test_cross_store_pool_uses_trusted_rows_only(self):
        with tempfile.TemporaryDirectory() as td:
            db = DealDatabase(str(Path(td) / "v13.db"))
            st = settings(db.path)
            eng = IntelligenceEngine(st)
            noisy = DealCandidate("noon", "N12345678", "Phone X100 256GB", "https://www.noon.com/egypt-en/x/N12345678/p/", 3000, 10000)
            pre = eng.evaluate(noisy, verified=False)
            db.upsert_candidate(noisy, pre)
            self.assertEqual(db.recent_other_store("amazon"), [])
            strong = eng.evaluate(noisy, verified=True, history=[10000,9800,9900], verification_signals=2)
            db.mark_verified(noisy.key, noisy, strong, {"decision_reasons": strong.reasons})
            rows = db.recent_other_store("amazon")
            self.assertEqual(len(rows), 1)

    def test_scheduler_forces_diversity(self):
        surfaces = [
            Surface("a1", "electronics", "x"),
            Surface("a2", "electronics", "x"),
            Surface("a3", "electronics", "x"),
            Surface("b1", "fashion", "x"),
            Surface("c1", "grocery", "x"),
        ]
        selector = AdaptiveSurfaceSelector(surfaces, 0.4)
        picked = selector.pick(4, {})
        self.assertGreaterEqual(len({x.category for x in picked}), 2)


if __name__ == "__main__":
    unittest.main()
