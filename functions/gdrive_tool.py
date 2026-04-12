"""
gdrive_tool.py -- Google Drive integration for ASHI cold storage.

Features:
  - OAuth2 desktop flow with persistent token
  - Daily backup of ~/SecondBrain/ to Google Drive
  - Upload, download, list, search files
  - Tool functions for tool_dispatch.py registration

Requires: google-auth google-auth-oauthlib google-api-python-client

Setup:
  1. Create OAuth2 credentials at console.cloud.google.com
  2. Download client_secret.json
  3. Set GOOGLE_CREDENTIALS_PATH=/path/to/client_secret.json
  4. First run will open browser for OAuth consent
  5. Token saved to ~/.ashi/gdrive_token.json (auto-refreshes)
"""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ashi.gdrive")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CREDENTIALS_PATH = Path(
    os.getenv("GOOGLE_CREDENTIALS_PATH", os.path.expanduser("~/.ashi/client_secret.json"))
)
TOKEN_PATH = Path(os.getenv("GOOGLE_TOKEN_PATH", os.path.expanduser("~/.ashi/gdrive_token.json")))
SECOND_BRAIN = Path(os.getenv("SECOND_BRAIN_PATH", os.path.expanduser("~/SecondBrain")))
DRIVE_BACKUP_FOLDER = os.getenv("ASHI_DRIVE_BACKUP_FOLDER", "ASHI_Backups")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_service = None


def _get_drive_service():
    """Get authenticated Google Drive v3 service. Lazy-loaded singleton."""
    global _service
    if _service is not None:
        return _service

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        logger.error(
            "Google Drive dependencies not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-api-python-client"
        )
        raise ImportError(f"Missing Google Drive deps: {e}") from e

    creds = None

    # Load existing token
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning("Failed to load token: %s", e)
            creds = None

    # Refresh or re-auth
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            logger.warning("Token refresh failed: %s — re-authenticating", e)
            creds = None

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Google OAuth credentials not found at {CREDENTIALS_PATH}. "
                "Download from console.cloud.google.com and set GOOGLE_CREDENTIALS_PATH."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    # Save token
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())

    _service = build("drive", "v3", credentials=creds)
    logger.info("Google Drive service authenticated")
    return _service


# ---------------------------------------------------------------------------
# Folder management
# ---------------------------------------------------------------------------

def _find_or_create_folder(name: str, parent_id: Optional[str] = None) -> str:
    """Find a folder by name, or create it. Returns folder ID."""
    service = _get_drive_service()

    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # Create folder
    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    logger.info("Created Drive folder: %s (id=%s)", name, folder["id"])
    return folder["id"]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def gdrive_upload(local_path: str, drive_folder: str = "", drive_filename: str = "") -> dict:
    """
    Upload a file to Google Drive.

    Args:
        local_path: Path to local file
        drive_folder: Target folder name in Drive (created if missing)
        drive_filename: Name in Drive (defaults to local filename)

    Returns:
        {"file_id": str, "name": str, "web_link": str}
    """
    local = Path(os.path.expanduser(local_path))
    if not local.exists():
        return {"error": f"File not found: {local}"}

    from googleapiclient.http import MediaFileUpload

    service = _get_drive_service()
    filename = drive_filename or local.name

    # Resolve parent folder
    parent_id = None
    if drive_folder:
        parent_id = _find_or_create_folder(drive_folder)

    metadata: dict = {"name": filename}
    if parent_id:
        metadata["parents"] = [parent_id]

    # Determine MIME type
    import mimetypes
    mime_type = mimetypes.guess_type(str(local))[0] or "application/octet-stream"

    media = MediaFileUpload(str(local), mimetype=mime_type, resumable=True)

    try:
        file = service.files().create(
            body=metadata, media_body=media, fields="id, name, webViewLink"
        ).execute()

        result = {
            "file_id": file["id"],
            "name": file["name"],
            "web_link": file.get("webViewLink", ""),
        }
        logger.info("Uploaded: %s -> Drive/%s/%s", local, drive_folder, filename)
        return result

    except Exception as e:
        return {"error": f"Upload failed: {e}"}


