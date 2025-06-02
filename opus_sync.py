"""Synchronise LRT Opus recent playlist → public Spotify playlist.
Runs once; schedule every 15 min with cron/systemd or loop container.
Resilient to minor API changes in the LRT JSON endpoint.
"""
import os
import logging
import sqlite3
import re
import json
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
DNB_PLAYLIST_ID = os.getenv("PLAYLIST_DNB_ID")

VILNIUS_TZ = ZoneInfo("Europe/Vilnius")
CUTOFF_HOURS = 72
DNB_MAX_TRACKS = 100  # Keep 100 tracks in DNB playlist regardless of age
BATCH_SIZE = 100
CACHE_DB = "track_cache.sqlite3"
CACHE_PATH = ".token-cache"  
SCOPE = "playlist-modify-public"

YEAR_RE        = re.compile(r"\(\d{4}\)\s*$")      # strips "(2025)" from the tail
FEAT_RE        = re.compile(r"\((?:feat|ft)\.?\s+.*?\)\s*", re.IGNORECASE)  # strips "(feat. Artist)" from title
ART_TITLE_RE   = re.compile(r"^\s*(.*?)\s*-\s*(.*?)\s*$")  # "Artist - Title"
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
#   Drum‑and‑Bass detection helpers
# ──────────────────────────────────────────────────────────────────────────────

DNB_GENRE_KEYWORDS = {"drum and bass", "drum & bass", "dnb", "uk garage", "jungle"}

def ensure_cache():
    # Get the cache path from environment or use the module-level default
    cache_dir = Path(os.getenv("CACHE_DIR", "/data"))
    cache_db = os.getenv("CACHE_DB")

    # If CACHE_DB is not set in environment, construct it from CACHE_DIR
    if not cache_db:
        cache_db = str(cache_dir / "track_cache.sqlite3")

    conn = sqlite3.connect(cache_db)
    conn.execute("CREATE TABLE IF NOT EXISTS tracks (key TEXT PRIMARY KEY, uri TEXT)")
    # Add table for tracking songs not found in Spotify
    conn.execute("""CREATE TABLE IF NOT EXISTS not_found (
        key TEXT PRIMARY KEY, 
        last_search_date TEXT
    )""")
    # Add table for caching artist genres
    conn.execute("""CREATE TABLE IF NOT EXISTS artist_genres (
        artist_id TEXT PRIMARY KEY, 
        genres TEXT
    )""")
    # Add table for caching track DNB status
    conn.execute("""CREATE TABLE IF NOT EXISTS track_dnb_status (
        uri TEXT PRIMARY KEY,
        is_dnb INTEGER,
        track_data TEXT
    )""")
    conn.commit()
    return conn


def get_cached_artist_genres(conn, artist_id: str) -> List[str] | None:
    """Get cached genres for an artist. Returns None if not cached."""
    row = conn.execute("SELECT genres FROM artist_genres WHERE artist_id=?", (artist_id,)).fetchone()
    if row and row[0]:
        # Parse JSON array back to list
        return json.loads(row[0])
    return None


def cache_artist_genres(conn, artist_id: str, genres: List[str]):
    """Cache the genres for an artist."""
    genres_json = json.dumps(genres)
    conn.execute("INSERT OR REPLACE INTO artist_genres(artist_id, genres) VALUES (?, ?)", 
                (artist_id, genres_json))
    conn.commit()


def get_cached_track_dnb_status(conn, uri: str) -> Tuple[bool, Dict[str, Any]] | None:
    """Get cached DNB status and track data for a track. Returns None if not cached."""
    row = conn.execute("SELECT is_dnb, track_data FROM track_dnb_status WHERE uri=?", (uri,)).fetchone()
    if row:
        is_dnb = bool(row[0])
        track_data = json.loads(row[1]) if row[1] else None
        return (is_dnb, track_data)
    return None


