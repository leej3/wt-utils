**AI-generated draft — not reviewed by John**

# wt-utils

Git worktrees let you keep several branches checked out at once, so you can leave unfinished work in place while reviewing a change or starting another experiment.
`wt` makes creating, finding, navigating, and removing worktrees easier with fzf selection and one shared storage location.
Pixi supplies the dependencies; agents can disable selection with `--no-interactive`.

## Install

With [Pixi](https://pixi.sh) installed, run this command and follow the printed instructions:

```sh
curl -fsSL https://raw.githubusercontent.com/leej3/wt-utils/main/install.sh | bash
```

## Use

Run `wt` to select a worktree and change into it.
For commands and options, use:

```sh
wt --help
wt new --help
```

The [agent skill](https://github.com/leej3/skills-workshop/blob/main/.apm/skills/wt-utils/SKILL.md) guides noninteractive agent usage.

## How navigation works

An executable cannot change its parent shell's working directory.
The `wt` shell function sidesteps this by calling the `wt-utils` executable for the selected path and changing directories in your current shell; other subcommands pass through to the executable.
