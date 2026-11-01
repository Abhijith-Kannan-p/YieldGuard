"""Save real responses from the public "data" branch to tests/fixtures (for tests only; the app never reads them).

    cd backend
    python -m devtools.capture_github_mandi

Saves the GitHub contents listing of data/mandi, the newest dated file from raw.githubusercontent.com,
and the real body GitHub returns for a missing file (used as the "index.json not there yet" case).
No API key is involved.
"""
import json
import re
import sys
from pathlib import Path

import httpx

from app import config
from app.timeutil import iso, now_local

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
RAW = f"{config.MANDI_SAVED_RAW_BASE}/{config.MANDI_SAVED_REPO}/{config.MANDI_SAVED_BRANCH}/{config.MANDI_SAVED_DIR}"


def save(name: str, text: str, query: str) -> None:
    (FIXTURES / name).write_text(text, encoding="utf-8")
    manifest_path = FIXTURES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[name] = {"captured_at": iso(now_local()), "source": "GitHub (YieldGuard data branch)", "query": query}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"saved {name}")


def main() -> None:
    api = f"{config.MANDI_SAVED_API_BASE}/repos/{config.MANDI_SAVED_REPO}/contents/{config.MANDI_SAVED_DIR}"
    listing = httpx.get(api, params={"ref": config.MANDI_SAVED_BRANCH}, timeout=30)
    if listing.status_code != 200:
        sys.exit(f"contents API answered HTTP {listing.status_code}")
    names = sorted(x["name"] for x in listing.json() if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", x.get("name", "")))
    if not names:
        sys.exit("the data branch has no dated snapshot")
    save("github_mandi_contents.json", json.dumps(listing.json(), ensure_ascii=False, indent=1) + "\n",
         f"GET contents/{config.MANDI_SAVED_DIR}?ref={config.MANDI_SAVED_BRANCH}")
    newest = httpx.get(f"{RAW}/{names[-1]}", timeout=30)
    if newest.status_code != 200:
        sys.exit(f"raw file answered HTTP {newest.status_code}")
    save(f"github_mandi_{names[-1]}", newest.text, f"raw {config.MANDI_SAVED_DIR}/{names[-1]}")
    missing = httpx.get(f"{RAW}/no-such-file.json", timeout=30)
    save("github_raw_404.txt", missing.text, f"raw {config.MANDI_SAVED_DIR}/no-such-file.json (HTTP {missing.status_code})")


if __name__ == "__main__":
    main()
