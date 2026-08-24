#!/bin/bash

set -euo pipefail

image_name="${1:-mso5000_liveview}"
version="$(git describe --tags --abbrev=0)"
commit="$(git rev-parse --short HEAD)"
build_date="$(date -u '+%Y-%m-%d %H:%M UTC')"

docker build \
    --build-arg "MSO5000_VERSION=$version" \
    --build-arg "MSO5000_COMMIT=$commit" \
    --build-arg "MSO5000_BUILD_DATE=$build_date" \
    -t "$image_name" \
    .