def cache_track_dnb_status(conn, uri: str, is_dnb: bool, track_data: Dict[str, Any]):
    """Cache the DNB status and track data for a track."""
    track_data_json = json.dumps(track_data)
    conn.execute("INSERT OR REPLACE INTO track_dnb_status(uri, is_dnb, track_data) VALUES (?, ?, ?)", 
                (uri, int(is_dnb), track_data_json))
    conn.commit()


def is_dnb_track(sp: spotipy.Spotify, track: Dict[str, Any], conn) -> bool:
    """
    Heuristically decide whether the given track is Drum‑and‑Bass.
    • Accept if any artist on the track has a genre matching DNB_GENRE_KEYWORDS.
    The expensive sp.artist() calls are cached in the database.
    """
    for artist in track["artists"]:
        aid = artist["id"]

        # Check database cache first
        cached_genres = get_cached_artist_genres(conn, aid)
        if cached_genres is not None:
            is_dnb = bool(set(g.lower() for g in cached_genres) & DNB_GENRE_KEYWORDS)
            if is_dnb:
                return True
            continue

        # Not in cache, make API call
        genres = sp.artist(aid)["genres"]

        # Cache the full genres list
        cache_artist_genres(conn, aid, genres)

        # Check if it's DNB
        is_dnb = bool(set(g.lower() for g in genres) & DNB_GENRE_KEYWORDS)
        if is_dnb:
            return True
    return False

def clear_track_dnb_status_cache(conn):
    """
    Clear all cached DNB status information to force re-evaluation with updated genre keywords.
    
    Parameters:
        conn: sqlite3.Connection
            The database connection object
            
    Returns:
        int: Number of cache entries cleared
    """
    cursor = conn.execute("DELETE FROM track_dnb_status")
    conn.commit()
    return cursor.rowcount

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



