# wt-utils

One `wt` command for Git worktrees.
Human commands use fzf, including commands with an explicit selection.
Pass `--no-interactive` for agent or scripted use.

New worktrees live together under `${XDG_DATA_HOME:-$HOME/.local/share}/wt-utils/worktrees/<4hex>/<repo>`.
This follows the [XDG Base Directory standard](https://specifications.freedesktop.org/basedir/latest/) and does not depend on an editor or agent.
Relative XDG values are ignored.
Git's worktree registrations remain the source of truth; existing worktrees in other locations are visible and reusable.

## Install

With [Pixi](https://pixi.sh) installed:

```sh
git clone git@github.com:leej3/wt-utils.git
cd wt-utils
pixi install --locked
pixi run install-cli
pixi run pre-commit install
```

Put `~/.local/bin` on your PATH.
Installation exposes the package's actual console entrypoint by symlink; it creates no shell functions or wrappers.
Keep the checkout and Pixi environment in place.
Python, Git, and fzf come from that environment.
Re-run `pixi install --locked` after pulling updates.

## Use

```sh
wt list
wt new my-feature
wt new my-feature --base origin/main
cd "$(wt cd)"
wt move old-feature
wt take finished-feature
wt remove finished-feature
wt doctor
```

`wt` alone opens the navigation selector.
`cd` prints a path; the enclosing shell's `cd` performs navigation.
`new` reuses a branch's existing worktree or creates one.
Type a new branch in fzf and press Enter.
Without `--base`, a new branch starts from the locally recorded `origin/HEAD`, or the current HEAD if that remote default is unavailable.
Commands never fetch implicitly.

`move` puts an existing linked checkout in the central directory.
`take` moves a selected worktree's branch into the current checkout and removes the old checkout.
If the switch or removal fails, it attempts to restore both original branches and reports any rollback failure.
Primary and current worktrees cannot be removed or moved.
Locked worktrees are protected.

Removal and branch transfer refuse tracked changes and untracked files.
Ignored files are also protected; only `remove --discard-ignored` explicitly allows their deletion.
Branch switching uses Git's protection for ignored files.
Git may refuse moves/removals involving initialized submodules; the CLI reports that error without rewriting Git metadata or silently deinitializing anything.
`doctor` reports missing registrations without pruning them.

For agents and scripts, provide a unique branch, path, or bucket ID:

```sh
wt new codex/example --repo /path/to/repo --no-interactive
wt list --repo /path/to/repo --no-interactive --json
wt cd codex/example --repo /path/to/repo --no-interactive
```

Results go to stdout; errors go to stderr.
Cancelling fzf exits with status 130 without performing the selected operation.
`--json` formats results as JSON.
`list` and `doctor` select one worktree interactively; with `--no-interactive` they report every registered worktree for the repository.

## Development

```sh
pixi run test
pixi run lint
pixi run format
```

Tests use temporary local Git repositories and fake selectors.
They require no network or changes to your own worktrees.
