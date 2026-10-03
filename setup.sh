#!/bin/sh
set -eu
mkdir -p data/logs knowledge secrets
[ -f .env ] || cp .env.example .env
[ -f secrets/ha_token.txt ] || : > secrets/ha_token.txt
[ -f secrets/openai_api_key.txt ] || : > secrets/openai_api_key.txt
[ -f secrets/hassmind_api_token.txt ] || { command -v openssl >/dev/null 2>&1 && openssl rand -hex 32 > secrets/hassmind_api_token.txt || date +%s | sha256sum | awk '{print $1}' > secrets/hassmind_api_token.txt; }
[ -f secrets/telegram_bot_token.txt ] || : > secrets/telegram_bot_token.txt
[ -f secrets/camera_tts_api_key.txt ] || : > secrets/camera_tts_api_key.txt
[ -f secrets/zalo_password.txt ] || : > secrets/zalo_password.txt
[ -f secrets/zalo_webhook_secret.txt ] || { command -v openssl >/dev/null 2>&1 && openssl rand -hex 32 > secrets/zalo_webhook_secret.txt || date +%s | sha256sum | awk '{print $1}' > secrets/zalo_webhook_secret.txt; }
chmod 600 secrets/*.txt 2>/dev/null || true
# Container runs as uid/gid 10001. This makes the bind-mounted SQLite directory writable.
if [ "$(id -u)" = "0" ]; then
  chown -R 10001:10001 data
else
  echo "NOTE: run 'sudo chown -R 10001:10001 data' before deploy if SQLite reports permission denied."
fi
echo "Prepared. Edit .env and secrets/*.txt, then deploy docker-stack.yml."
