import unittest
import sqlite3
import os
import tempfile
import json
from datetime import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from opus_sync import (
    ensure_cache, cached_lookup, cache_store, 
    is_recently_not_found, cache_not_found,
    get_cached_artist_genres, cache_artist_genres,
    get_cached_track_dnb_status, cache_track_dnb_status,
    VILNIUS_TZ
)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        """Set up a temporary database for testing."""
        # Create a temporary directory for the database
        self.temp_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.temp_dir, "test_cache.sqlite3")

        # Save original environment variables
        self.original_cache_dir = os.environ.get('CACHE_DIR')
        self.original_cache_db = os.environ.get('CACHE_DB')

        # Set environment variables to use our temporary directory and file
        os.environ['CACHE_DIR'] = self.temp_dir
        os.environ['CACHE_DB'] = self.temp_db_path

        # Initialize the database
        self.conn = ensure_cache()

    def tearDown(self):
        """Clean up the temporary database."""
        self.conn.close()

        # Remove the temporary database file if it exists
        if os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)

        # Remove the temporary directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

        # Restore original environment variables
        if self.original_cache_dir:
            os.environ['CACHE_DIR'] = self.original_cache_dir
        else:
            os.environ.pop('CACHE_DIR', None)

        if self.original_cache_db:
            os.environ['CACHE_DB'] = self.original_cache_db
        else:
            os.environ.pop('CACHE_DB', None)

    def test_ensure_cache(self):
        """Test that ensure_cache creates the necessary tables."""
        # Check if tables exist
        cursor = self.conn.cursor()

        # Check tracks table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
        self.assertIsNotNone(cursor.fetchone())

        # Check not_found table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='not_found'")
        self.assertIsNotNone(cursor.fetchone())

        # Check artist_genres table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artist_genres'")
        self.assertIsNotNone(cursor.fetchone())

        # Check track_dnb_status table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='track_dnb_status'")
        self.assertIsNotNone(cursor.fetchone())

    def test_track_cache(self):
        """Test track caching functionality."""
        # Test that a non-existent key returns None
        self.assertIsNone(cached_lookup(self.conn, "nonexistent"))

        # Store a track
        cache_store(self.conn, "test_key", "spotify:track:123")

        # Verify it can be retrieved
        self.assertEqual(cached_lookup(self.conn, "test_key"), "spotify:track:123")

        # Update the track
        cache_store(self.conn, "test_key", "spotify:track:456")

        # Verify it was updated
        self.assertEqual(cached_lookup(self.conn, "test_key"), "spotify:track:456")

    def test_not_found_cache(self):
        """Test caching of tracks not found."""
        # Test that a non-existent key returns False
        self.assertFalse(is_recently_not_found(self.conn, "nonexistent"))

        # Cache a not found track
        cache_not_found(self.conn, "not_found_key")

        # Verify it's marked as recently not found
        self.assertTrue(is_recently_not_found(self.conn, "not_found_key"))

        # Store a track that was previously not found
        cache_store(self.conn, "not_found_key", "spotify:track:789")

        # Verify it's no longer marked as not found
        self.assertFalse(is_recently_not_found(self.conn, "not_found_key"))

    def test_artist_genres_cache(self):
        """Test caching of artist genres."""
        artist_id = "spotify:artist:123"
        genres = ["rock", "pop", "indie"]

        # Clear any existing data for this artist_id
        self.conn.execute("DELETE FROM artist_genres WHERE artist_id=?", (artist_id,))
        self.conn.commit()

        # Test that a non-existent artist returns None
        self.assertIsNone(get_cached_artist_genres(self.conn, artist_id))

        # Cache artist genres
        cache_artist_genres(self.conn, artist_id, genres)

        # Verify they can be retrieved
        cached_genres = get_cached_artist_genres(self.conn, artist_id)
        self.assertEqual(cached_genres, genres)

        # Update genres
        new_genres = ["electronic", "ambient"]
        cache_artist_genres(self.conn, artist_id, new_genres)

        # Verify they were updated
        cached_genres = get_cached_artist_genres(self.conn, artist_id)
        self.assertEqual(cached_genres, new_genres)

    def test_track_dnb_status_cache(self):
        """Test caching of track DNB status."""
        track_uri = "spotify:track:123"
        is_dnb = True
        track_data = {"name": "Test Track", "artists": [{"name": "Test Artist"}]}

        # Test that a non-existent track returns None
        self.assertIsNone(get_cached_track_dnb_status(self.conn, track_uri))

        # Cache track DNB status
        cache_track_dnb_status(self.conn, track_uri, is_dnb, track_data)

        # Verify it can be retrieved
        cached_status = get_cached_track_dnb_status(self.conn, track_uri)
        self.assertIsNotNone(cached_status)
        self.assertEqual(cached_status[0], is_dnb)
        self.assertEqual(cached_status[1], track_data)

        # Update status
        is_dnb = False
        new_track_data = {"name": "Updated Track", "artists": [{"name": "Updated Artist"}]}
        cache_track_dnb_status(self.conn, track_uri, is_dnb, new_track_data)

        # Verify it was updated
        cached_status = get_cached_track_dnb_status(self.conn, track_uri)
        self.assertEqual(cached_status[0], is_dnb)
        self.assertEqual(cached_status[1], new_track_data)


if __name__ == '__main__':
    unittest.main()
