# HassMind v1.5.12 - Zalo notes images

- Zalo webhook: parse personal-account photo attachment URL / zca-js content.href and caption.
- Receive image-only messages (previously discarded); buffer up to 5 images for 10 minutes.
- Support image-first, caption-with-image, and text-first then photo within three minutes.
- Route Zalo note intents directly through the deterministic durable notes engine.
- Search/list/view notes on Zalo and send original photos as attachments via existing companion.
- Do not expose `/api/notes/images` publicly; signed `/media/zalo-note-images/{id}` uses HMAC and expires in ten minutes.
- Reject arbitrary remote URLs, redirect chains, oversized images and invalid file formats.
- Add Web Admin Zalo media base URL configuration and troubleshooting guidance.

**Caveat**: Zalo personal companion must accept `MessageContent.attachments` in `/api/sendMessageByAccount`; requires real installation E2E validation. Zalo Official Account and Zalo Bot Platform are separate transports and were not modified.
