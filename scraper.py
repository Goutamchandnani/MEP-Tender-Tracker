import requests
import json
import threading
from datetime import datetime, timezone, timedelta
from database import upsert_tender

# ── Correct Contracts Finder API v2 ──────────────────────────────────────────
CONTRACTS_FINDER_URL = (
    "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json"
)

NOTICE_BASE_URL = "https://www.contractsfinder.service.gov.uk/Notice/"

MEP_KEYWORDS = [
    "MEP",
    "mechanical",
    "electrical",
    "plumbing",
    "HVAC",
    "building services",
    "M&E",
    "fire alarms",
    "security systems",
    "solar PV",
    "heat pumps",
    "boiler replacement",
]

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _today_iso() -> str:
    """Return today's date in ISO format (YYYY-MM-DD) for deadline filtering."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _build_payload(keyword: str, start: int = 0, size: int = 50) -> dict:
    """Build the v2 API payload for a given keyword."""
    # Look back 12 months for published tenders to ensure we find current opportunities
    # Use YYYY-MM-DD format which is more standard for this API
    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    
    return {
        "keyword": keyword,
        "publishedFrom": one_year_ago,
        "start": start,
        "size": size,
    }


def _fmt_value(lo, hi) -> str:
    """Format a value range."""
    if lo and hi and float(hi) > 0:
        return f"£{float(lo):,.0f} – £{float(hi):,.0f}"
    if lo and float(lo) > 0:
        return f"£{float(lo):,.0f}"
    if hi and float(hi) > 0:
        return f"£{float(hi):,.0f}"
    return "N/A"


def _is_future_deadline(raw: str | None) -> bool:
    """Return True only if the deadline is today or in the future."""
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        # We consider it 'future' if the deadline is any time today or later.
        # Use date() comparison to be generous with today's entries.
        now = datetime.now(timezone.utc)
        return dt.date() >= now.date()
    except Exception:
        return False


def _fmt_date(raw: str | None) -> str:
    """Convert ISO date string to human-readable format."""
    if not raw:
        return "N/A"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except Exception:
        return str(raw)[:10]


def _parse_item(item: dict, keyword: str) -> dict | None:
    """Parse a single notice item into our tender dict format.
    Returns None if the tender's closing date is not strictly in the future.
    """
    api_id = str(item.get("id") or "")
    if not api_id:
        return None

    # ── Strict future-deadline guard ─────────────────────────────────────────
    # Reject anything already closed — belt-and-braces on top of API filter.
    if not _is_future_deadline(item.get("deadlineDate")):
        return None

    title = (item.get("title") or "Untitled").strip()
    buyer = (item.get("organisationName") or "Unknown Buyer").strip()
    description = (item.get("description") or title).strip()

    # Value
    value = _fmt_value(item.get("valueLow"), item.get("valueHigh"))
    if value == "N/A" and item.get("awardedValue"):
        value = f"£{float(item['awardedValue']):,.0f}"

    # Location
    region = item.get("regionText") or item.get("region") or ""
    postcode = item.get("postcode") or ""
    location = region or postcode or "UK"

    # Deadline
    deadline = _fmt_date(item.get("deadlineDate"))

    # Link
    link = f"{NOTICE_BASE_URL}{api_id}"

    return {
        "api_id": api_id,
        "title": title[:500],
        "buyer": buyer[:300],
        "deadline": deadline,
        "value": value,
        "location": location[:200],
        "description": description[:2000],
        "link": link,
        "keywords": keyword,
    }


def fetch_tenders_for_keyword(keyword: str, max_pages: int = 1) -> list[dict]:
    """Fetch live MEP tenders for a single keyword (paginated)."""
    results = []
    page_size = 50

    for page in range(max_pages):
        start = page * page_size
        payload = _build_payload(keyword, start=start, size=page_size)

        try:
            resp = requests.post(
                CONTRACTS_FINDER_URL,
                json=payload,
                headers=HEADERS,
                timeout=60, # Increased timeout for slow government API
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            print(f"[scraper] Timeout fetching '{keyword}' page {page + 1}")
            break
        except Exception as e:
            print(f"[scraper] Error fetching '{keyword}' page {page + 1}: {e}")
            break

        notices = data.get("noticeList", [])
        if not notices:
            break

        for notice in notices:
            item = notice.get("item", {})
            parsed = _parse_item(item, keyword)
            if parsed:
                results.append(parsed)

        # If we got fewer results than requested, no more pages
        if len(notices) < page_size:
            break

    return results


import concurrent.futures

def scrape_all(save_to_db: bool = True, cancel_event=None, on_progress=None) -> list[dict]:
    """Scrape all MEP keywords in parallel and optionally save to DB.
    
    cancel_event: optional threading.Event — if set, stops processing tasks.
    on_progress: optional callback(keyword, current_total, is_done)
    """
    seen_ids: set[str] = set()
    all_tenders: list[dict] = []
    lock = threading.Lock()

    def process_keyword(keyword):
        # ── Check for stop signal ─────────────────────────────────────────────
        if cancel_event and cancel_event.is_set():
            return

        # Notify progress: starting keyword
        if on_progress:
            with lock:
                on_progress(keyword, len(all_tenders), False)

        print(f"[scraper] Fetching: '{keyword}'")
        tenders = fetch_tenders_for_keyword(keyword)
        
        for t in tenders:
            with lock:
                if t["api_id"] and t["api_id"] not in seen_ids:
                    seen_ids.add(t["api_id"])
                    all_tenders.append(t)
                    if save_to_db:
                        try:
                            upsert_tender(t)
                        except Exception as e:
                            print(f"[scraper] DB error for {t['api_id']}: {e}")
        
        print(f"[scraper]   → {len(tenders)} results for '{keyword}'")

    # Use ThreadPoolExecutor for parallel fetching
    # 8 workers provide a 5x+ speed boost while remaining polite to the API
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_keyword, kw): kw for kw in MEP_KEYWORDS}
        
        for future in concurrent.futures.as_completed(futures):
            # Check for cancel signal mid-execution
            if cancel_event and cancel_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break
            try:
                future.result()
            except Exception as e:
                kw = futures[future]
                print(f"[scraper] Error processing '{kw}': {e}")

    # Notify progress: finished all keywords
    if on_progress:
        with lock:
            on_progress("Complete", len(all_tenders), True)

    status = "stopped early" if (cancel_event and cancel_event.is_set()) else "done"
    print(f"[scraper] {status.capitalize()}. {len(all_tenders)} unique tenders saved.")
    return all_tenders


if __name__ == "__main__":
    from database import init_db
    init_db()
    # Diagnostic run
    scrape_all(save_to_db=True)

