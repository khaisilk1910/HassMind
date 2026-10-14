# HassMind v1.5.19 - Upgrade guide

This update changes only HassMind. Keep your current Zalo Bot Server and Zalo HACS.

1. Back up the HassMind database and the persistent `/data` volume (including note photos).
2. Replace the HassMind source with the files from this archive. Do not point the replacement Compose installation to a new empty `./data` directory.
3. Rebuild the HassMind container from the updated source:

   ```bash
   docker compose up -d --build --force-recreate
   ```

4. Refresh the browser and confirm version 1.5.19 on the HassMind status page.
5. In Zalo or Web Chat, try `danh sach ghi chu` or `liet ke ghi chu`.
   Expected: titles, note IDs, and the number of attached photos, with no actual photos delivered.
6. Try `tim ghi chu thuoc an than` or `Xem ghi chu #<ID>`.
   Expected: only matching notes are returned, and their attached photos remain available as before.

For long lists, Zalo can send the catalogue in multiple text messages to respect platform message-size limits. No photos should be included in those messages.

**Do not delete the `/data` Docker volume.** No database migration is required.
