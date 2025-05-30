import unittest
from unittest.mock import patch, MagicMock, call
import json
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from opus_sync import main, VILNIUS_TZ


class TestMain(unittest.TestCase):
    @patch('opus_sync.get_spotify')
    @patch('opus_sync.ensure_cache')
    @patch('opus_sync.fetch_opus')
    @patch('opus_sync.search_track')
    @patch('opus_sync.get_cached_track_dnb_status')
    @patch('opus_sync.cache_track_dnb_status')
    @patch('opus_sync.is_dnb_track')
    @patch('opus_sync.playlist_snapshot')
    @patch('opus_sync.remove_old')
    @patch('opus_sync.add_new')
    def test_main_flow(self, mock_add_new, mock_remove_old, mock_playlist_snapshot, 
                      mock_is_dnb_track, mock_cache_track_dnb_status, mock_get_cached_track_dnb_status,
                      mock_search_track, mock_fetch_opus, mock_ensure_cache, mock_get_spotify):
        """Test the main function flow."""
        # Setup mocks
        mock_sp = MagicMock()
        mock_get_spotify.return_value = mock_sp

        mock_conn = MagicMock()
        mock_ensure_cache.return_value = mock_conn

        # Mock fetch_opus to return some records
        now = datetime.now(tz=VILNIUS_TZ)
        mock_fetch_opus.return_value = [
            {"dt": now.timestamp() * 1000, "song": "Artist1 - Title1"},
            {"dt": now.timestamp() * 1000, "song": "Artist2 - Title2"},
            {"dt": now.timestamp() * 1000, "song": "Artist3 - Title3"}
        ]

        # Mock search_track to return URIs for the first two tracks and None for the third
        def mock_search_side_effect(sp, conn, artist, title, return_cache_flag=False):
            if artist == "Artist1":
                return ("spotify:track:111", False) if return_cache_flag else "spotify:track:111"
            elif artist == "Artist2":
                return ("spotify:track:222", True) if return_cache_flag else "spotify:track:222"
            else:
                return (None, False) if return_cache_flag else None

        mock_search_track.side_effect = mock_search_side_effect

        # Mock DNB status cache
        def mock_dnb_cache_side_effect(conn, uri):
            if uri == "spotify:track:111":
                return (True, {"name": "Track1", "artists": [{"name": "Artist1"}]})
            return None

        mock_get_cached_track_dnb_status.side_effect = mock_dnb_cache_side_effect

        # Mock is_dnb_track to return False for the second track
        mock_is_dnb_track.return_value = False

        # Mock track details
        mock_sp.track.return_value = {"name": "Track2", "artists": [{"name": "Artist2"}]}

        # Mock playlist snapshots
        main_snapshot = [(0, now - timedelta(hours=1), "spotify:track:old1")]
        dnb_snapshot = [(0, now - timedelta(hours=1), "spotify:track:old_dnb")]

        mock_playlist_snapshot.side_effect = [main_snapshot, main_snapshot, dnb_snapshot, dnb_snapshot]

        # Mock remove_old to return 1 for both playlists
        mock_remove_old.return_value = 1

        # Mock add_new to return the number of tracks added
        mock_add_new.side_effect = lambda sp, uris, playlist_id: len(uris)

        # Call the main function
        with patch('opus_sync.PLAYLIST_ID', 'main_playlist_id'), \
             patch('opus_sync.DNB_PLAYLIST_ID', 'dnb_playlist_id'):
            main()

        # Verify the mocks were called correctly
        mock_get_spotify.assert_called_once()
        mock_ensure_cache.assert_called_once()
        mock_fetch_opus.assert_called_once()

        # Should call search_track for all 3 records
        self.assertEqual(mock_search_track.call_count, 3)

        # Should check DNB cache for both found tracks
        self.assertEqual(mock_get_cached_track_dnb_status.call_count, 2)

        # Should call is_dnb_track for the second track (not cached)
        mock_is_dnb_track.assert_called_once_with(mock_sp, {"name": "Track2", "artists": [{"name": "Artist2"}]}, mock_conn)

        # Should cache DNB status for the second track
        mock_cache_track_dnb_status.assert_called_once()

        # Should get playlist snapshots
        self.assertEqual(mock_playlist_snapshot.call_count, 4)  # 2 for main, 2 for DNB

        # Should remove old tracks from both playlists
        self.assertEqual(mock_remove_old.call_count, 2)

        # Should add new tracks to both playlists
        self.assertEqual(mock_add_new.call_count, 2)

        # Verify the correct URIs were added to each playlist
        main_playlist_calls = [call for call in mock_add_new.call_args_list if call[0][2] == 'main_playlist_id']
        dnb_playlist_calls = [call for call in mock_add_new.call_args_list if call[0][2] == 'dnb_playlist_id']

        self.assertEqual(len(main_playlist_calls), 1)
        self.assertEqual(len(dnb_playlist_calls), 1)

        # Main playlist should have both tracks
        main_uris = main_playlist_calls[0][0][1]
        self.assertEqual(len(main_uris), 2)
        self.assertIn("spotify:track:111", main_uris)
        self.assertIn("spotify:track:222", main_uris)

        # DNB playlist should have only the first track
        dnb_uris = dnb_playlist_calls[0][0][1]
        self.assertEqual(len(dnb_uris), 1)
        self.assertIn("spotify:track:111", dnb_uris)

    @patch('opus_sync.get_spotify')
    @patch('opus_sync.ensure_cache')
    @patch('opus_sync.fetch_opus')
    @patch('opus_sync.playlist_snapshot')
    @patch('opus_sync.logging')
    def test_main_empty_records(self, mock_logging, mock_playlist_snapshot, mock_fetch_opus, mock_ensure_cache, mock_get_spotify):
        """Test main function with empty records."""
        # Setup mocks
        mock_sp = MagicMock()
        mock_get_spotify.return_value = mock_sp

        mock_conn = MagicMock()
        mock_ensure_cache.return_value = mock_conn

        # Mock fetch_opus to return empty list
        mock_fetch_opus.return_value = []

        # Mock playlist_snapshot to return an empty list
        mock_playlist_snapshot.return_value = []

        # Call the main function
        main()

        # Verify the mocks were called correctly
        mock_get_spotify.assert_called_once()
        mock_ensure_cache.assert_called_once()
        mock_fetch_opus.assert_called_once()

        # Should log that 0 records were fetched
        mock_logging.info.assert_any_call("Fetched %d recent records", 0)

    @patch('opus_sync.get_spotify')
    @patch('opus_sync.ensure_cache')
    @patch('opus_sync.fetch_opus')
    @patch('opus_sync.playlist_snapshot')
    def test_main_exception(self, mock_playlist_snapshot, mock_fetch_opus, mock_ensure_cache, mock_get_spotify):
        """Test main function with exception."""
        # Setup mocks
        mock_get_spotify.side_effect = Exception("Test exception")

        # Call the main function and expect it to raise an exception
        with self.assertRaises(Exception):
            main()


if __name__ == '__main__':
    unittest.main()
