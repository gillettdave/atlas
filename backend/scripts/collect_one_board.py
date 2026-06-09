"""Single-board collection worker — called as a subprocess by run_greenhouse_collection.py.

Prints a JSON object to stdout:
  {"records": [...], "reason": "ok", "count": 42}

On error:
  {"records": [], "reason": "error:SomeError:message", "count": 0}

Usage (internal — do not call directly):
    python scripts/collect_one_board.py <ats_type> <board_url> <company_name> <slug>

The parent process captures stdout and parses the JSON. Anything written to stderr
is logged by the parent as a warning.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    if len(sys.argv) < 5:
        print(json.dumps({"records": [], "reason": "error:bad_args", "count": 0}))
        sys.exit(1)

    ats_type = sys.argv[1]
    board_url = sys.argv[2]
    company_name = sys.argv[3]
    # slug is argv[4] — available if needed by future collectors

    try:
        if ats_type == "greenhouse":
            from app.collectors.web3_ats import collect_greenhouse
            records, reason = collect_greenhouse(board_url, company_name, board_url)

        elif ats_type == "lever":
            from app.collectors.web3_ats import collect_lever
            records, reason = collect_lever(board_url, company_name, board_url)

        elif ats_type == "ashby":
            # Ashby uses Playwright — run synchronously via asyncio
            import asyncio
            from playwright.async_api import async_playwright

            async def _run():
                from app.collectors.web3_ats import collect_ashby
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    try:
                        return await collect_ashby(browser, board_url, company_name)
                    finally:
                        await browser.close()

            records, reason = asyncio.run(_run())

        else:
            records, reason = [], f"unsupported_type:{ats_type}"

        # Serialize records — only the fields the parent needs to POST
        serializable = [
            {
                "provider": r.provider,
                "source_url": r.source_url,
                "raw_payload": r.raw_payload,
                "fetch_status": r.fetch_status or "fetched",
            }
            for r in records
        ]

        print(json.dumps({
            "records": serializable,
            "reason": reason or "ok",
            "count": len(serializable),
        }))

    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "records": [],
            "reason": f"error:{type(exc).__name__}:{str(exc)[:200]}",
            "count": 0,
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
