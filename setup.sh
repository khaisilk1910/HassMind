#!/bin/sh
set -eu
umask 077

generate_hex() {
  bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_hex($bytes))"
  elif [ -r /dev/urandom ] && command -v od >/dev/null 2>&1; then
    od -An -N "$bytes" -tx1 /dev/urandom | tr -d ' \n'
    printf '\n'
  else
    echo "ERROR: cannot generate cryptographically secure secrets (need openssl, python3, or /dev/urandom + od)." >&2
    exit 1
  fi
}

mkdir -p data/logs data/secrets knowledge secrets
[ -f .env ] || cp .env.example .env
[ -f secrets/ha_token.txt ] || : > secrets/ha_token.txt
[ -f secrets/openai_api_key.txt ] || : > secrets/openai_api_key.txt
[ -f secrets/hassmind_api_token.txt ] || generate_hex 32 > secrets/hassmind_api_token.txt
[ -f secrets/admin_password.txt ] || generate_hex 24 > secrets/admin_password.txt
[ -f secrets/admin_recovery_key.txt ] || generate_hex 32 > secrets/admin_recovery_key.txt
[ -f secrets/telegram_bot_token.txt ] || : > secrets/telegram_bot_token.txt
[ -f secrets/camera_tts_api_key.txt ] || : > secrets/camera_tts_api_key.txt
[ -f secrets/zalo_password.txt ] || : > secrets/zalo_password.txt
[ -f secrets/zalo_webhook_secret.txt ] || generate_hex 32 > secrets/zalo_webhook_secret.txt

chmod 600 secrets/*.txt 2>/dev/null || true
chmod 700 data data/logs data/secrets 2>/dev/null || true
if [ "$(id -u)" = "0" ]; then
  chown -R 10001:10001 data
else
  echo "NOTE: run 'sudo chown -R 10001:10001 data' before deploy if SQLite reports permission denied."
fi

echo "Prepared securely."
echo "Admin username: admin"
echo "Read the initial admin password with: cat secrets/admin_password.txt"
echo "Store the recovery key offline: cat secrets/admin_recovery_key.txt"
echo "Then edit .env and deploy the stack."
