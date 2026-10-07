#!/usr/bin/env bash
set -euo pipefail

if ! command -v pixi >/dev/null 2>&1; then
    printf 'Install Pixi first: https://pixi.sh/latest/installation/\n' >&2
    exit 1
fi
case "${XDG_DATA_HOME:-}" in
    /*) data_home="$XDG_DATA_HOME" ;;
    *) data_home="$HOME/.local/share" ;;
esac
checkout="$data_home/wt-utils/tool"
repository='https://github.com/leej3/wt-utils.git'
git_cmd() { pixi exec --spec 'git>=2.40' -- git "$@"; }

if [ -e "$checkout" ]; then
    if [ "$(git_cmd -C "$checkout" remote get-url origin)" != "$repository" ]; then
        printf 'Existing installation directory belongs to another repository: %s\n' "$checkout" >&2
        exit 1
    fi
    if [ -n "$(git_cmd -C "$checkout" status --porcelain)" ]; then
        printf 'Installation checkout has local changes: %s\n' "$checkout" >&2
        exit 1
    fi
    git_cmd -C "$checkout" pull --ff-only
else
    mkdir -p "$(dirname "$checkout")"
    git_cmd clone "$repository" "$checkout"
fi
pixi run --locked --manifest-path "$checkout/pixi.toml" install-cli
