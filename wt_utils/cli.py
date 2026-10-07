"""A small Git-backed CLI; no worktree registry or shell integration."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


class Error(Exception):
    pass


class Cancelled(Exception):
    pass


def xdg(name: str, fallback: str) -> Path:
    value = os.environ.get(name, "")
    return (
        Path(value) if value and Path(value).is_absolute() else Path.home() / fallback
    )


def storage() -> Path:
    return xdg("XDG_DATA_HOME", ".local/share") / "wt-utils/worktrees"


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode:
        raise Error(result.stderr.strip() or result.stdout.strip() or "Git failed")
    return result


@dataclass
class Worktree:
    path: str
    branch: str = ""
    head: str = ""
    primary: bool = False
    locked: str | None = None
    prunable: str | None = None

    def label(self) -> str:
        kind = "main" if self.primary else "linked"
        flags = " locked" if self.locked is not None else ""
        if not Path(self.path).exists():
            flags += " missing"
        return f"{kind}{flags}  {self.branch or '(detached)'}  {self.path}"


def worktrees(repo: Path) -> list[Worktree]:
    # NUL delimiters preserve whitespace and Git's unquoted paths.
    records = run(repo, "worktree", "list", "--porcelain", "-z").stdout.split("\0\0")
    items = []
    for record in records:
        fields = {}
        for line in record.split("\0"):
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" in fields:
            items.append(
                Worktree(
                    path=fields["worktree"],
                    branch=fields.get("branch", "").removeprefix("refs/heads/"),
                    head=fields.get("HEAD", ""),
                    primary=not items,
                    locked=fields.get("locked"),
                    prunable=fields.get("prunable"),
                )
            )
    return items


def pick(labels: list[str], prompt: str, *, query: bool = False) -> int | str:
    if not shutil.which("fzf"):
        raise Error("fzf is required; install with Pixi or pass --no-interactive")
    cmd = [
        "fzf",
        "--height=50%",
        "--reverse",
        "--delimiter=\t",
        "--with-nth=2..",
        "--prompt",
        f"wt {prompt} > ",
        "--no-multi",
    ]
    if query:
        cmd += ["--print-query", "--bind=enter:accept-or-print-query"]
    env = dict(os.environ, FZF_DEFAULT_OPTS="", FZF_DEFAULT_OPTS_FILE="")
    result = subprocess.run(
        cmd,
        input="".join(
            f"{i}\t{label.replace(chr(10), ' ')}\n" for i, label in enumerate(labels)
        ),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    lines = result.stdout.splitlines()
    if query and result.returncode in (0, 1) and lines:
        typed = lines.pop(0)
        if not lines and typed:
            return typed
    if result.returncode in (1, 130):
        raise Cancelled
    if result.returncode:
        raise Error(result.stderr.strip() or "fzf failed")
    if not lines:
        raise Cancelled
    try:
        index = int(lines[-1].split("\t", 1)[0])
        if 0 <= index < len(labels):
            return index
    except ValueError:
        pass
    raise Error("fzf returned an invalid selection")


def select(
    items: list[Worktree], key: str | None, interactive: bool, command: str
) -> Worktree:
    candidates = items
    if key:
        path = str(Path(key).expanduser().resolve())
        candidates = [
            w
            for w in items
            if key in (w.branch, w.path, Path(w.path).parent.name) or w.path == path
        ]
    if not candidates:
        raise Error(f"worktree not found: {key or '(none)'}")
    if interactive:
        return candidates[int(pick([w.label() for w in candidates], command))]
    if len(candidates) != 1:
        raise Error("select a unique branch, worktree path, or bucket ID")
    return candidates[0]


def allocate(repo_name: str) -> Path:
    root = storage()
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        bucket = root / secrets.token_hex(2)
        try:
            bucket.mkdir()
            return bucket / repo_name
        except FileExistsError:
            continue
    raise Error("could not allocate a worktree directory")


def cleanup(path: Path) -> None:
    if path.parent.parent == storage():
        try:
            path.parent.rmdir()
        except OSError:
            pass


def clean(path: Path, *, discard_ignored: bool = False) -> None:
    if run(path, "status", "--porcelain", "--untracked-files=all").stdout:
        raise Error(f"uncommitted or untracked files in {path}")
    if (
        not discard_ignored
        and run(path, "ls-files", "--others", "--ignored", "--exclude-standard").stdout
    ):
        raise Error(
            f"ignored files in {path}; preserve them or explicitly use --discard-ignored for removal"
        )


def removable(tree: Worktree, current: Path) -> None:
    if tree.primary:
        raise Error("cannot remove or move the primary worktree")
    if Path(tree.path).resolve() == current:
        raise Error("cannot remove or move the current worktree")
    if tree.locked is not None:
        raise Error(f"worktree is locked: {tree.path}")


def default_base(repo: Path) -> str:
    remote = run(
        repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False
    )
    if remote.returncode == 0:
        return remote.stdout.strip()
    return "HEAD"


def create(repo: Path, items: list[Worktree], branch: str, base: str | None) -> Path:
    run(repo, "check-ref-format", "--branch", branch)
    for tree in items:
        if tree.branch == branch:
            if not Path(tree.path).is_dir():
                raise Error(
                    f"branch is attached to a missing worktree: {tree.path}; inspect with wt doctor"
                )
            return Path(tree.path)
    exists = (
        run(
            repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False
        ).returncode
        == 0
    )
    path = allocate(Path(items[0].path).name)
    try:
        args = ["worktree", "add"]
        args += (
            [str(path), branch]
            if exists
            else ["-b", branch, str(path), base or default_base(repo)]
        )
        run(repo, *args)
    except Error:
        cleanup(path)
        raise
    return path


def take(repo: Path, tree: Worktree, current: Path) -> Path:
    removable(tree, current)
    if not tree.branch:
        raise Error("cannot take a detached worktree")
    clean(current, discard_ignored=True)
    clean(Path(tree.path))
    original = run(current, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    old_ref = (
        original.stdout.strip()
        if original.returncode == 0
        else run(current, "rev-parse", "HEAD").stdout.strip()
    )
    run(Path(tree.path), "switch", "--detach", "HEAD")
    switched = False
    try:
        run(current, "switch", "--no-overwrite-ignore", tree.branch)
        switched = True
        run(repo, "worktree", "remove", tree.path)
    except Error as error:
        failures = []
        if switched:
            args = ["switch", "--no-overwrite-ignore"]
            if original.returncode:
                args.append("--detach")
            result = run(current, *args, old_ref, check=False)
            if result.returncode:
                failures.append(result.stderr.strip())
        result = run(
            Path(tree.path), "switch", "--no-overwrite-ignore", tree.branch, check=False
        )
        if result.returncode:
            failures.append(result.stderr.strip())
        extra = (
            f"; rollback needs attention: {'; '.join(failures)}"
            if failures
            else "; original branches restored"
        )
        raise Error(str(error) + extra) from error
    cleanup(Path(tree.path))
    return current


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument(
        "--repo",
        default=argparse.SUPPRESS,
        help="repository path (default: current directory)",
    )
    common.add_argument(
        "-n",
        "--no-interactive",
        action="store_true",
        default=argparse.SUPPRESS,
        help="disable fzf; require explicit selections",
    )
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="emit JSON"
    )
    result = argparse.ArgumentParser(
        prog="wt",
        parents=[common],
        allow_abbrev=False,
        description="Git worktrees in XDG storage, selected with fzf.",
    )
    result.add_argument("--version", action="version", version="wt-utils 0.1.0")
    subs = result.add_subparsers(dest="command")
    for name in ("list", "cd", "new", "move", "remove", "take", "doctor"):
        sub = subs.add_parser(name, parents=[common], allow_abbrev=False)
        if name == "new":
            sub.add_argument("branch", nargs="?")
            sub.add_argument(
                "--base", help="start a new branch at this ref; no fetch is performed"
            )
        elif name in ("cd", "move", "remove", "take"):
            sub.add_argument("selector", nargs="?", help="branch, bucket ID, or path")
        if name == "remove":
            sub.add_argument(
                "--discard-ignored",
                action="store_true",
                help="allow deletion of ignored files, after checking tracked/untracked files",
            )
    return result


def execute(args: argparse.Namespace):
    repo = Path(getattr(args, "repo", ".")).expanduser().resolve()
    items = worktrees(repo)
    current = Path(run(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    interactive = not getattr(args, "no_interactive", False)
    command = args.command or "cd"
    if command in ("list", "doctor"):
        selected = items
        if interactive:
            selected = [select(items, None, True, command)]
        if command == "doctor":
            return {
                "storage": str(storage()),
                "worktrees": [
                    asdict(w) | {"exists": Path(w.path).is_dir()} for w in selected
                ],
            }
        return [asdict(w) for w in selected]
    if command == "new":
        branch = args.branch
        if interactive:
            branches = (
                [branch]
                if branch
                else run(
                    repo, "for-each-ref", "--format=%(refname:short)", "refs/heads"
                ).stdout.splitlines()
            )
            value = pick(
                branches,
                "new (type a new branch or select existing)",
                query=branch is None,
            )
            branch = branches[value] if isinstance(value, int) else value
        if not branch:
            raise Error("wt new requires a branch with --no-interactive")
        return str(create(repo, items, branch, args.base))
    tree = select(items, getattr(args, "selector", None), interactive, command)
    path = Path(tree.path)
    if command == "cd":
        if not path.is_dir():
            raise Error(f"worktree path is missing: {path}")
        return str(path)
    removable(tree, current)
    if command == "take":
        return str(take(repo, tree, current))
    if command == "remove":
        clean(path, discard_ignored=args.discard_ignored)
        run(
            repo,
            "worktree",
            "remove",
            *(["--force"] if args.discard_ignored else []),
            str(path),
        )
        cleanup(path)
        return str(path)
    destination = allocate(Path(items[0].path).name)
    try:
        run(repo, "worktree", "move", str(path), str(destination))
    except Error:
        cleanup(destination)
        raise
    cleanup(path)
    return str(destination)


def main(argv: list[str] | None = None) -> int:
    # A directly installed console entrypoint also finds its Pixi-provided tools.
    bin_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    args = parser().parse_args(argv)
    try:
        value = execute(args)
        if getattr(args, "json", False) or isinstance(value, dict):
            print(json.dumps(value, indent=2))
        elif isinstance(value, list):
            for row in value:
                print(Worktree(**row).label())
        else:
            print(value)
        return 0
    except (Cancelled, KeyboardInterrupt):
        return 130
    except (Error, OSError) as error:
        print(f"wt: {error}", file=sys.stderr)
        return 1
