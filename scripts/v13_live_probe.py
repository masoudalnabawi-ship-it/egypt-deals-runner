from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

from deals_v13.config import Settings
from deals_v13.discovery.amazon import AmazonDiscovery
from deals_v13.discovery.noon import NoonDiscovery
from deals_v13.infra.http import StoreHttpClient
from deals_v13.verification.verifier import StoreVerifier, VerificationRejected


async def probe_store(store: str, adapter, http: StoreHttpClient, verifier: StoreVerifier, surface_limit: int, verify_limit: int):
    report = {"store": store, "surfaces": [], "verified": [], "errors": []}
    candidates = []
    for surface in list(adapter.surfaces)[:surface_limit]:
        started = time.monotonic()
        try:
            result = await http.fetch(surface.url, store)
            deals = adapter.parse_search(result.text, surface) if store == 'amazon' else adapter.parse_page(result.text, surface)
            deals.sort(key=lambda d: d.discount_percent, reverse=True)
            candidates.extend(deals[: max(verify_limit * 2, 6)])
            report["surfaces"].append({
                "name": surface.name,
                "category": surface.category,
                "via": result.via,
                "http": result.status_code,
                "latency_ms": result.latency_ms,
                "parsed": len(deals),
                "top_discount": deals[0].discount_percent if deals else 0,
            })
        except Exception as exc:
            report["errors"].append({"surface": surface.name, "error": f"{type(exc).__name__}:{exc}"})
        await asyncio.sleep(0.15)

    seen = set()
    unique = []
    for d in sorted(candidates, key=lambda x: x.discount_percent, reverse=True):
        if d.key in seen:
            continue
        seen.add(d.key)
        unique.append(d)

    for d in unique[:verify_limit]:
        try:
            verified, meta = await verifier.verify(d)
            report["verified"].append({
                "id": verified.external_id or verified.key[:12],
                "title": verified.title[:120],
                "price": verified.current_price,
                "old_price": verified.old_price,
                "discount": verified.discount_percent,
                "via": meta.get("http_via"),
                "signals": meta.get("verification_signals"),
                "coupon": meta.get("coupon_percent"),
                "flash": bool(meta.get("flash")),
            })
        except VerificationRejected as exc:
            report["errors"].append({"id": d.external_id or d.key[:12], "error": f"rejected:{exc}"})
        except Exception as exc:
            report["errors"].append({"id": d.external_id or d.key[:12], "error": f"{type(exc).__name__}:{exc}"})
    return report


async def main():
    ap = argparse.ArgumentParser(description='V13 no-send live discovery/verification probe')
    ap.add_argument('--surfaces', type=int, default=3)
    ap.add_argument('--verify', type=int, default=3)
    ap.add_argument('--out', default='v13-live-probe.json')
    args = ap.parse_args()

    st = Settings.from_env()
    http = StoreHttpClient(st)
    verifier = StoreVerifier(http)
    try:
        amazon, noon = await asyncio.gather(
            probe_store('amazon', AmazonDiscovery(), http, verifier, max(1,args.surfaces), max(1,args.verify)),
            probe_store('noon', NoonDiscovery(), http, verifier, max(1,args.surfaces), max(1,args.verify)),
        )
        report = {"generated_at": int(time.time()), "amazon": amazon, "noon": noon}
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await http.aclose()


if __name__ == '__main__':
    asyncio.run(main())
