Runtime secret files expected by docker-compose.yml / docker-stack.yml:

ha_token.txt               Home Assistant Long-Lived Access Token
openai_api_key.txt          API key for the OpenAI-compatible LLM provider
hassmind_api_token.txt      Token used to log in to HassMind dashboard/API
telegram_bot_token.txt      Optional Telegram bot token
camera_tts_api_key.txt      Optional camera-tts-ezviz API key
zalo_password.txt           Optional zalo-bot-server web/API login password
zalo_webhook_secret.txt     Random secret embedded in the HassMind Zalo webhook URL

Never commit populated secret files to Git.
