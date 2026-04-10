from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _load_dotenv_if_present(dotenv_path: Path) -> None:
    """
    Minimal .env loader (KEY=VALUE lines).
    - Ignores comments and empty lines
    - Does NOT override existing environment variables
    """
    if not dotenv_path.exists():
        return

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class Settings:
    data_root_dir: Path
    output_dir: Path


    @classmethod
    def from_env(cls, *, project_root: Path | None = None) -> "Settings":
        # If project_root is provided, we try loading project_root/.env
        if project_root is not None:
            _load_dotenv_if_present(project_root / ".env")

        data_root = os.getenv("DATA_ROOT_DIR") or os.getenv("DATA_ROOT")
        if not data_root:
            raise ValueError(
                "DATA_ROOT_DIR is not set. Define it in your environment or in .env."
            )

        output_dir = os.getenv("OUTPUT_DIR", "./output")
        data_root_path = Path(data_root).expanduser()
        output_path = Path(output_dir).expanduser()

        if project_root is not None:
            if not data_root_path.is_absolute():
                data_root_path = (project_root / data_root_path).resolve()
            if not output_path.is_absolute():
                output_path = (project_root / output_path).resolve()

        return cls(
            data_root_dir=data_root_path,
            output_dir=output_path,
        )

        return cls(
            data_root_dir=Path(data_root).expanduser(),
            output_dir=Path(output_dir).expanduser(),
        )

    def data_path(self, *parts: str | Path) -> Path:
        """Build a path under DATA_ROOT_DIR."""
        p = self.data_root_dir
        for part in parts:
            p = p / part
        return p

    def output_path(self, *parts: str | Path) -> Path:
        """Build a path under OUTPUT_DIR."""
        p = self.output_dir
        for part in parts:
            p = p / part
        return p