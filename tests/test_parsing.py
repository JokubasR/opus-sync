import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from opus_sync import parse_records, _parse_dt, VILNIUS_TZ, ART_TITLE_RE, YEAR_RE, FEAT_RE


class TestParsing(unittest.TestCase):
    def test_parse_dt_timestamp(self):
        """Test parsing datetime from timestamp."""
        # Test with millisecond timestamp
        timestamp = 1625000000000  # 2021-06-29 19:33:20 UTC
        expected = datetime.fromtimestamp(timestamp / 1000, tz=VILNIUS_TZ)
        self.assertEqual(_parse_dt(timestamp), expected)

    def test_parse_dt_string(self):
        """Test parsing datetime from string."""
        # Test with string format
        dt_str = "2025.05.26 15:51"
        expected = datetime.strptime(dt_str, "%Y.%m.%d %H:%M").replace(tzinfo=VILNIUS_TZ)
        self.assertEqual(_parse_dt(dt_str), expected)

    def test_parse_dt_invalid(self):
        """Test parsing invalid datetime."""
        # Test with invalid inputs
        self.assertIsNone(_parse_dt(None))
        self.assertIsNone(_parse_dt("invalid date"))
        self.assertIsNone(_parse_dt({}))

    def test_art_title_re(self):
        """Test artist-title regex pattern."""
        # Valid format
        m = ART_TITLE_RE.match("Artist Name - Song Title")
        self.assertIsNotNone(m)
        artist, title = m.groups()
        self.assertEqual(artist, "Artist Name")
        self.assertEqual(title, "Song Title")

        # Invalid format
        self.assertIsNone(ART_TITLE_RE.match("Artist Name: Song Title"))

    def test_year_re(self):
        """Test year regex pattern."""
        # With year
        self.assertEqual(YEAR_RE.sub("", "Song Title (2024)"), "Song Title ")

        # Without year
        self.assertEqual(YEAR_RE.sub("", "Song Title"), "Song Title")

    def test_feat_re(self):
        """Test featuring artist regex pattern."""
        # With feat
        self.assertEqual(FEAT_RE.sub("", "Song Title (feat. Another Artist)"), "Song Title ")
        self.assertEqual(FEAT_RE.sub("", "Song Title (ft. Another Artist)"), "Song Title ")

        # Without feat
        self.assertEqual(FEAT_RE.sub("", "Song Title"), "Song Title")

    def test_parse_records_empty(self):
        """Test parsing empty records list."""
        self.assertEqual(parse_records([]), [])

    def test_parse_records_valid(self):
        """Test parsing valid records."""
        now = datetime.now(tz=VILNIUS_TZ)

        # Create test records
        records = [
            {"dt": now.timestamp() * 1000, "song": "Artist1 - Title1"},
            {"time": (now - timedelta(hours=1)).timestamp() * 1000, "song": "Artist2 - Title2 (2024)"},
            {"timestamp": (now - timedelta(hours=2)).timestamp() * 1000, "name": "Artist3 - Title3 (feat. Someone)"},
            # Old record (beyond cutoff)
            {"dt": (now - timedelta(hours=100)).timestamp() * 1000, "song": "OldArtist - OldTitle"},
            # Invalid format
            {"dt": now.timestamp() * 1000, "song": "Invalid Format"},
            # Empty song
            {"dt": now.timestamp() * 1000, "song": ""},
            # Duplicate (should be deduplicated and kept as earliest instance)
            {"dt": (now - timedelta(hours=3)).timestamp() * 1000, "song": "Artist1 - Title1"},
        ]

        result = parse_records(records)

        # Should have 3 valid records (deduplicated)
        self.assertEqual(len(result), 3)

        # Check content of first record (Artist1 is first because its duplicate is earliest)
        self.assertEqual(result[0][1], "Artist1")
        self.assertEqual(result[0][2], "Title1")

        # Check content of second record
        self.assertEqual(result[1][1], "Artist3")
        self.assertEqual(result[1][2], "Title3")

        # Check content of third record
        self.assertEqual(result[2][1], "Artist2")
        self.assertEqual(result[2][2], "Title2")  # Year should be removed

    def test_parse_records_deduplication(self):
        """Test deduplication of records."""
        now = datetime.now(tz=VILNIUS_TZ)

        # Create test records with duplicates (different case)
        records = [
            {"dt": now.timestamp() * 1000, "song": "Artist - Title"},
            {"dt": (now - timedelta(hours=1)).timestamp() * 1000, "song": "ARTIST - title"},
            {"dt": (now - timedelta(hours=2)).timestamp() * 1000, "song": "artist - TITLE"},
        ]

        result = parse_records(records)

        # Should have only 1 record (earliest one)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "artist")
        self.assertEqual(result[0][2], "TITLE")


if __name__ == '__main__':
    unittest.main()
