# LRT Opus ▶️ Spotify Playlist Sync

Keep a public Spotify playlist in lockstep with the **last 3 days** of LRT Opus songs.

## Quick run
```bash
# one‑off
python opus_sync.py

# docker
docker volume create opus_cache
docker build -t opus-spotify-sync:latest .
docker run --rm -it --env-file .env -v opus_cache:/data opus-spotify-sync:latest
```