import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from opus_sync import fetch_opus


class TestOpusAPI(unittest.TestCase):
    @patch('opus_sync.requests.get')
    def test_fetch_opus_success(self, mock_get):
        """Test successful fetch from LRT Opus API."""
        # Mock response with rdsList
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "rdsList": [
                {"dt": 1625000000000, "song": "Artist1 - Title1"},
                {"dt": 1624990000000, "song": "Artist2 - Title2"}
            ]
        }
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["song"], "Artist1 - Title1")
        self.assertEqual(result[1]["song"], "Artist2 - Title2")
        
        # Verify the mock was called correctly
        mock_get.assert_called_once()
        self.assertIn("https://www.lrt.lt/api/json/rds?station=opus", mock_get.call_args[0][0])
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_rds_key(self, mock_get):
        """Test fetch with 'rds' key instead of 'rdsList'."""
        # Mock response with rds
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "rds": [
                {"dt": 1625000000000, "song": "Artist1 - Title1"},
                {"dt": 1624990000000, "song": "Artist2 - Title2"}
            ]
        }
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["song"], "Artist1 - Title1")
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_data_key(self, mock_get):
        """Test fetch with 'data' key."""
        # Mock response with data
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"dt": 1625000000000, "song": "Artist1 - Title1"},
                {"dt": 1624990000000, "song": "Artist2 - Title2"}
            ]
        }
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["song"], "Artist1 - Title1")
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_items_key(self, mock_get):
        """Test fetch with 'items' key."""
        # Mock response with items
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {"dt": 1625000000000, "song": "Artist1 - Title1"},
                {"dt": 1624990000000, "song": "Artist2 - Title2"}
            ]
        }
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["song"], "Artist1 - Title1")
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_direct_list(self, mock_get):
        """Test fetch with direct list response."""
        # Mock response with direct list
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"dt": 1625000000000, "song": "Artist1 - Title1"},
            {"dt": 1624990000000, "song": "Artist2 - Title2"}
        ]
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["song"], "Artist1 - Title1")
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_unknown_structure(self, mock_get):
        """Test fetch with unknown JSON structure."""
        # Mock response with unknown structure
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "unknown_key": "unknown_value"
        }
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result is empty
        self.assertEqual(len(result), 0)
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_non_json(self, mock_get):
        """Test fetch with non-JSON response."""
        # Mock response with ValueError on json()
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Not a JSON response"
        mock_get.return_value = mock_response
        
        # Call the function
        result = fetch_opus()
        
        # Verify the result is empty
        self.assertEqual(len(result), 0)
    
    @patch('opus_sync.requests.get')
    def test_fetch_opus_request_error(self, mock_get):
        """Test fetch with request error."""
        # Mock response with request exception
        mock_get.side_effect = Exception("Connection error")
        
        # Call the function and expect exception to be raised
        with self.assertRaises(Exception):
            fetch_opus()


if __name__ == '__main__':
    unittest.main()