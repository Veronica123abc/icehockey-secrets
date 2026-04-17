"""
Upload game data directories to Azure Blob Storage.

Each game directory (e.g. 168742/) is uploaded with its JSON files
preserved under the same path structure:

    <container>/168742/game-info.json
    <container>/168742/playsequence.json
    ...

Usage:
    from hockey.io.blob_upload import upload_game_data
    upload_game_data([Path("/data/168742"), Path("/data/202401")])

Requirements:
    pip install azure-storage-blob
"""
from __future__ import annotations

from pathlib import Path

from azure.storage.blob import BlobServiceClient

STORAGE_ACCOUNT_NAME = "hockeystatsdata"
STORAGE_ACCOUNT_KEY = "REPLACE_WITH_YOUR_STORAGE_KEY"
CONTAINER_NAME = "gamedata"
RESOURCE_GROUP = "REPLACE_WITH_YOUR_RESOURCE_GROUP"


def _get_blob_service_client() -> BlobServiceClient:
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    return BlobServiceClient(account_url=account_url, credential=STORAGE_ACCOUNT_KEY)


def upload_game_data(game_dirs: list[Path]) -> None:
    """
    Upload one or more game directories to Azure Blob Storage.

    Args:
        game_dirs: List of paths to game directories. Each directory
                   should be named by its game ID and contain JSON files
                   (game-info.json, playsequence.json, playerTOI.json, roster.json).
    """
    client = _get_blob_service_client()
    container = client.get_container_client(CONTAINER_NAME)

    for game_dir in game_dirs:
        if not game_dir.is_dir():
            print(f"Skipping {game_dir} (not a directory)")
            continue

        game_id = game_dir.name
        for json_file in sorted(game_dir.glob("*.json")):
            blob_name = f"{game_id}/{json_file.name}"
            print(f"Uploading {blob_name}...")
            with open(json_file, "rb") as f:
                container.upload_blob(name=blob_name, data=f, overwrite=True)

    print("Done.")


def upload_all_games(data_root: Path) -> None:
    """
    Upload all game directories found under data_root.

    Scans for sub-directories whose names are numeric (game IDs).
    """
    game_dirs = sorted(
        d for d in data_root.iterdir()
        if d.is_dir() and d.name.isdigit()
    )
    print(f"Found {len(game_dirs)} game(s) to upload.")
    upload_game_data(game_dirs)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python blob_upload.py <data_root_dir>")
        print("       python blob_upload.py /home/veronica/hockeystats/ver3")
        sys.exit(1)

    root = Path(sys.argv[1])
    upload_all_games(root)