def gdrive_download(file_id: str, local_path: str) -> dict:
    """
    Download a file from Google Drive by file ID.

    Args:
        file_id: Google Drive file ID
        local_path: Where to save locally

    Returns:
        {"path": str, "size_bytes": int}
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = _get_drive_service()
    local = Path(os.path.expanduser(local_path))
    local.parent.mkdir(parents=True, exist_ok=True)

    try:
        request = service.files().get_media(fileId=file_id)
        with open(local, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()

        size = local.stat().st_size
        logger.info("Downloaded: %s -> %s (%d bytes)", file_id, local, size)
        return {"path": str(local), "size_bytes": size}

    except Exception as e:
        return {"error": f"Download failed: {e}"}


def gdrive_list(folder_name: str = "", max_results: int = 20) -> dict:
    """
    List files in a Drive folder.

    Args:
        folder_name: Folder name to list (empty = root)
        max_results: Max files to return

    Returns:
        {"files": [{"id": str, "name": str, "size": str, "modified": str}]}
    """
    service = _get_drive_service()

    query = "trashed=false"
    if folder_name:
        try:
            folder_id = _find_or_create_folder(folder_name)
            query += f" and '{folder_id}' in parents"
        except Exception:
            return {"error": f"Folder not found: {folder_name}", "files": []}

    try:
        results = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name, size, modifiedTime, mimeType)",
                pageSize=max_results,
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "size": f.get("size", "0"),
                "modified": f.get("modifiedTime", ""),
                "mime_type": f.get("mimeType", ""),
            }
            for f in results.get("files", [])
        ]

        return {"files": files, "count": len(files)}

    except Exception as e:
        return {"error": f"List failed: {e}", "files": []}


def gdrive_search(query: str, max_results: int = 10) -> dict:
    """
    Search files in Google Drive by name.

    Args:
        query: Search term (matched against file name)
        max_results: Max results

    Returns:
        {"files": [{"id": str, "name": str, "modified": str}]}
    """
    service = _get_drive_service()

    drive_query = f"name contains '{query}' and trashed=false"

    try:
        results = (
            service.files()
            .list(
                q=drive_query,
                spaces="drive",
                fields="files(id, name, size, modifiedTime, mimeType)",
                pageSize=max_results,
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "size": f.get("size", "0"),
                "modified": f.get("modifiedTime", ""),
            }
            for f in results.get("files", [])
        ]

        return {"files": files, "count": len(files)}

    except Exception as e:
        return {"error": f"Search failed: {e}", "files": []}


# ---------------------------------------------------------------------------
# Backup: Second Brain -> Google Drive
# ---------------------------------------------------------------------------

def gdrive_backup_second_brain() -> dict:
    """
    Create a tar.gz of ~/SecondBrain/ and upload to Google Drive.
    Stored in ASHI_Backups/ folder with date-stamped filename.

    Returns:
        {"file_id": str, "name": str, "size_mb": float}
    """
    if not SECOND_BRAIN.is_dir():
        return {"error": f"SecondBrain not found at {SECOND_BRAIN}"}

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_name = f"SecondBrain_{timestamp}"

    try:
        # Create tar.gz in temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = shutil.make_archive(
                os.path.join(tmpdir, archive_name),
                "gztar",
                root_dir=str(SECOND_BRAIN.parent),
                base_dir=SECOND_BRAIN.name,
            )

            size_mb = round(os.path.getsize(archive_path) / (1024 * 1024), 2)
            logger.info("SecondBrain archive: %s (%.2f MB)", archive_path, size_mb)

            # Upload
            result = gdrive_upload(
                local_path=archive_path,
                drive_folder=DRIVE_BACKUP_FOLDER,
                drive_filename=f"{archive_name}.tar.gz",
            )

            if "error" in result:
                return result

            result["size_mb"] = size_mb
            logger.info("SecondBrain backup uploaded: %s", result.get("file_id", "?"))
            return result

    except Exception as e:
        return {"error": f"Backup failed: {e}"}


# ---------------------------------------------------------------------------
# Check if Drive is configured
# ---------------------------------------------------------------------------

def gdrive_status() -> dict:
    """Check if Google Drive is configured and authenticated."""
    status = {
        "credentials_exist": CREDENTIALS_PATH.exists(),
        "token_exist": TOKEN_PATH.exists(),
        "authenticated": False,
        "backup_folder": DRIVE_BACKUP_FOLDER,
    }

    if TOKEN_PATH.exists():
        try:
            _get_drive_service()
            status["authenticated"] = True
        except Exception as e:
            status["auth_error"] = str(e)

    return status


# ---------------------------------------------------------------------------
# Manual test / first-time auth
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        print("Authenticating with Google Drive...")
        try:
            svc = _get_drive_service()
            print("Authentication successful!")
            print(f"Token saved to: {TOKEN_PATH}")
        except Exception as e:
            print(f"Authentication failed: {e}")
            sys.exit(1)

    elif len(sys.argv) > 1 and sys.argv[1] == "backup":
        print("Backing up SecondBrain to Google Drive...")
        result = gdrive_backup_second_brain()
        print(json.dumps(result, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        folder = sys.argv[2] if len(sys.argv) > 2 else ""
        result = gdrive_list(folder)
        print(json.dumps(result, indent=2))

    else:
        status = gdrive_status()
        print(json.dumps(status, indent=2))
        if not status["credentials_exist"]:
            print(f"\nSetup: Place client_secret.json at {CREDENTIALS_PATH}")
            print("Then run: python gdrive_tool.py auth")
