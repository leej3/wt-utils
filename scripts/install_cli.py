"""Install the executable and the shell's public wt interface."""

import os
import sys
from pathlib import Path

SHELL = Path(__file__).resolve().parents[1] / "wt_utils/shell.sh"


def install(home: Path, executable: Path) -> Path:
    target = home / ".local/bin/wt-utils"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.resolve() != executable.resolve():
            raise RuntimeError(f"refusing to replace existing {target}")
    else:
        target.symlink_to(executable)
    # Remove only this project's former entrypoint, including a dangling link.
    old = target.with_name("wt")
    if old.is_symlink() and old.readlink() == executable.with_name("wt"):
        old.unlink()
    return target


def install_shell(home: Path, config: Path | None = None) -> Path:
    value = os.environ.get("XDG_CONFIG_HOME", "")
    config = config or (
        Path(value) if value and Path(value).is_absolute() else home / ".config"
    )
    target = config / "wt-utils/shell.sh"
    if target.exists() and not target.read_text().startswith(
        "# wt-utils shell integration:"
    ):
        raise RuntimeError(f"refusing to replace existing {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SHELL.read_text())
    return target


if __name__ == "__main__":
    print(install(Path.home(), Path(sys.executable).parent / "wt-utils"))
    print(f'Source "{install_shell(Path.home())}" in your shell startup file.')
