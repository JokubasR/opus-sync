import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from opus_sync import (
    search_track, playlist_snapshot, remove_old, add_new, 
    clean_artist, is_dnb_track, VILNIUS_TZ, BATCH_SIZE
)


class TestSpotify(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        # Create a mock SQLite connection
        self.conn = MagicMock()
        
        # Mock cursor and execute method
        self.cursor = MagicMock()
        self.conn.execute.return_value = self.cursor
        self.cursor.fetchone.return_value = None  # Default to no results
        
        # Mock Spotify client
        self.sp = MagicMock()
    
    def test_clean_artist(self):
        """Test artist name cleaning."""
        self.assertEqual(clean_artist("Artist and Band"), "Artist  Band")
        self.assertEqual(clean_artist("Artist AND Band"), "Artist  Band")
        self.assertEqual(clean_artist("Artist  and  Band"), "Artist    Band")
        self.assertEqual(clean_artist("Artist"), "Artist")
        self.assertEqual(clean_artist("GandG Sindikatas"), "G&G Sindikatas")

    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_cache_hit(self, mock_cache_not_found, mock_cache_store, 
                                   mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with a cache hit."""
        # Setup mock to return a cached URI
        mock_cached_lookup.return_value = "spotify:track:123"
        mock_is_recently_not_found.return_value = False
        
        # Call the function
        result = search_track(self.sp, self.conn, "Artist", "Title")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:123")
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once_with(self.conn, "artist - title")
        mock_is_recently_not_found.assert_not_called()
        mock_cache_store.assert_not_called()
        mock_cache_not_found.assert_not_called()
        self.sp.search.assert_not_called()
    
    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_recently_not_found(self, mock_cache_not_found, mock_cache_store, 
                                           mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with a recently not found track."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = True
        
        # Call the function
        result = search_track(self.sp, self.conn, "Artist", "Title")
        
        # Verify the result
        self.assertIsNone(result)
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once_with(self.conn, "artist - title")
        mock_is_recently_not_found.assert_called_once_with(self.conn, "artist - title")
        mock_cache_store.assert_not_called()
        mock_cache_not_found.assert_not_called()
        self.sp.search.assert_not_called()
    
    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_spotify_hit(self, mock_cache_not_found, mock_cache_store, 
                                    mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with a Spotify API hit."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search response
        self.sp.search.return_value = {
            "tracks": {
                "items": [
                    {"uri": "spotify:track:456"}
                ]
            }
        }
        
        # Call the function
        result = search_track(self.sp, self.conn, "Artist", "Title")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:456")
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once_with(self.conn, "artist - title")
        mock_is_recently_not_found.assert_called_once_with(self.conn, "artist - title")
        mock_cache_store.assert_called_once_with(self.conn, "artist - title", "spotify:track:456")
        mock_cache_not_found.assert_not_called()
        self.sp.search.assert_called_once()
    
    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_spotify_miss(self, mock_cache_not_found, mock_cache_store, 
                                     mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with a Spotify API miss."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search response with no results
        self.sp.search.return_value = {
            "tracks": {
                "items": []
            }
        }
        
        # Call the function
        result = search_track(self.sp, self.conn, "Artist", "Title")
        
        # Verify the result
        self.assertIsNone(result)
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once_with(self.conn, "artist - title")
        mock_is_recently_not_found.assert_called_once_with(self.conn, "artist - title")
        mock_cache_store.assert_not_called()
        mock_cache_not_found.assert_called_once_with(self.conn, "artist - title")
        self.sp.search.assert_called_once()

    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_fallback_to_first_artist(self, mock_cache_not_found, mock_cache_store, 
                                                 mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with fallback to first artist."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search response - first search fails, second succeeds
        self.sp.search.side_effect = [
            {"tracks": {"items": []}},  # No results with all artists
            {"tracks": {"items": [{"uri": "spotify:track:789"}]}}  # Results with first artist
        ]
        
        # Call the function with multiple artists
        result = search_track(self.sp, self.conn, "Artist1, Artist2 and Artist3", "Title")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:789")
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once()
        mock_is_recently_not_found.assert_called_once()
        mock_cache_store.assert_called_once()
        mock_cache_not_found.assert_not_called()
        
        # Verify search was called twice with different queries
        self.assertEqual(self.sp.search.call_count, 2)
        first_call = self.sp.search.call_args_list[0][1]['q']
        second_call = self.sp.search.call_args_list[1][1]['q']
        
        # First call should include all artists, second only the first artist
        self.assertIn("Artist1, Artist2  Artist3", first_call)  # Note: "and" is removed by clean_artist
        self.assertIn("Artist1", second_call)
        self.assertNotIn("Artist2", second_call)
        self.assertNotIn("Artist3", second_call)

    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_fallback_to_first_artist_real_example(self, mock_cache_not_found, mock_cache_store, 
                                                         mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with fallback to first artist using a real example."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search response - first search fails, second succeeds
        self.sp.search.side_effect = [
            {"tracks": {"items": []}},  # No results with "So1o and SLJ"
            {"tracks": {"items": [{"uri": "spotify:track:solo123"}]}}  # Results with just "So1o"
        ]
        
        # Call the function with the real example
        result = search_track(self.sp, self.conn, "So1o and SLJ", "Example Track")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:solo123")
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once()
        mock_is_recently_not_found.assert_called_once()
        mock_cache_store.assert_called_once()
        mock_cache_not_found.assert_not_called()
        
        # Verify search was called twice with different queries
        self.assertEqual(self.sp.search.call_count, 2)
        first_call = self.sp.search.call_args_list[0][1]['q']
        second_call = self.sp.search.call_args_list[1][1]['q']
        
        # First call should include both artists, second only So1o
        self.assertIn('artist:"So1o  SLJ"', first_call)  # "and" is removed by clean_artist
        self.assertIn('artist:"So1o"', second_call)
        self.assertNotIn('SLJ', second_call)

    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_vs_separator(self, mock_cache_not_found, mock_cache_store, 
                                 mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with artists separated by 'Vs'."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search response - first search fails, second succeeds
        self.sp.search.side_effect = [
            {"tracks": {"items": []}},  # No results with all artists
            {"tracks": {"items": [{"uri": "spotify:track:killerz123"}]}}  # Results with just first artist
        ]
        
        # Call the function with the example using 'Vs' separator
        result = search_track(self.sp, self.conn, "Teddy Killerz Vs Serum Vs P_Money", "Example Track")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:killerz123")
        
        # Verify the mocks were called correctly
        mock_cached_lookup.assert_called_once()
        mock_is_recently_not_found.assert_called_once()
        mock_cache_store.assert_called_once()
        mock_cache_not_found.assert_not_called()
        
        # Verify search was called twice with different queries
        self.assertEqual(self.sp.search.call_count, 2)
        first_call = self.sp.search.call_args_list[0][1]['q']
        second_call = self.sp.search.call_args_list[1][1]['q']
        
        # First call should include all artists, second only the first artist
        self.assertIn('artist:"Teddy Killerz Vs Serum Vs P_Money"', first_call)
        self.assertIn('artist:"Teddy Killerz"', second_call)
        self.assertNotIn('Serum', second_call)
        self.assertNotIn('P_Money', second_call)

    @patch('opus_sync.cached_lookup')
    @patch('opus_sync.is_recently_not_found')
    @patch('opus_sync.cache_store')
    @patch('opus_sync.cache_not_found')
    def test_search_track_slash_separator(self, mock_cache_not_found, mock_cache_store, 
                                     mock_is_recently_not_found, mock_cached_lookup):
        """Test search_track with slash-separated artists."""
        # Setup mocks
        mock_cached_lookup.return_value = None
        mock_is_recently_not_found.return_value = False
        
        # Mock Spotify search responses
        self.sp.search.side_effect = [
            # First search with full artist name fails
            {"tracks": {"items": []}},
            # Second search with just the first artist succeeds
            {"tracks": {"items": [{"uri": "spotify:track:123"}]}}
        ]
        
        # Call the function with slash-separated artists
        result = search_track(self.sp, self.conn, "GOAT/MC YALLAH", "Test Title")
        
        # Verify the result
        self.assertEqual(result, "spotify:track:123")
        
        # Verify the search calls
        self.assertEqual(self.sp.search.call_count, 2)
        
        # Check first call used full artist name
        first_call = self.sp.search.call_args_list[0][1]
        self.assertIn("GOAT/MC YALLAH", first_call["q"])
        
        # Check second call used only first artist
        second_call = self.sp.search.call_args_list[1][1]
        self.assertIn("GOAT", second_call["q"])
        self.assertNotIn("MC YALLAH", second_call["q"])
        
        # Verify the cache was updated
        mock_cache_store.assert_called_once_with(self.conn, "goat/mc yallah - test title", "spotify:track:123")

    def test_playlist_snapshot_pagination(self):
        """Test playlist_snapshot function with pagination."""
        # Mock Spotify playlist_items response with pagination
        first_page = {
            "items": [
                {
                    "added_at": "2023-01-01T12:00:00Z",
                    "track": {"uri": "spotify:track:111"}
                },
                {
                    "added_at": "2023-01-02T12:00:00Z",
                    "track": {"uri": "spotify:track:222"}
                }
            ],
            "next": "next_page_url"  # Has more pages
        }
        
        second_page = {
            "items": [
                {
                    "added_at": "2023-01-03T12:00:00Z",
                    "track": {"uri": "spotify:track:333"}
                }
            ],
            "next": None  # No more pages
        }
        
        self.sp.playlist_items.return_value = first_page
        
        # Mock the next method to return the second page first, then None
        self.sp.next.side_effect = [second_page, None]
        
        # Call the function
        result = playlist_snapshot(self.sp, "playlist_id")
        
        # Verify the result
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], 0)  # First position
        self.assertEqual(result[0][2], "spotify:track:111")
        self.assertEqual(result[1][0], 1)  # Second position
        self.assertEqual(result[1][2], "spotify:track:222")
        self.assertEqual(result[2][0], 2)  # Third position
        self.assertEqual(result[2][2], "spotify:track:333")
        
        # Verify the mocks were called correctly
        self.sp.playlist_items.assert_called_once_with("playlist_id", additional_types=["track"])
        self.assertEqual(self.sp.next.call_count, 2)
        self.sp.next.assert_any_call(first_page)
        self.sp.next.assert_any_call(second_page)

    def test_playlist_snapshot(self):
        """Test playlist_snapshot function."""
        # Mock Spotify playlist_items response
        playlist_response = {
            "items": [
                {
                    "added_at": "2023-01-01T12:00:00Z",
                    "track": {"uri": "spotify:track:111"}
                },
                {
                    "added_at": "2023-01-02T12:00:00Z",
                    "track": {"uri": "spotify:track:222"}
                }
            ],
            "next": None  # No more pages
        }
        
        self.sp.playlist_items.return_value = playlist_response
        # Mock the next method to return None (no more pages)
        self.sp.next.return_value = None
        
        # Call the function
        result = playlist_snapshot(self.sp, "playlist_id")
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 0)  # First position
        self.assertEqual(result[0][2], "spotify:track:111")
        self.assertEqual(result[1][0], 1)  # Second position
        self.assertEqual(result[1][2], "spotify:track:222")
        
        # Verify the mocks were called correctly
        self.sp.playlist_items.assert_called_once_with("playlist_id", additional_types=["track"])
        self.sp.next.assert_called_once_with(playlist_response)

    def test_remove_old(self):
        """Test remove_old function."""
        # Create a snapshot with some old tracks
        now = datetime.now(tz=VILNIUS_TZ)
        old_time = now - timedelta(hours=100)  # Older than default cutoff
        recent_time = now - timedelta(hours=1)  # Newer than default cutoff
        
        snapshot = [
            (0, old_time, "spotify:track:old1"),
            (1, recent_time, "spotify:track:recent1"),
            (2, old_time, "spotify:track:old2"),
            (3, recent_time, "spotify:track:recent2")
        ]
        
        # Call the function
        result = remove_old(self.sp, snapshot, "playlist_id")
        
        # Verify the result
        self.assertEqual(result, 2)  # Should remove 2 old tracks
        
        # Verify the mock was called correctly
        self.sp.playlist_remove_specific_occurrences_of_items.assert_called_once()
        
        # Get the call arguments
        args, kwargs = self.sp.playlist_remove_specific_occurrences_of_items.call_args
        
        # Verify the playlist ID
        self.assertEqual(args[0], "playlist_id")
        
        # Verify the tracks to remove
        tracks_to_remove = args[1]
        self.assertEqual(len(tracks_to_remove), 2)
        
        # Check that the correct tracks were removed
        uris = [item["uri"] for item in tracks_to_remove]
        self.assertIn("spotify:track:old1", uris)
        self.assertIn("spotify:track:old2", uris)
        self.assertNotIn("spotify:track:recent1", uris)
        self.assertNotIn("spotify:track:recent2", uris)
    
    def test_add_new(self):
        """Test add_new function."""
        # Create a list of URIs to add
        uris = ["spotify:track:1", "spotify:track:2", "spotify:track:3"]
        
        # Call the function
        result = add_new(self.sp, uris, "playlist_id")
        
        # Verify the result
        self.assertEqual(result, 3)  # Should add 3 tracks
        
        # Verify the mock was called correctly
        self.sp.playlist_add_items.assert_called_once_with("playlist_id", uris)
    
    def test_add_new_batch(self):
        """Test add_new function with batching."""
        # Create a list of URIs that exceeds the batch size
        uris = [f"spotify:track:{i}" for i in range(BATCH_SIZE + 10)]
        
        # Call the function
        result = add_new(self.sp, uris, "playlist_id")
        
        # Verify the result
        self.assertEqual(result, BATCH_SIZE + 10)
        
        # Verify the mock was called correctly (should be called twice)
        self.assertEqual(self.sp.playlist_add_items.call_count, 2)
        
        # First batch should have BATCH_SIZE tracks
        first_call_args = self.sp.playlist_add_items.call_args_list[0][0]
        self.assertEqual(first_call_args[0], "playlist_id")
        self.assertEqual(len(first_call_args[1]), BATCH_SIZE)
        
        # Second batch should have the remaining tracks
        second_call_args = self.sp.playlist_add_items.call_args_list[1][0]
        self.assertEqual(second_call_args[0], "playlist_id")
        self.assertEqual(len(second_call_args[1]), 10)
    
    @patch('opus_sync.get_cached_artist_genres')
    @patch('opus_sync.cache_artist_genres')
    def test_is_dnb_track_from_cache(self, mock_cache_artist_genres, mock_get_cached_artist_genres):
        """Test is_dnb_track function with cached genres."""
        # Setup mock to return genres with DNB
        mock_get_cached_artist_genres.return_value = ["rock", "drum and bass", "electronic"]
        
        # Create a track with one artist
        track = {
            "artists": [
                {"id": "artist1"}
            ]
        }
        
        # Call the function
        result = is_dnb_track(self.sp, track, self.conn)
        
        # Verify the result
        self.assertTrue(result)
        
        # Verify the mocks were called correctly
        mock_get_cached_artist_genres.assert_called_once_with(self.conn, "artist1")
        mock_cache_artist_genres.assert_not_called()
        self.sp.artist.assert_not_called()
    
    @patch('opus_sync.get_cached_artist_genres')
    @patch('opus_sync.cache_artist_genres')
    def test_is_dnb_track_api_call(self, mock_cache_artist_genres, mock_get_cached_artist_genres):
        """Test is_dnb_track function with API call."""
        # Setup mock to return None (no cache)
        mock_get_cached_artist_genres.return_value = None
        
        # Mock Spotify artist response
        self.sp.artist.return_value = {
            "genres": ["electronic", "drum & bass"]
        }
        
        # Create a track with one artist
        track = {
            "artists": [
                {"id": "artist1"}
            ]
        }
        
        # Call the function
        result = is_dnb_track(self.sp, track, self.conn)
        
        # Verify the result
        self.assertTrue(result)
        
        # Verify the mocks were called correctly
        mock_get_cached_artist_genres.assert_called_once_with(self.conn, "artist1")
        mock_cache_artist_genres.assert_called_once_with(self.conn, "artist1", ["electronic", "drum & bass"])
        self.sp.artist.assert_called_once_with("artist1")
    
    @patch('opus_sync.get_cached_artist_genres')
    @patch('opus_sync.cache_artist_genres')
    def test_is_dnb_track_multiple_artists(self, mock_cache_artist_genres, mock_get_cached_artist_genres):
        """Test is_dnb_track function with multiple artists."""
        # Setup mock to return different genres for different artists
        def get_cached_genres(conn, artist_id):
            if artist_id == "artist1":
                return ["rock", "pop"]
            return None
        
        mock_get_cached_artist_genres.side_effect = get_cached_genres
        
        # Mock Spotify artist response for the second artist
        self.sp.artist.return_value = {
            "genres": ["electronic", "dnb"]
        }
        
        # Create a track with multiple artists
        track = {
            "artists": [
                {"id": "artist1"},
                {"id": "artist2"}
            ]
        }
        
        # Call the function
        result = is_dnb_track(self.sp, track, self.conn)
        
        # Verify the result
        self.assertTrue(result)
        
        # Verify the mocks were called correctly
        self.assertEqual(mock_get_cached_artist_genres.call_count, 2)
        mock_cache_artist_genres.assert_called_once_with(self.conn, "artist2", ["electronic", "dnb"])
        self.sp.artist.assert_called_once_with("artist2")

    def test_remove_old_max_tracks(self):
        """Test remove_old function with max_tracks parameter."""
        # Create a snapshot with tracks of various ages
        now = datetime.now(tz=VILNIUS_TZ)
        
        # Create 5 tracks with different timestamps (newest to oldest)
        snapshot = [
            (0, now - timedelta(hours=1), "spotify:track:newest"),
            (1, now - timedelta(hours=24), "spotify:track:newer"),
            (2, now - timedelta(hours=48), "spotify:track:middle"),
            (3, now - timedelta(hours=72), "spotify:track:older"),
            (4, now - timedelta(hours=96), "spotify:track:oldest")
        ]
        
        # Call the function with max_tracks=3 (should keep the 3 newest tracks)
        result = remove_old(self.sp, snapshot, "playlist_id", max_tracks=3)
        
        # Verify the result
        self.assertEqual(result, 2)  # Should remove 2 oldest tracks
        
        # Verify the mock was called correctly
        self.sp.playlist_remove_specific_occurrences_of_items.assert_called_once()
        
        # Get the call arguments
        args, kwargs = self.sp.playlist_remove_specific_occurrences_of_items.call_args
        
        # Verify the playlist ID
        self.assertEqual(args[0], "playlist_id")
        
        # Verify the tracks to remove
        tracks_to_remove = args[1]
        self.assertEqual(len(tracks_to_remove), 2)
        
        # Check that the correct tracks were removed (the 2 oldest)
        uris = [item["uri"] for item in tracks_to_remove]
        self.assertIn("spotify:track:older", uris)
        self.assertIn("spotify:track:oldest", uris)
        self.assertNotIn("spotify:track:newest", uris)
        self.assertNotIn("spotify:track:newer", uris)
        self.assertNotIn("spotify:track:middle", uris)
        
        # Check that positions are correct
        positions = {item["uri"]: item["positions"] for item in tracks_to_remove}
        self.assertEqual(positions["spotify:track:older"], [3])
        self.assertEqual(positions["spotify:track:oldest"], [4])
    
    def test_remove_old_max_tracks_not_exceeded(self):
        """Test remove_old function with max_tracks parameter when limit is not exceeded."""
        # Create a snapshot with fewer tracks than the max
        now = datetime.now(tz=VILNIUS_TZ)
        
        # Create 3 tracks with different timestamps
        snapshot = [
            (0, now - timedelta(hours=1), "spotify:track:newest"),
            (1, now - timedelta(hours=24), "spotify:track:newer"),
            (2, now - timedelta(hours=48), "spotify:track:oldest")
        ]
        
        # Call the function with max_tracks=5 (should not remove any tracks)
        result = remove_old(self.sp, snapshot, "playlist_id", max_tracks=5)
        
        # Verify the result
        self.assertEqual(result, 0)  # Should not remove any tracks
        
        # Verify the mock was not called
        self.sp.playlist_remove_specific_occurrences_of_items.assert_not_called()
    
    def test_remove_old_both_criteria(self):
        """Test remove_old function with both time cutoff and max_tracks."""
        # Create a snapshot with tracks of various ages
        now = datetime.now(tz=VILNIUS_TZ)
        cutoff_time = now - timedelta(hours=50)  # Cutoff at 50 hours
        
        # Create 5 tracks with different timestamps (newest to oldest)
        snapshot = [
            (0, now - timedelta(hours=1), "spotify:track:newest"),
            (1, now - timedelta(hours=24), "spotify:track:newer"),
            (2, now - timedelta(hours=48), "spotify:track:middle"),
            (3, now - timedelta(hours=72), "spotify:track:older"),
            (4, now - timedelta(hours=96), "spotify:track:oldest")
        ]
        
        # Call the function with both cutoff_hours=50 and max_tracks=4
        # Should prioritize max_tracks and remove the oldest track
        result = remove_old(self.sp, snapshot, "playlist_id", cutoff_hours=50, max_tracks=4)
        
        # Verify the result
        self.assertEqual(result, 1)  # Should remove 1 track (the oldest)
        
        # Verify the mock was called correctly
        self.sp.playlist_remove_specific_occurrences_of_items.assert_called_once()
        
        # Get the call arguments
        args, kwargs = self.sp.playlist_remove_specific_occurrences_of_items.call_args
        
        # Verify the tracks to remove
        tracks_to_remove = args[1]
        self.assertEqual(len(tracks_to_remove), 1)
        
        # Check that the correct track was removed (the oldest)
        self.assertEqual(tracks_to_remove[0]["uri"], "spotify:track:oldest")
        self.assertEqual(tracks_to_remove[0]["positions"], [4])


if __name__ == '__main__':
    unittest.main()