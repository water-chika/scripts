#!/usr/bin/env bash
# Compatibility entrypoint; banana_view.py is the canonical implementation.
exec "$(dirname "$(readlink -f "$0")")/banana_view.py" "$@"
