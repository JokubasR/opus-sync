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

## Testing

The project includes a comprehensive test suite that covers all major components:

- Record parsing
- Database operations
- Spotify API interactions
- LRT Opus API interaction
- DNB detection logic
- Playlist management
- Main program flow

### Running the tests

#### Locally

1. Install the test dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

2. Run all tests:
   ```bash
   python run_tests.py
   ```

   Or using pytest directly:
   ```bash
   pytest -v tests/
   ```

3. Run specific test files:
   ```bash
   pytest -v tests/test_parsing.py
   pytest -v tests/test_database.py
   pytest -v tests/test_spotify.py
   pytest -v tests/test_opus_api.py
   pytest -v tests/test_main.py
   ```

4. Run with coverage report:
   ```bash
   pytest --cov=opus_sync tests/
   ```

#### Using Docker

You can also run the tests inside a Docker container:

1. Build the Docker image:
   ```bash
   docker build -t opus-spotify-sync:latest .
   ```

2. Run the tests in the container:
   ```bash
   docker run --rm -it --env-file .env.test -v opus_cache:/data opus-spotify-sync:latest test
   ```

   The tests will exit immediately on the first failure and show the error trace. 
