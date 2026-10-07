"""Install the executable and the shell's public wt interface."""

import os
import shlex
import sys
from pathlib import Path

SHELL = Path(__file__).resolve().parents[1] / "wt_utils/shell.sh"


def install(home: Path, executable: Path) -> Path:
    target = home / ".local/bin/wt-utils"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not target.is_symlink():
            raise RuntimeError(f"refusing to replace existing {target}")
        if target.resolve() != executable.resolve():
            previous = target.resolve()
            if (
                not previous.is_file()
                or "from wt_utils.cli import main" not in previous.read_text()
            ):
                raise RuntimeError(f"refusing to replace existing {target}")
            target.unlink()
            target.symlink_to(executable)
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


def instructions(home: Path, shell_file: Path, path: str, shell: str) -> str:
    startup = home / (".zshrc" if Path(shell).name == "zsh" else ".bashrc")
    lines = ["Installed wt. Run the following in your terminal:", ""]
    bin_dir = home / ".local/bin"
    on_path = any(
        Path(entry or ".").expanduser().resolve() == bin_dir.resolve()
        for entry in path.split(os.pathsep)
    )
    commands = []
    if not on_path:
        commands.append('export PATH="$HOME/.local/bin:$PATH"')
    commands.append(f"source {shlex.quote(str(shell_file))}")
    for command in commands:
        if not startup.exists() or command not in startup.read_text().splitlines():
            lines.append(
                f"printf '%s\\n' {shlex.quote(command)} >> {shlex.quote(str(startup))}"
            )
        lines.append(command)
    if Path(shell).name not in ("bash", "zsh"):
        lines.extend(
            ["", "wt navigation supports Bash and Zsh; these commands configure Bash."]
        )
    lines.extend(["", "Then run: wt --help"])
    return "\n".join(lines)


if __name__ == "__main__":
    install(Path.home(), Path(sys.executable).parent / "wt-utils")
    shell_file = install_shell(Path.home())
    print(
        instructions(
            Path.home(),
            shell_file,
            os.environ.get("PATH", ""),
            os.environ.get("SHELL", "bash"),
        )
    )
