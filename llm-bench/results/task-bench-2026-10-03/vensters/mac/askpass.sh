#!/bin/sh
case "$1" in
  *[Uu]sername*) printf '%s\n' janpeter ;;
  *) printf '%s\n' "$FORGEJO_TOKEN" ;;
esac
