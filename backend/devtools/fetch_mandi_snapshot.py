"""Fetch the Karnataka mandi snapshot from data.gov.in and save it to data/mandi/<newest arrival date>.json.

    cd backend
    python -m devtools.fetch_mandi_snapshot              # writes ../data/mandi/<date>.json
    python -m devtools.fetch_mandi_snapshot --out DIR    # e.g. the "data" branch checkout, so "unchanged" compares with it

Run every 6 hours by .github/workflows/mandi-snapshot.yml, which commits the file to the "data" branch.
Same request as app/sources/mandi.py (MANDI_URL, MANDI_HEADERS, its query parameters, paging on "total").
The file holds the raw records as the API returned them, total, fetched_at (Asia/Kolkata) and the source name.
Nothing is written when the API fails or returns no usable records; the exit code is then non-zero.
On failure only a short cause is printed (timeout, refused, DNS, TLS, HTTP status), never the URL or the key.
"""
import argparse
import json
import logging
import socket
import ssl
import sys
import time
from pathlib import Path

import httpx

from app import config
from app.sources import mandi
from app.timeutil import iso, now_local

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "mandi"
RETRYABLE_STATUS = {500, 502, 503, 504}
RETRY_PAUSE_S = 0.5  # replaced in tests


class SnapshotError(Exception):
    """A short cause that is safe to print (no URL, no key)."""


def cause(exc: BaseException) -> str:
    """timeout / DNS / refused / TLS from the exception chain; never the exception text (it may hold the URL)."""
    chain, e = [], exc
    while e is not None and e not in chain:
        chain.append(e)
        e = e.__cause__ or e.__context__
    if any(isinstance(x, httpx.TimeoutException) for x in chain):
        return "timeout"
    if any(isinstance(x, socket.gaierror) for x in chain):
        return "DNS"
    if any(isinstance(x, ConnectionRefusedError) for x in chain):
        return "refused"
    if any(isinstance(x, ssl.SSLError) for x in chain):
        return "TLS"
    return f"network error ({type(exc).__name__})"


def get_page(client: httpx.Client, offset: int) -> dict:
    """One page; one retry on timeout, connection errors and 5xx, none on 4xx."""
    for attempt in (1, 2):
        try:
            r = client.get(config.MANDI_URL, params=mandi._params(offset))
        except httpx.HTTPError as e:
            if attempt == 1:
                time.sleep(RETRY_PAUSE_S)
                continue
            raise SnapshotError(cause(e)) from None
        if r.status_code in RETRYABLE_STATUS and attempt == 1:
            time.sleep(RETRY_PAUSE_S)
            continue
        if r.status_code != 200:
            raise SnapshotError(f"HTTP {r.status_code}")
        try:
            payload = r.json()
        except ValueError:
            raise SnapshotError("response was not JSON") from None
        if not isinstance(payload, dict) or payload.get("status") == "error" or "records" not in payload:
            raise SnapshotError("unexpected response from data.gov.in")
        return payload
    raise SnapshotError("no response")


def fetch_all(client: httpx.Client) -> tuple[list, int]:
    """All Karnataka records, paged on "total" exactly like mandi._load."""
    records, offset, total = [], 0, 0
    while True:
        payload = get_page(client, offset)
        page = payload.get("records") or []
        try:
            total = int(payload.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        records += page
        offset += len(page)
        if not page or offset >= total or offset >= config.MANDI_MAX_RECORDS:
            return records, total


def build(records: list, total: int, fetched_at) -> tuple[str, dict]:
    """File name from the newest arrival date among usable records (mandi.parse), and the document to save."""
    newest = mandi.parse(records, total)["snapshot_date"]
    if not newest:
        raise SnapshotError("no records")
    return f"{newest}.json", {"source": mandi.NAME, "fetched_at": iso(fetched_at), "total": total, "records": records}


def save(name: str, doc: dict, out_dir: Path) -> str:
    """'written' or 'unchanged'. An identical snapshot keeps the existing file."""
    path = out_dir / name
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("total") == doc["total"] and old.get("records") == doc["records"]:
            # The old file is kept, so its fetched_at means "last time the data changed".
            return "unchanged"
    text = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    if config.DATAGOV_API_KEY and config.DATAGOV_API_KEY in text:
        raise SnapshotError("refusing to save: the response contains the API key")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return "written"


def main(transport: httpx.BaseTransport | None = None, out_dir: Path = OUT_DIR) -> int:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)  # their INFO lines carry the URL, and the URL the key
    if not config.DATAGOV_API_KEY:
        print("failed: DATAGOV_API_KEY is not set", file=sys.stderr)
        return 1
    try:
        with httpx.Client(headers=config.MANDI_HEADERS, timeout=config.MANDI_TIMEOUT_S, transport=transport) as client:
            records, total = fetch_all(client)
        name, doc = build(records, total, now_local())
        status = save(name, doc, out_dir)
    except SnapshotError as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # anything unexpected: the type only, never the text
        print(f"failed: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"{status}: {name} ({len(records)} records, total {total})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save the Karnataka mandi snapshot from data.gov.in.")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="folder for <date>.json (default: data/mandi)")
    sys.exit(main(out_dir=parser.parse_args().out))
