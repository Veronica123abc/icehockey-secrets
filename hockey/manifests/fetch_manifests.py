from hockey.config.settings import Settings
import shutil
from pathlib import Path

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]

def copy_manifests(leagues: list[int]=[1,13,17,39, 213]):
    """Copy manifest files from source to destination directory."""
    manifest_dir = Path(__file__).resolve().parent

    # Copy global teams lookup
    shutil.copy2(settings.data_root_dir / "teams.json", manifest_dir / "teams.json")

    # Copy per-league schedule/competition directories
    for league in leagues:
        source_path = settings.data_root_dir / 'leagues' / f'{league}'
        destination_path = manifest_dir / f'{league}'
        if destination_path.exists():
            shutil.rmtree(destination_path)
        shutil.copytree(source_path, destination_path)


if __name__ == "__main__":
    copy_manifests()