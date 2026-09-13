#!/usr/bin/env bash
# harvest-secrets.sh <source-env-file> <secrets-file>
#
# Copies every per-repo secret line (NGIT_CI_SECRET_<ALIAS>__<NAME>,
# NGIT_CI_OPERATOR_BUNKER) from an existing .env into the secrets file that
# compose injects through env_file. The .env is the file this role rewrites, so
# anything left only there would be dropped on the next run; the secrets file is
# never overwritten and its existing values always win.
#
# Only file contents move: nothing is printed, so a secret value never reaches
# Ansible output or a log.
set -euo pipefail

ENV_FILE="${1:?usage: harvest-secrets.sh <source-env-file> <secrets-file>}"
SECRETS="${2:?usage: harvest-secrets.sh <source-env-file> <secrets-file>}"

umask 077
mkdir -p "$(dirname "$SECRETS")"
touch "$SECRETS"
chmod 0600 "$SECRETS"

[ -f "$ENV_FILE" ] || exit 0

{ grep -E '^(NGIT_CI_SECRET_[A-Za-z0-9_]+|NGIT_CI_OPERATOR_BUNKER)=' "$ENV_FILE" || true; } |
  while IFS= read -r line; do
    key="${line%%=*}"
    if ! grep -q "^${key}=" "$SECRETS"; then
      printf '%s\n' "$line" >> "$SECRETS"
    fi
  done
