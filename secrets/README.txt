Core secret files expected by docker-compose.yml / docker-stack.yml:

ha_token.txt                Home Assistant Long-Lived Access Token
openai_api_key.txt          API key for the OpenAI-compatible LLM provider
hassmind_api_token.txt      Token for external HassMind API clients (not the web-admin password)
admin_password.txt          Initial web-admin password, used only when the admin DB is empty
admin_recovery_key.txt      Offline recovery key for the web-admin "forgot password" flow
telegram_bot_token.txt      Optional Telegram bot token

Integration credentials are preferably entered in Web Admin -> Integrations.
Runtime integration secrets are stored under /data/secrets and are not returned by the API.
Legacy camera_tts_api_key.txt / zalo_password.txt / zalo_webhook_secret.txt remain supported
when explicitly mounted/configured, but they are no longer required by the shipped stack files.

Permissions should be 0600. Never commit populated secret files to Git.
After first login, change the admin password in Settings. Keep admin_recovery_key.txt offline.
If Recovery Key is rotated in Settings, the active key is stored at /data/secrets/admin_recovery_key and supersedes this bootstrap file.
