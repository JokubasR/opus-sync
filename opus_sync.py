"""Synchronise LRT Opus recent playlist → public Spotify playlist.
Runs once; schedule every 15 min with cron/systemd or loop container.
Resilient to minor API changes in the LRT JSON endpoint.
"""
import os
import logging
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Tuple, Dict, Any

import requests
import sentry_sdk
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# Configuration & setup
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

PLAYLIST_ID = os.environ["PLAYLIST_ID"]
VILNIUS_TZ = ZoneInfo("Europe/Vilnius")
CUTOFF_HOURS = 72
BATCH_SIZE = 100
CACHE_DB = "track_cache.sqlite3"
CACHE_PATH = ".token-cache"  
SCOPE = "playlist-modify-public"

YEAR_RE        = re.compile(r"\(\d{4}\)\s*$")      # strips “(2025)” from the tail
ART_TITLE_RE   = re.compile(r"^\s*(.*?)\s*-\s*(.*?)\s*$")  # “Artist - Title”
AND_RE         = re.compile(r"\band\b", re.I) # remove literal "and"
MULTI_SPACE_RE = re.compile(r"\s{2,}")

TICK  = "\u2705"   # ✅
CROSS = "\u274C"   # ❌
RIGHT = "\u27A4"   # ➡

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/data"))
CACHE_DB   = str(CACHE_DIR / CACHE_DB)
CACHE_PATH = str(CACHE_DIR / CACHE_PATH)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_spotify() -> spotipy.Spotify:
    """
    Return an authenticated Spotipy client.

    · If SPOTIPY_REFRESH_TOKEN is set      → refresh silently, no browser.
    · Else                                 → run the usual OAuth code-flow once
                                             (prints login URL, waits for ?code=…).
    """
    # 1.  Create a SpotifyOAuth helper (needed in both branches)
    oauth = SpotifyOAuth(
        client_id     = os.environ["SPOTIPY_CLIENT_ID"],
        client_secret = os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri  = os.environ["SPOTIPY_REDIRECT_URI"],
        scope         = SCOPE,
        cache_path    = CACHE_PATH,
        open_browser  = False,
        show_dialog   = False,
    )

    refresh_token = os.getenv("SPOTIPY_REFRESH_TOKEN")

    if refresh_token:
        # -- Headless path -----------------------------------------------------
        token_info = oauth.refresh_access_token(refresh_token)
        access_token = token_info["access_token"]
        return spotipy.Spotify(auth=access_token, requests_timeout=10)

    # -------------------------------------------------------------------------
    # No refresh-token yet → run interactive code flow once.
    # -------------------------------------------------------------------------
    auth_url = oauth.get_authorize_url()
    print("\n❖ Visit the following URL, authorise the app, then paste the full "
          "redirected URL here:\n\n", auth_url, "\n")
    redirected = input("↳ Redirected URL: ").strip()

    try:
        code = oauth.parse_response_code(redirected)
        if not code:
            raise ValueError("No `code` found in the URL you pasted.")
        token_info = oauth.get_access_token(code, check_cache=False)
    except Exception as exc:
        print(f"Auth failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Show the user the refresh_token so they can put it in `.env`
    print("\n✓ Success!  Copy this line into your .env file:\n")
    print(f"SPOTIPY_REFRESH_TOKEN={token_info['refresh_token']}\n")

    access_token = token_info["access_token"]
    return spotipy.Spotify(auth=access_token, requests_timeout=10)

def ensure_cache():
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS tracks (key TEXT PRIMARY KEY, uri TEXT)")
    conn.commit()
    return conn


def cached_lookup(conn, key):
    row = conn.execute("SELECT uri FROM tracks WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def cache_store(conn, key, uri):
    conn.execute("INSERT OR REPLACE INTO tracks(key, uri) VALUES (?, ?)", (key, uri))
    conn.commit()

# ──────────────────────────────────────────────────────────────────────────────
# LRT Opus JSON handling (robust to schema drift)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_opus() -> List[Dict[str, Any]]:
    """Download recent RDS payload from LRT Opus and return the raw list of items.
    The endpoint occasionally changes field names; we try a few fall‑backs.
    """
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    url   = f"https://www.lrt.lt/api/json/rds?station=opus&v={ts_ms}"
    logging.info("Fetching LRT data: %s", url)
    resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        logging.error("LRT endpoint returned non‑JSON payload: %s", resp.text[:200])
        return []

    # Common top‑level keys we have seen over the years
    for key in ("rdsList", "rds", "data", "items"):
        if key in data and isinstance(data[key], list):
            return data[key]

    # Some deployments just return the list itself
    if isinstance(data, list):
        return data

    logging.error("Unable to locate song list in JSON: keys=%s", list(data.keys())[:10])
    return []


def _parse_dt(dt_raw: Any) -> datetime | None:
    """Return timezone-aware datetime (Europe/Vilnius) or None on failure."""
    if isinstance(dt_raw, (int, float)):
        return datetime.fromtimestamp(dt_raw / 1000, tz=VILNIUS_TZ)

    if not isinstance(dt_raw, str):
        return None

    dt_raw = dt_raw.strip()

    # 1) Current format: "2025.05.26 15:51"
    try:
        return datetime.strptime(dt_raw, "%Y.%m.%d %H:%M").replace(tzinfo=VILNIUS_TZ)
    except ValueError:
        pass

    # 2) ISO-8601 or variant (fallback)
    try:
        return datetime.fromisoformat(dt_raw.replace("Z", "+00:00")).astimezone(VILNIUS_TZ)
    except ValueError:
        return None


def parse_records(records: List[Dict[str, Any]]) -> List[Tuple[datetime, str, str]]:
    """Return (timestamp, artist, title) tuples — last 72 h, de-duplicated."""
    cutoff  = datetime.now(tz=VILNIUS_TZ) - timedelta(hours=CUTOFF_HOURS)
    latest: list[tuple[datetime, str, str]] = []

    for item in records:
        ts = _parse_dt(item.get("dt") or item.get("time") or item.get("timestamp"))
        if not ts or ts < cutoff:
            continue

        raw_song = (item.get("song") or item.get("name") or "").strip()
        if not raw_song:
            continue

        # Split on the *first* hyphen “Artist - Title”.
        m = ART_TITLE_RE.match(raw_song)
        if not m:
            # give up if we can’t recognise the pattern
            continue
        artist, title = m.groups()

        # Remove trailing “(2024)”
        title = YEAR_RE.sub("", title).strip()

        latest.append((ts, artist, title))

    # de-dupe in time order (keep earliest instance per song)
    seen, unique = set(), []
    for ts, art, tit in sorted(latest, key=lambda x: x[0]):
        key = f"{art.lower()} - {tit.lower()}"
        if key not in seen:
            unique.append((ts, art, tit))
            seen.add(key)

    return unique

# ──────────────────────────────────────────────────────────────────────────────
# Spotify helpers
# ──────────────────────────────────────────────────────────────────────────────


def clean_artist(a: str) -> str:
    """Remove the word 'and' and collapse whitespace (case‑insensitive)."""
    cleaned = AND_RE.sub("", a)
    return MULTI_SPACE_RE.sub(" ", cleaned).strip()


def search_track(sp, conn, artist: str, title: str, *, return_cache_flag=False):

    key = f"{artist.lower()} - {title.lower()}"

    uri = cached_lookup(conn, key)
    if uri:
        return (uri, True) if return_cache_flag else uri

    artist_q = clean_artist(artist)

    res = sp.search(q=f'track:"{title}" artist:"{artist_q}"', type="track", limit=1)
    items = res.get("tracks", {}).get("items", [])
    if items:
        uri = items[0]["uri"]
        cache_store(conn, key, uri)          # insert into SQLite
        return (uri, False) if return_cache_flag else uri

    return (None, False) if return_cache_flag else None


def playlist_snapshot(sp) -> List[Tuple[int, datetime, str]]:
    items, pos = [], 0
    page = sp.playlist_items(PLAYLIST_ID, additional_types=["track"])
    while page:
        for it in page["items"]:
            added_at = datetime.fromisoformat(
                it["added_at"].replace("Z", "+00:00")
            ).astimezone(VILNIUS_TZ)
            items.append((pos, added_at, it["track"]["uri"]))
            pos += 1
        page = sp.next(page)
    return items


def remove_old(sp, snapshot):
    cutoff = datetime.now(tz=VILNIUS_TZ) - timedelta(hours=CUTOFF_HOURS)
    removals = {}
    for idx, added_at, uri in snapshot:
        if added_at < cutoff:
            removals.setdefault(uri, []).append(idx)
    if not removals:
        return 0
    payload = [{"uri": uri, "positions": pos} for uri, pos in removals.items()]
    for chunk in (
        payload[i : i + BATCH_SIZE] for i in range(0, len(payload), BATCH_SIZE)
    ):
        sp.playlist_remove_specific_occurrences_of_items(PLAYLIST_ID, chunk)
    return sum(len(p) for p in removals.values())


def add_new(sp, uris):
    added = 0
    for chunk in (uris[i : i + BATCH_SIZE] for i in range(0, len(uris), BATCH_SIZE)):
        sp.playlist_add_items(PLAYLIST_ID, chunk)
        added += len(chunk)
    return added


def log_song(action: str, artist: str, title: str, note: str = "") -> None:
    """Uniform per-song debug line."""
    logging.info("%s %-35s – %-35s %s", action, artist[:35], title[:35], note)

def log_mutation(action: str, n: int) -> None:
    """Uniform playlist mutation line."""
    if n:
        what = "added" if action == "ADD" else "removed"
        logging.info("%s %d track%s", what.capitalize(), n, "" if n == 1 else "s")


# ──────────────────────────────────────────────────────────────────────────────
# Main flow
# ──────────────────────────────────────────────────────────────────────────────

def main():
    sp = get_spotify()
    conn = ensure_cache()

    records = parse_records(fetch_opus())
    logging.info("Fetched %d recent records", len(records))

    new_uris, misses = [], []

    for _, artist, title in records:
        uri, from_cache = search_track(sp, conn, artist, title, return_cache_flag=True)

        if uri:
            where = "CACHE" if from_cache else "SPOTIFY"
            log_song(TICK, artist, title, f"found ({where})")
            new_uris.append(uri)
        else:
            log_song(CROSS, artist, title, "not found")
            misses.append(f"{artist} – {title}")

    snapshot_before = playlist_snapshot(sp)
    removed = remove_old(sp, snapshot_before)
    log_mutation("REM", removed)

    snapshot = snapshot_before if removed == 0 else playlist_snapshot(sp)
    current_uris = {uri for _, _, uri in snapshot}

    to_add = [u for u in new_uris if u not in current_uris]
    added = add_new(sp, to_add)
    log_mutation("ADD", added)

    summary = (
        f"\n{RIGHT}  **SYNC SUMMARY**  {RIGHT}\n"
        f"  Added      : {added}\n"
        f"  Removed    : {removed}\n"
        f"  Not found  : {len(misses)}\n"
    )
    logging.info(summary.rstrip())
    if misses:
        logging.info("Missing: %s", "; ".join(misses))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error")
        raise