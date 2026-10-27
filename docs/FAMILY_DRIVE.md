# Family documents in the family's OWN Google Drive (item E)

Status: built and tested against fakes, switch OFF (`FRIDAY_FAMILY_DRIVE_ENABLED=false`). Nothing has run against a real
Google account. All user-facing wording (the Drive consent paragraph, `friday/familydrive/copy.py`, and the folder and file
names that appear in the user's Drive) is PENDING founder approval. No spoken lines.
Founder decision 2026-10-27: family documents live ONLY in the family's own Google Drive, never on Friday's servers.
Design source: `docs/TRIP_CONCIERGE_DESIGN.md` section E. Builds on `docs/GOOGLE_CONNECTOR.md` and `docs/DOCUMENT_UNDERSTANDING.md`.

## What it does
1. **Scope.** `drive.file` (only files and folders Friday itself creates) is added to the Google consent ONLY when the switch is on
   (`friday/google/scopes.py`, same pattern as Gmail). `drive` and `drive.readonly` are never requested; `tests/google/test_scopes.py`
   fails on any other Drive scope. A user can untick Drive on Google's screen: the Calendar connection still works and Drive calls
   say "scope missing" (nothing is called).
2. **Port.** `DrivePort` (`friday/familydrive/ports.py`): find by Friday's own key, create folder, upload, get, download, trash, share,
   unshare. `FakeDrive`/`FakeDriveHub` (tests, one separate Drive per user) and `GoogleDrive` (real Drive v3 REST over the existing OAuth
   token store, `friday/familydrive/google_drive.py`). Tests run the real adapter against `tests/google/fake_google.py` (ASGI, no sockets).
3. **Folder tree**, created lazily and idempotently per family and per trip (`friday/familydrive/tree.py`):
   `Friday/Family/<person>/Passports|Visas|IDs|Insurance|Bills|Other` and `Friday/Trips/<trip>/Tickets|Hotel|Insurance|Bills`.
   Folders are identified by a stable key (not their name), saved as `drive_folders` rows, and stamped on the Drive object as an app
   property (`friday_key`, a hash). So a rename in Drive, a lost local row or a retry after a timeout never creates a duplicate; a folder
   the user trashed is recreated (and everything cached below it forgotten). `ensure_tree(person=, trip=)` creates the whole standard tree.
4. **Filing.** `FamilyDrive.file_document(user_id, document_id, data, ...)`: only for a CONFIRMED document of that user; bytes must be a
   real PDF/JPEG/PNG/WebP (magic bytes), at most `FRIDAY_FAMILY_DRIVE_MAX_BYTES` (8 MB), and match the document's sha-256 from item D.
   The bytes are streamed from memory (64 KiB chunks, explicit Content-Length) to the right folder, never written to disk, and dropped.
   We keep only `documents.pointer_kind="gdrive"` and an encrypted `pointer_ref` (JSON: Drive file id, the display path, the generated file
   name) plus the minimal confirmed fields item D already holds. File names come only from validated fields through a character allow-list
   (`2026-11-14 DEL-GOI IndiGo.pdf`, `Passport Asha exp 2031-02-03.pdf`); no long digit run (ID or account number) ever appears in a name.
   Upload fails -> nothing is stored, the user is asked to send the file again. Pointer write fails after upload -> the uploaded file is
   trashed. A retry after a lost response finds the file by its key (no second upload). Calling it twice returns the same link.
5. **"Where is my X".** `where_is(user_id, query)`: English, Hinglish and Devanagari keywords (passport, ticket, hotel, bill...) and
   name words; returns the Drive link of the best matches. Each pointer is checked against Drive; a file the user deleted or trashed
   drops the pointer. If Drive is unreachable the link is still returned, marked unverified.
   `fetch_document` downloads into memory to send to the user only (sending elsewhere is a separate approved action, not built).
6. **Sharing with a family member.** `request_share(owner, email, role)` records the wish and shows the e-mail back; NOTHING happens at
   Google until `approve_share` (the owner's yes). Then the root `Friday` folder is shared (viewer or editor). Requests expire after
   `FRIDAY_FAMILY_DRIVE_SHARE_TTL_DAYS` (7); decline, revoke, no own-account share, at most 5 open requests. Needs its own switch
   `FRIDAY_FAMILY_DRIVE_SHARING_ENABLED` (default off). **Owner-only actor model for the pilot**: every method takes the owner's user id
   and every read filters by it; a member never logs in to Friday, they just open the shared folder in Drive. A failed share stays pending
   so the owner can retry.
7. **Disconnect.** `disconnect(user_id)` deletes the link, the folder cache, the share requests and every pointer (the document row with
   its fields) of documents filed in Drive. It works with the switch off and with Drive down. The user's FILES are theirs and are not touched;
   trashing the `Friday` folder is a separate explicit `trash_root=True` (best effort). It does NOT revoke the Google token (Calendar may
   use it). `/google/disconnect` revokes the one token and ALSO clears the Drive data.
8. **Delete everything / retention.** `DataPurger` removes the three tables with the user's other rows. Daily retention
   (`expire_family_drive` in `run_retention`): unanswered share requests become `expired`, finished ones are deleted after 30 days, a link
   stuck in `needs_reconnect` for 180 days is dropped with its pointers. Documents follow item D's retention (confirmed 180 days, the
   pointer goes with the row; the Drive file stays).

## Data (migration `0016_family_drive`)
`drive_links` (user_id unique, status active|needs_reconnect, encrypted root_folder_id), `drive_folders` (user_id, path_key, encrypted
folder_id, unique per user and key), `drive_shares` (user_id, encrypted email, role, status pending|shared|declined|revoked|expired,
encrypted permission_id, expires_at). No column holds bytes or a token. RLS is ON for all three (no policy, like every Friday table).
**Chain note:** `down_revision = "0014_documents"` because `0015_urgent_escalation` was not on this branch. When 0015 merges, change it
to `"0015_urgent_escalation"` (one line in the migration, plus the doctor comment) or Alembic will see two heads. `EXPECTED_HEAD_CHAIN` is
`0016_family_drive`.

## Settings (names only)
`FRIDAY_FAMILY_DRIVE_ENABLED` (false), `FRIDAY_FAMILY_DRIVE_SHARING_ENABLED` (false), `FRIDAY_FAMILY_DRIVE_MAX_BYTES`,
`FRIDAY_FAMILY_DRIVE_SHARE_TTL_DAYS`, `FRIDAY_GOOGLE_DRIVE_BASE_URL`, `FRIDAY_GOOGLE_DRIVE_UPLOAD_URL` (real Google by default).
The doctor lists the switch and, when on, warns that the wording is pending and the Drive facts unverified.

## Not wired / open
- No WhatsApp intent calls this yet (connect Drive, "vault mein rakho", "where is my passport", share, disconnect). Only the service,
  the OAuth scope and the `/google` routes exist. `friday.familydrive.factory.build_family_drive` builds the real service.
- **The bytes problem.** Item D drops the file bytes at the end of `process()`, before the user taps "Yes, correct". To file the original
  we need the bytes again: (a) ask the user to forward the file again after confirming (works today, clumsy), or (b) upload to a
  `Friday/Inbox` folder BEFORE the confirmation and move it on "yes" (needs one `files.update` call, not built; uploads before consent
  to file). Founder decision needed; (a) is what the code supports.
- Folder creation is serialised per user inside one process (an asyncio lock); two server processes could still race (the Drive-side key
  lookup narrows it, it does not close it).
- Names used when none is given ("Me", "Unsorted trip") are copy, pending.
- No export-as-JSON of pointers, no audit table beyond `audit_log` entries (`drive.linked`, `drive.filed`, `drive.shared`,
  `drive.disconnected`; ids and counts only).
- Not run on Postgres; migration tested on SQLite.

## Drive facts we rely on: all UNVERIFIED (general knowledge, not checked against current Google docs)
1. `drive.file` is a non-sensitive scope: no restricted-scope security assessment (the design assumes it; Gmail-readonly in the same app
   IS restricted, so keep Gmail off or use a separate OAuth project).
2. With `drive.file` the app sees only files it created (or the user opens with it via the picker), and can LIST them with `files.list`
   and a `q` filter, including `appProperties has { key='friday_key' and value='...' }` and `'<parent>' in parents`.
3. `files.create` (JSON) makes a folder (`mimeType=application/vnd.google-apps.folder`, `parents`, `appProperties`).
4. `uploadType=multipart` with `multipart/related` and an explicit `Content-Length` is accepted with a streamed body (no chunked encoding).
5. `files.get?alt=media` downloads; `files.update` with `{"trashed": true}` trashes; descendants of a trashed folder report `trashed: true`.
6. `permissions.create` with `type=user`, `role=reader|writer`, `emailAddress` shares a folder (and everything in it) and Google e-mails
   the member by default; `permissions.delete` removes it. Sharing to a non-Google e-mail is not supported by our flow.
7. A member's own Friday grant would NOT see files created by the owner's grant (per user, per app): so all Friday reads/writes use the
   OWNER's connection; members open the folder in Drive.
8. `webViewLink` is returned with `fields=` and works for the owner; we build `https://drive.google.com/file/d/<id>/view` from the id.
9. 404 on `files.get` means deleted OR not visible to this app; we treat both as "dangling" and drop the pointer.
10. OAuth app in Testing mode: about 100 test users and refresh tokens that expire after about 7 days (`needs_reconnect` will be frequent);
    unverified-app warning on the consent screen.
11. Rate limits and per-file size limits for the Drive API are not known to us (we cap uploads at 8 MB).
12. A user can remove Friday at myaccount.google.com; the next refresh gives `invalid_grant` and the link becomes `needs_reconnect`.

## One-day real-account spike (founder or builder, with a throwaway Google account; ~1 day)
Use a test OAuth project in Testing mode with ONE test user, the real adapter (`build_family_drive`) from a scratch script, and a
throwaway Drive. Never use a real family document: generate a dummy PDF. Tick off:
1. [ ] Consent screen lists "See, edit, create and delete only the specific Google Drive files you use with this app" (drive.file) next to
       Calendar; record the exact wording Google shows (our own paragraph must not contradict it).
2. [ ] Granular consent: untick Drive on Google's screen; confirm the callback still arrives and `status.drive` is false.
3. [ ] `files.create` folder with `appProperties.friday_key`; `files.list` with the `appProperties has` query and `'<id>' in parents`
       returns it; confirm `trashed=false` filtering and that a folder trashed in the Drive UI is excluded.
4. [ ] Create the full tree twice; no duplicates. Rename a folder in the Drive UI; next filing still works. Move a folder; see what
       `find_by_key(parent_id=...)` does.
5. [ ] Upload a 100 KB and a 7 MB dummy PDF with our streamed multipart body and explicit Content-Length. If Google rejects it, switch to
       the resumable upload.
6. [ ] `files.get` returns `webViewLink`; open the link signed in as the owner and as the member after sharing.
7. [ ] Trash a file and a parent folder in the UI; what do `files.get` and `files.list` return for the children (trashed flag, 404)?
8. [ ] Share the root folder with a second test Google account as viewer then editor; does the member get an e-mail; does the folder show
       under "Shared with me"; does `permissions.delete` remove access?
9. [ ] With the member's OWN Friday grant (second connection), can it list/read the owner's files? (Expected no.) Can the member upload to
       the shared folder through the owner's grant only?
10. [ ] Delete a file in the UI: `files.get` status (404 vs trashed) and our dangling handling.
11. [ ] Let the access token expire, call again (refresh path); revoke Friday at myaccount.google.com, call again (`needs_reconnect`).
12. [ ] After `/google/disconnect` the Drive files are untouched and the token is revoked.
13. [ ] Testing-mode facts: the 7-day refresh expiry, the test-user cap, the unverified-app screen.
14. [ ] Is `drive.file` accepted for brand verification without the restricted-scope assessment, in the console's scope list?
Record each result in this file (replace UNVERIFIED with the observed fact and date) before turning the switch on for anyone.

## Founder to do
Approve the wording in `friday/familydrive/copy.py` and the Drive paragraph in `friday/google/consent_copy.py`; decide the bytes
problem above; enable the Drive API in the Google Cloud project and add the `drive.file` scope to the consent screen; run the spike.
