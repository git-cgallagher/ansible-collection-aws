#!/usr/bin/env bash
# Runs the lookup against a local moto server standing in for SSM and STS.
# moto gives each assumed role's credentials the role's account, so a
# parameter seeded through a role in TARGET_ACCOUNT is invisible to the base
# credentials and visible only through the lookup's role assumption.

set -eux

PORT=$(python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
export MOTO_ENDPOINT="http://127.0.0.1:${PORT}"
export AWS_ACCESS_KEY_ID=testing
export AWS_SECRET_ACCESS_KEY=testing
export AWS_DEFAULT_REGION=us-east-1
unset AWS_PROFILE AWS_SESSION_TOKEN || true

moto_server -H 127.0.0.1 -p "${PORT}" > "${OUTPUT_DIR:-.}/moto.log" 2>&1 &
MOTO_PID=$!
trap 'kill "${MOTO_PID}" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
    if python -c "import urllib.request, sys; urllib.request.urlopen(sys.argv[1] + '/moto-api/')" "${MOTO_ENDPOINT}" 2>/dev/null; then
        break
    fi
    sleep 0.2
done

python files/seed.py "${MOTO_ENDPOINT}"

ansible-playbook test.yml -e "moto_endpoint=${MOTO_ENDPOINT}" "$@"