def cached_lookup(conn, key):
    row = conn.execute("SELECT uri FROM tracks WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def is_recently_not_found(conn, key):
    """Check if this song was searched today and not found."""
    today = datetime.now(tz=VILNIUS_TZ).date().isoformat()
    row = conn.execute("SELECT last_search_date FROM not_found WHERE key=?", (key,)).fetchone()
    return row and row[0] == today


def cache_not_found(conn, key):
    """Mark this song as not found today."""
    today = datetime.now(tz=VILNIUS_TZ).date().isoformat()
    conn.execute("INSERT OR REPLACE INTO not_found(key, last_search_date) VALUES (?, ?)", (key, today))
    conn.commit()


def cache_store(conn, key, uri):
    conn.execute("INSERT OR REPLACE INTO tracks(key, uri) VALUES (?, ?)", (key, uri))
    # Remove from not_found table if it exists (song was found now)
    conn.execute("DELETE FROM not_found WHERE key=?", (key,))
    conn.commit()


def search_track(sp, conn, artist: str, title: str, *, return_cache_flag=False):
    key = f"{artist.lower()} - {title.lower()}"

    # Check positive cache first
    uri = cached_lookup(conn, key)
    if uri:
        return (uri, True) if return_cache_flag else uri

    # Check if we already searched for this today and didn't find it
    if is_recently_not_found(conn, key):
        return (None, True) if return_cache_flag else None

    artist_q = clean_artist(artist)

    # First attempt: search with all artists
    res = sp.search(q=f'track:"{title}" artist:"{artist_q}"', type="track", limit=1)
    items = res.get("tracks", {}).get("items", [])
    
    # If no results and there are multiple artists (contains commas, 'and', '&', 'Vs', or '/')
    if not items and (',' in artist or ' and ' in artist.lower() or ' & ' in artist or ' Vs ' in artist or '/' in artist):
        # Extract first artist (before first comma, 'and', '&', 'Vs', or '/')
        first_artist = artist.split(',')[0].split(' and ')[0].split(' & ')[0].split(' Vs ')[0].split('/')[0].strip()
        first_artist_q = clean_artist(first_artist)
        
        # Try again with just the first artist
        res = sp.search(q=f'track:"{title}" artist:"{first_artist_q}"', type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
    
    if items:
        uri = items[0]["uri"]
        cache_store(conn, key, uri)          # insert into SQLite
        return (uri, False) if return_cache_flag else uri

    # Cache that we didn't find this song today
    cache_not_found(conn, key)
    return (None, False) if return_cache_flag else None

# ──────────────────────────────────────────────────────────────────────────────
# LRT Opus JSON handling (robust to schema drift)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_opus() -> List[Dict[str, Any]]:
    """Download recent RDS payload from LRT Opus and return the raw list of items.
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

    # Current format: "2025.05.26 15:51"
    try:
        return datetime.strptime(dt_raw, "%Y.%m.%d %H:%M").replace(tzinfo=VILNIUS_TZ)
    except ValueError:
        pass

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

        # Split on the *first* hyphen "Artist - Title".
        m = ART_TITLE_RE.match(raw_song)
        if not m:
            # give up if we can't recognise the pattern
            continue
        artist, title = m.groups()

        # Remove trailing "(2024)" and "(feat. Artist)" parts
        title = YEAR_RE.sub("", title).strip()
        title = FEAT_RE.sub("", title).strip()

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
    """Remove the word 'and' and preserve whitespace (case‑insensitive)."""
    if "GandG" in a:
        a = a.replace("GandG", "G&G")
    cleaned = AND_RE.sub("", a)
    return cleaned.strip()


def playlist_snapshot(sp, playlist_id: str) -> List[Tuple[int, datetime, str]]:
    """Get current playlist snapshot with positions, timestamps, and URIs."""
    items, pos = [], 0
    page = sp.playlist_items(playlist_id, additional_types=["track"])
    while page:
        for it in page["items"]:
            added_at = datetime.fromisoformat(
                it["added_at"].replace("Z", "+00:00")
            ).astimezone(VILNIUS_TZ)
            items.append((pos, added_at, it["track"]["uri"]))
            pos += 1
        page = sp.next(page)
    return items


def remove_old(sp, snapshot, playlist_id: str, cutoff_hours: int = CUTOFF_HOURS, max_tracks: int = None):
    """
    Remove tracks from the playlist based on either:
    - Tracks older than cutoff_hours (if max_tracks is None)
    - Oldest tracks beyond max_tracks count (if max_tracks is specified)
    """
    removals = {}
    
    if max_tracks is not None and len(snapshot) > max_tracks:
        # Sort by timestamp (oldest first) and mark tracks beyond max_tracks for removal
        sorted_snapshot = sorted(snapshot, key=lambda x: x[1])
        tracks_to_remove = sorted_snapshot[:-max_tracks]  # Keep the newest max_tracks
        
        for idx, _, uri in tracks_to_remove:
            removals.setdefault(uri, []).append(idx)
    else:
        # Original time-based removal logic
        cutoff = datetime.now(tz=VILNIUS_TZ) - timedelta(hours=cutoff_hours)
        for idx, added_at, uri in snapshot:
            if added_at < cutoff:
                removals.setdefault(uri, []).append(idx)
                
    if not removals:
        return 0
        
    payload = [{"uri": uri, "positions": pos} for uri, pos in removals.items()]
    for chunk in (
        payload[i : i + BATCH_SIZE] for i in range(0, len(payload), BATCH_SIZE)
    ):
        sp.playlist_remove_specific_occurrences_of_items(playlist_id, chunk)
    return sum(len(p) for p in removals.values())


def add_new(sp, uris, playlist_id: str):
    """Add new tracks to the playlist."""
    added = 0
    for chunk in (uris[i : i + BATCH_SIZE] for i in range(0, len(uris), BATCH_SIZE)):
        sp.playlist_add_items(playlist_id, chunk)
        added += len(chunk)
    return added


def log_song(action: str, artist: str, title: str, note: str = "", is_dnb: bool = False) -> None:
    """Uniform per-song debug line."""
    logging.info("%s %-35s – %-35s %-18s %s", action, artist[:35], title[:35], note, "DnB" if is_dnb else "--")

def log_mutation(action: str, n: int, playlist_type: str = "main") -> None:
    """Uniform playlist mutation line."""
    if n:
        what = "added" if action == "ADD" else "removed"
        logging.info("%s %d track%s (%s playlist)", what.capitalize(), n, "" if n == 1 else "s", playlist_type)


# ──────────────────────────────────────────────────────────────────────────────
# Main flow
# ──────────────────────────────────────────────────────────────────────────────

def main():
    sp = get_spotify()
    conn = ensure_cache()

    if os.getenv("CLEAR_DNB_CACHE", "").lower() in ("1", "true", "yes"):
        cleared = clear_track_dnb_status_cache(conn)
        logging.info("Cleared %d DNB status cache entries", cleared)

    records = parse_records(fetch_opus())
    logging.info("Fetched %d recent records", len(records))

    new_uris, new_dnb_uris, misses = [], [], []
    artist_cache = {}  # Cache for DNB detection

    for _, artist, title in records:
        uri, from_cache = search_track(sp, conn, artist, title, return_cache_flag=True)

        if uri:
            where = "CACHE" if from_cache else "SPOTIFY"

            # Check if we have DNB status cached
            cached_dnb_info = get_cached_track_dnb_status(conn, uri)

            if cached_dnb_info:
                # Use cached DNB status and track data
                is_dnb, track = cached_dnb_info
                where += "+DNB_CACHE"
            else:
                # Get track details for DNB detection
                track = sp.track(uri)
                is_dnb = is_dnb_track(sp, track, conn)
                # Cache the DNB status and track data
                cache_track_dnb_status(conn, uri, is_dnb, track)

            log_song(TICK, artist, title, f"found ({where})", is_dnb)
            new_uris.append(uri)
            if is_dnb:
                new_dnb_uris.append(uri)
        else:
            log_song(CROSS, artist, title, "not found")
            misses.append(f"{artist} – {title}")

    # Handle main playlist
    snapshot_before = playlist_snapshot(sp, PLAYLIST_ID)
    removed = remove_old(sp, snapshot_before, PLAYLIST_ID)
    log_mutation("REM", removed, "main")

    snapshot = snapshot_before if removed == 0 else playlist_snapshot(sp, PLAYLIST_ID)
    current_uris = {uri for _, _, uri in snapshot}

    to_add = [u for u in new_uris if u not in current_uris]
    added = add_new(sp, to_add, PLAYLIST_ID)
    log_mutation("ADD", added, "main")

    # Handle DNB playlist if configured
    dnb_added, dnb_removed = 0, 0
    if DNB_PLAYLIST_ID and new_dnb_uris:
        dnb_snapshot_before = playlist_snapshot(sp, DNB_PLAYLIST_ID)
        dnb_removed = remove_old(sp, dnb_snapshot_before, DNB_PLAYLIST_ID, max_tracks=DNB_MAX_TRACKS)
        log_mutation("REM", dnb_removed, "DNB")

        dnb_snapshot = dnb_snapshot_before if dnb_removed == 0 else playlist_snapshot(sp, DNB_PLAYLIST_ID)
        dnb_current_uris = {uri for _, _, uri in dnb_snapshot}

        dnb_to_add = [u for u in new_dnb_uris if u not in dnb_current_uris]
        dnb_added = add_new(sp, dnb_to_add, DNB_PLAYLIST_ID)
        log_mutation("ADD", dnb_added, "DNB")

    summary = (
        f"\n{RIGHT}  **SYNC SUMMARY**  {RIGHT}\n"
        f"  Main playlist:\n"
        f"    Added      : {added}\n"
        f"    Removed    : {removed}\n"
    )

    if DNB_PLAYLIST_ID:
        summary += (
            f"  DNB playlist:\n"
            f"    Added      : {dnb_added}\n"
            f"    Removed    : {dnb_removed}\n"
        )

    summary += f"  Not found  : {len(misses)}\n"

    logging.info(summary.rstrip())
    if misses:
        logging.info("Missing: %s", "; ".join(misses))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error")
        raise