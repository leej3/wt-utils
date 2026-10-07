import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wt_utils import cli


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "user data"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "project with spaces"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.org")
    (root / "file").write_text("initial\n")
    (root / ".gitignore").write_text("ignored\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


def invoke(repo, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "wt_utils",
            "--repo",
            str(repo),
            "--no-interactive",
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def new(repo, branch="feature"):
    result = invoke(repo, "new", branch)
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip())


def test_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    for value in ("", "relative/path"):
        monkeypatch.setenv("XDG_DATA_HOME", value)
        assert cli.storage() == tmp_path / ".local/share/wt-utils/worktrees"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert cli.storage() == tmp_path / "xdg/wt-utils/worktrees"


def test_new_reuse_and_linked_name(repo):
    first = new(repo)
    assert first.name == repo.name
    assert first.parent.parent == cli.storage()
    assert len(first.parent.name) == 4
    assert new(repo) == first
    assert new(first, "another").name == repo.name
    rows = json.loads(invoke(first, "list", "--json").stdout)
    assert rows[0]["primary"] and rows[0]["path"] == str(repo)
    assert len(rows) == 3


def test_new_base_and_failed_allocation(repo):
    old = git(repo, "rev-parse", "HEAD")
    (repo / "file").write_text("second\n")
    git(repo, "commit", "-am", "second")
    result = invoke(repo, "new", "old", "--base", old)
    assert result.returncode == 0
    assert git(Path(result.stdout.strip()), "rev-parse", "HEAD") == old
    buckets = list(cli.storage().iterdir())
    failed = invoke(repo, "new", "bad-base", "--base", "nonexistent-ref")
    assert failed.returncode == 1
    assert list(cli.storage().iterdir()) == buckets
    assert invoke(repo, "new", "bad branch").returncode == 1


def test_remove_protects_main_current_and_lock(repo):
    tree = new(repo)
    assert "primary" in invoke(tree, "remove", "main").stderr
    assert "current" in invoke(tree, "remove", "feature").stderr
    git(repo, "worktree", "lock", str(tree))
    assert "locked" in invoke(repo, "remove", "feature").stderr
    assert tree.exists()


@pytest.mark.parametrize("filename", ["file", "untracked", "ignored"])
def test_remove_protects_files(repo, filename):
    tree = new(repo)
    (tree / filename).write_text("keep me\n")
    assert invoke(repo, "remove", "feature").returncode == 1
    assert (tree / filename).read_text() == "keep me\n"
    forced = invoke(repo, "remove", "feature", "--discard-ignored")
    assert forced.returncode == (0 if filename == "ignored" else 1)


def test_remove_cleanup(repo):
    tree = new(repo)
    assert invoke(repo, "remove", tree.parent.name).returncode == 0
    assert not tree.parent.exists()


def test_move_external(repo):
    external = repo.parent / "old sibling"
    git(repo, "worktree", "add", "-b", "external", str(external))
    result = invoke(repo, "move", str(external))
    assert result.returncode == 0, result.stderr
    destination = Path(result.stdout.strip())
    assert destination.parent.parent == cli.storage()
    assert not external.exists()
    assert git(destination, "branch", "--show-current") == "external"


def test_take(repo):
    tree = new(repo)
    result = invoke(repo, "take", "feature")
    assert result.returncode == 0, result.stderr
    assert git(repo, "branch", "--show-current") == "feature"
    assert not tree.exists()


def test_take_ignored_collision_rolls_back(repo):
    tree = new(repo)
    (tree / "ignored").write_text("incoming")
    git(tree, "add", "-f", "ignored")
    git(tree, "commit", "-m", "track ignored")
    (repo / "ignored").write_text("preserve")
    result = invoke(repo, "take", "feature")
    assert result.returncode == 1
    assert "restored" in result.stderr
    assert git(repo, "branch", "--show-current") == "main"
    assert git(tree, "branch", "--show-current") == "feature"
    assert (repo / "ignored").read_text() == "preserve"


def test_take_remove_failure_rolls_back(repo, monkeypatch):
    tree = new(repo)
    original = cli.run

    def failing(path, *args, **kwargs):
        if args[:2] == ("worktree", "remove"):
            raise cli.Error("injected removal failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(cli, "run", failing)
    with pytest.raises(cli.Error, match="original branches restored"):
        cli.take(repo, cli.worktrees(repo)[1], repo)
    assert git(repo, "branch", "--show-current") == "main"
    assert git(tree, "branch", "--show-current") == "feature"


def test_doctor_does_not_prune(repo):
    tree = new(repo)
    import shutil

    shutil.rmtree(tree)
    result = json.loads(invoke(repo, "doctor").stdout)
    assert result["worktrees"][1]["exists"] is False
    assert len(cli.worktrees(repo)) == 2
    assert invoke(repo, "cd", "feature").returncode == 1


def test_explicit_selection_and_options(repo):
    new(repo)
    assert invoke(repo, "cd").returncode == 1
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wt_utils",
            "cd",
            "main",
            "--repo",
            str(repo),
            "--no-interactive",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(result.stdout) == str(repo)
    assert result.stderr == ""


def test_fzf_all_commands_and_cancel(repo, monkeypatch):
    calls = []
    selected = new(repo)

    def fake(labels, prompt, **kwargs):
        calls.append(prompt)
        raise cli.Cancelled

    monkeypatch.setattr(cli, "pick", fake)
    for cmd in ("list", "cd", "new", "move", "remove", "take", "doctor"):
        args = ["--repo", str(repo), cmd]
        if cmd == "new":
            args.append("another")
        assert cli.main(args) == 130
    assert len(calls) == 7
    assert selected.exists() and len(cli.worktrees(repo)) == 2


def test_fzf_protocol(tmp_path, monkeypatch):
    executable = tmp_path / "fzf"
    executable.write_text("#!/bin/sh\ncat > /dev/null\nprintf '0\\tselected\\n'\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert cli.pick(["a path with spaces"], "cd") == 0
    executable.write_text(
        "#!/bin/sh\ncat > /dev/null\nprintf 'typed-branch\\n'\nexit 1\n"
    )
    assert cli.pick(["main"], "new", query=True) == "typed-branch"
    executable.write_text("#!/bin/sh\nexit 130\n")
    with pytest.raises(cli.Cancelled):
        cli.pick(["main"], "new", query=True)


def test_install_direct_entrypoint(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "install", Path(__file__).parents[1] / "scripts/install_cli.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executable = tmp_path / "env/bin/wt"
    executable.parent.mkdir(parents=True)
    executable.touch()
    target = module.install(tmp_path, executable)
    assert target.is_symlink() and target.resolve() == executable
    assert module.install(tmp_path, executable) == target
    target.unlink()
    target.write_text("foreign")
    with pytest.raises(RuntimeError, match="refusing"):
        module.install(tmp_path, executable)


def test_remote_default_is_used(repo):
    git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    old = git(repo, "rev-parse", "HEAD")
    (repo / "file").write_text("second")
    git(repo, "commit", "-am", "second")
    tree = new(repo)
    assert git(tree, "rev-parse", "HEAD") == old


def test_initialized_submodule_move_leaves_tree(repo):
    source = repo.parent / "module source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.org")
    (source / "data").write_text("module")
    git(source, "add", ".")
    git(source, "commit", "-m", "module")
    git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(source),
        "module",
    )
    git(repo, "commit", "-am", "add module")
    tree = new(repo)
    git(tree, "-c", "protocol.file.allow=always", "submodule", "update", "--init")
    result = invoke(repo, "move", "feature")
    assert result.returncode == 1
    assert "submodule" in result.stderr.lower()
    assert (tree / "module/data").read_text() == "module"
    assert len(cli.worktrees(repo)) == 2


def test_real_fzf_new_query(tmp_path):
    # A controlling terminal is required even though selection uses piped input.
    import fcntl
    import pty
    import select
    import struct
    import termios
    import time

    output = tmp_path / "result"
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        try:
            value = cli.pick(["main"], "new", query=True)
            output.write_text(json.dumps(value))
            os._exit(0)
        except (cli.Error, OSError):
            os._exit(1)
    transcript = bytearray()
    sent = False
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                transcript.extend(data)
                if b"\x1b[6n" in data:
                    os.write(fd, b"\x1b[1;1R")
                if not sent and b"main" in data:
                    os.write(fd, b"new-feature\r")
                    sent = True
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                assert os.waitstatus_to_exitcode(status) == 0
                break
        else:
            pytest.fail(f"fzf terminal interaction timed out: {transcript!r}")
        assert json.loads(output.read_text()) == "new-feature"
    finally:
        os.close(fd)
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except ProcessLookupError:
            pass
