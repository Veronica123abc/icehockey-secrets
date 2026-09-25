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


def _find_dotenv(start: Path) -> Path | None:
    """Walk up directory tree from start until a .env file is found."""
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def load_dotenv(start: Path | None = None) -> Path | None:
    """Load the nearest .env walking up from ``start``; return its path.

    THE CODE THAT READS A VARIABLE SHOULD MAKE SURE THE FILE HAS BEEN READ.
    Loading the .env used to be a side effect of :meth:`Settings.from_env`,
    so any entry point that reached the database without first building
    Settings -- a module ``__main__`` with its Settings line commented out,
    say -- met an empty ``os.environ`` and died on ``KeyError:
    'DATABASE_HOST_AZURE'``. Whether it worked depended on what else the
    process happened to import, which is not a property anyone can reason
    about.

    Idempotent and cheap: the file is small, and ``_load_dotenv_if_present``
    uses ``setdefault``, so a real environment -- Azure App Settings -- is
    never overridden by a file that happens to be lying around next to the
    code.
    """
    dotenv = _find_dotenv(start or Path(__file__).resolve().parent)
    if dotenv:
        _load_dotenv_if_present(dotenv)
    return dotenv


#: The repo root: this file is hockey/config/settings.py, so two levels up.
#: Relative paths in .env (OUTPUT_DIR defaults to "./output") resolve against
#: it, which is what makes them mean the same thing to every caller.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CACHED: "Settings | None" = None


def settings() -> "Settings":
    """The repo's Settings, resolved on FIRST USE and cached.

    Why this exists rather than a module-level ``Settings.from_env(...)`` in
    each file: ``from_env`` RAISES when DATA_ROOT_DIR is unset, and
    ``metric_catalog`` imports every metric module, and the game canvas
    imports ``metric_catalog`` -- but a ``db_only`` deployment deliberately
    has no DATA_ROOT_DIR. An eager call in any of those modules means the
    canvas cannot import at all.

    That constraint needs ONE lazy accessor, not one per module. The nine
    metric modules used to carry a 13-line private copy each; they now import
    this.

    A SCRIPT SHOULD STILL CALL ``Settings.from_env`` EAGERLY. Something that
    genuinely requires DATA_ROOT_DIR ought to die at startup when it is
    missing, with the one-liner saying so at the top of the file. This is for
    library modules that must stay importable without it.
    """
    global _CACHED
    if _CACHED is None:
        _CACHED = Settings.from_env(project_root=_REPO_ROOT)
    return _CACHED


@dataclass(frozen=True, slots=True)
class Settings:
    data_root_dir: Path
    output_dir: Path
    project_root: Path | None = None



    @classmethod
    def from_env(cls, *, project_root: Path | None = None) -> "Settings":
        if project_root is not None:
            load_dotenv(project_root)

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