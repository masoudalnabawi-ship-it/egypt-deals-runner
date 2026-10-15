import asyncio
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from deals_v14.discovery.scheduler import Surface
from deals_v14.models import FetchResult
from deals_v14.workers.pipeline import V14Pipeline


class UltraHunterConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_hunter_concurrency_and_failure_recovery(self):
        surfaces = [
            Surface(
                name=f"source_{i}",
                category="test",
                url=f"https://www.amazon.eg/test/{i}",
                priority=1.0,
            )
            for i in range(5)
        ]

        active = 0
        maximum = 0
        completed = []
        recorded = []

        stop_event = asyncio.Event()

        async def fake_fetch(url, store):
            nonlocal active, maximum

            active += 1
            maximum = max(maximum, active)

            try:
                await asyncio.sleep(0.03)

                if url.endswith("/2"):
                    raise RuntimeError("simulated_failure")

                completed.append(url)

                return FetchResult(
                    url=url,
                    text="<html></html>",
                    status_code=200,
                    via="test",
                    latency_ms=30,
                )
            finally:
                active -= 1

        class FakeDB:
            def source_health(self, store):
                return {}

            def source_result(self, *args):
                recorded.append(args)

        class FakePlanner:
            def pick_surfaces(self, *args, **kwargs):
                return SimpleNamespace(surfaces=surfaces)

        class FakeAdapter:
            def __init__(self, available_surfaces):
                self.surfaces = available_surfaces

            def parse_search(self, text, surface):
                return []

        pipeline = object.__new__(V14Pipeline)
        pipeline.db = FakeDB()
        pipeline.http = SimpleNamespace(fetch=fake_fetch)
        pipeline.ultra_hunter = FakePlanner()
        pipeline.discovery = {"amazon": FakeAdapter(surfaces)}
        pipeline.settings = SimpleNamespace(
            ultra_hunter_batch_size=5,
            ultra_hunter_interval=60,
            ultra_hunter_noon_probe_floor=45,
        )
        pipeline.stop_event = stop_event
        pipeline._amazon_ultra_page_cursor = {}

        def fake_page_url(surface):
            return surface.url, 1

        pipeline._amazon_ultra_page_url = fake_page_url

        original_wait_for = asyncio.wait_for

        async def stop_after_first_cycle(awaitable, timeout):
            stop_event.set()
            return await original_wait_for(awaitable, timeout)

        with patch(
            "deals_v14.workers.pipeline.asyncio.wait_for",
            side_effect=stop_after_first_cycle,
        ):
            with self.assertLogs("v14", level=logging.INFO) as logs:
                await pipeline.ultra_hunter_loop("amazon")

        self.assertEqual(maximum, 2)
        self.assertEqual(len(completed), 4)
        self.assertEqual(len(recorded), 5)

        failures = [
            row for row in recorded
            if "simulated_failure" in str(row)
        ]
        self.assertEqual(len(failures), 1)

        self.assertTrue(
            any("errors=1" in line for line in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
