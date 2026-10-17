#!/bin/sh
# Creates a separate Docker environment without reading the root .env.
set -eu
cd "$(dirname "$0")"
if [ -e .env ]; then
    echo '.env already exists; leaving it unchanged.'
    exit 0
fi
umask 077
password=$(openssl rand -hex 32)
# noclobber also protects a concurrent setup invocation.
(set -C; sed "s/^POSTGRES_PASSWORD=$/POSTGRES_PASSWORD=$password/" .env.example > .env)
echo 'Created .env with a random database password.'
echo 'Add OPENAI_API_KEY to .env, then run:'
if [ -f compose.client.yaml ]; then
    echo '  docker compose -f compose.client.yaml up -d --wait'
else
    echo '  docker compose up --build -d --wait'
fi
