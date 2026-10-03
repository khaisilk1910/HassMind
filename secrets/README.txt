Runtime secret files expected by docker-compose.yml / docker-stack.yml:

ha_token.txt                Home Assistant Long-Lived Access Token
openai_api_key.txt          API key for the OpenAI-compatible LLM provider
hassmind_api_token.txt      Token for external HassMind API clients (not the web-admin password)
admin_password.txt          Initial web-admin password, used only when the admin DB is empty
admin_recovery_key.txt      Offline recovery key for the web-admin "forgot password" flow
telegram_bot_token.txt      Optional Telegram bot token
camera_tts_api_key.txt      Optional camera-tts-ezviz API key
zalo_password.txt           Optional zalo-bot-server web/API login password
zalo_webhook_secret.txt     Random secret embedded in the HassMind Zalo webhook URL

Permissions should be 0600. Never commit populated secret files to Git.
After first login, change the admin password in Settings. Keep admin_recovery_key.txt offline.
If Recovery Key is rotated in Settings, the active key is stored at /data/secrets/admin_recovery_key and supersedes this bootstrap file.
