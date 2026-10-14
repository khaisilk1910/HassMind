# HassMind v1.5.13 - Zalo photo note transport fix

- Fix outbound photo transport: send the private, short-lived signed note-image URL via `/api/sendImageByAccount`. The provided `zalo-bot-server` downloads it as a local file for zca-js, rather than using unsupported URL objects in `MessageContent.attachments`.
- Support authenticated Zalo Server photo-capture relay using opaque, temporary tokens in the webhook (`_hassmindImages`), fetched over the Zalo Server's existing authenticated API `/api/incomingImage/{token}`.
- Preserve direct CDN image download as a backward-compatible fallback; parse `chat.photo` JSON-string content instead of mistaking it for a user text command.
- Accept Zalo photo download sources up to 15 MB before transcoding and stripping metadata; the existing web upload limit remains 5 MB. Saved notes must still satisfy validated image and pixel-size limits.
- Serialize photo and note-command processing per Zalo thread to eliminate the quick-photo-then-text race condition.
- Protect signed image URL signatures from debug log previews.

**Deployment:** Upgrade HassMind and the matching local-build `zalo-bot-server-main` together; keep existing persistent `/data` and `/app/data` mounts unchanged. Home Assistant Zalo HACS integration is not changed by this fix.

**Limitations:** Integration tested using mocks and unit tests only; physical Zalo/HA runtime delivery must be verified after upgrade. The capture cache is temporary (10 minutes), stored in the Zalo Server temporary directory and erased on restart. A CDN image that Zalo denies even to the server cannot be recovered from its URL by this patch.
