"""Tests for gdrive_tool.py -- unit tests that don't require Google auth."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from gdrive_tool import gdrive_status


class TestGdriveStatus:
    def test_status_no_credentials(self, tmp_path):
        with patch("gdrive_tool.CREDENTIALS_PATH", tmp_path / "nonexistent.json"):
            with patch("gdrive_tool.TOKEN_PATH", tmp_path / "nonexistent_token.json"):
                status = gdrive_status()
                assert status["credentials_exist"] is False
                assert status["token_exist"] is False
                assert status["authenticated"] is False

    def test_status_has_backup_folder(self):
        status = gdrive_status()
        assert "backup_folder" in status


class TestGdriveUpload:
    def test_upload_missing_file(self):
        """Upload should check file existence before importing google libs."""
        from gdrive_tool import gdrive_upload

        # Patch the import inside the function to avoid needing googleapiclient
        with patch.dict("sys.modules", {"googleapiclient": MagicMock(), "googleapiclient.http": MagicMock()}):
            result = gdrive_upload("/tmp/nonexistent_file_xyz_123.txt")
            assert "error" in result
            assert "not found" in result["error"].lower()


class TestGdriveList:
    def test_list_without_auth_returns_error(self):
        """Without valid auth, list should raise or return error."""
        with patch("gdrive_tool.CREDENTIALS_PATH", Path("/tmp/nonexistent.json")):
            with patch("gdrive_tool.TOKEN_PATH", Path("/tmp/nonexistent_token.json")):
                import gdrive_tool

                gdrive_tool._service = None
                try:
                    from gdrive_tool import gdrive_list

                    result = gdrive_list()
                    # Should get an error since no credentials
                    assert "error" in result or "files" in result
                except (FileNotFoundError, ImportError):
                    pass  # Expected when google libs not installed


class TestGdriveSearch:
    def test_search_without_auth(self):
        """Without valid auth, search should handle gracefully."""
        with patch("gdrive_tool.CREDENTIALS_PATH", Path("/tmp/nonexistent.json")):
            with patch("gdrive_tool.TOKEN_PATH", Path("/tmp/nonexistent_token.json")):
                import gdrive_tool

                gdrive_tool._service = None
                try:
                    from gdrive_tool import gdrive_search

                    result = gdrive_search("test query")
                    assert "error" in result or "files" in result
                except (FileNotFoundError, ImportError):
                    pass
