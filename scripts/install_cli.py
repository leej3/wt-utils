"""Expose the real console entrypoint; no shell wrappers."""

import sys
from pathlib import Path


def install(home: Path, executable: Path) -> Path:
    target = home / ".local/bin/wt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == executable.resolve():
        return target
    if target.exists() or target.is_symlink():
        raise RuntimeError(f"refusing to replace existing {target}")
    target.symlink_to(executable)
    return target


if __name__ == "__main__":
    print(install(Path.home(), Path(sys.executable).parent / "wt"))
