from hockey.config.settings import Settings
import shutil
from pathlib import Path

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]

def copy_manifests(leagues: list[int]=[1,13,17,39, 213]):

    """Copy manifest files from source to destination directory."""
    for league in leagues:
        source_path = settings.data_root_dir / 'leagues' / f'{league}'
        destination_path = Path(__file__).resolve().parent / f'{league}'
        # Copy the directory recursively
        shutil.copytree(source_path, destination_path)


if __name__ == "__main__":
    copy_manifests()