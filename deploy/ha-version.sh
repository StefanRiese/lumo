#!/usr/bin/env bash
# Keeps the version of the Home Assistant integration in step with the release tag.
# HACS installs the repository at the tag, so custom_components/lumo/manifest.json must
# already carry the version when the tag is created.
#
#   bash deploy/ha-version.sh set   v0.26.0   # write the version into manifest.json
#   bash deploy/ha-version.sh check v0.26.0   # fail if manifest.json has another version

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
manifest="$ROOT/custom_components/lumo/manifest.json"
mode=${1:?usage: ha-version.sh set|check vX.Y.Z}
version=${2:?usage: ha-version.sh set|check vX.Y.Z}
version=${version#v}

if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "not a release version: $version" >&2
  exit 2
fi

current=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$manifest")

case $mode in
  set)
    sed -i "s/^\([[:space:]]*\"version\":[[:space:]]*\)\"[^\"]*\"/\1\"$version\"/" "$manifest"
    echo "manifest.json: $current -> $version"
    ;;
  check)
    if [[ $current != "$version" ]]; then
      echo "custom_components/lumo/manifest.json has version $current, the release is $version." >&2
      echo "Run: bash deploy/ha-version.sh set v$version, commit, and tag again." >&2
      exit 1
    fi
    echo "manifest.json version $current matches the tag"
    ;;
  *)
    echo "usage: ha-version.sh set|check vX.Y.Z" >&2
    exit 2
    ;;
esac
