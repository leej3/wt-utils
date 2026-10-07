# wt-utils shell integration: wt is the public interface.
wt() {
    if [ "$#" -eq 0 ] || [ "$1" = cd ]; then
        [ "$#" -eq 0 ] || shift
        # Help and structured output belong to the executable.
        local argument
        for argument in "$@"; do
            case "$argument" in
                -h|--help|--json) command wt-utils cd "$@"; return ;;
            esac
        done
        local destination
        destination="$(command wt-utils cd "$@")" || return
        cd -- "$destination"
    else
        command wt-utils "$@"
    fi
}
