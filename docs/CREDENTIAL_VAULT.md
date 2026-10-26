# Website password vault (BUILT 2026-10-26; default OFF per tester)

Founder decision (2026-10-26): Friday may store a user's login for a website that needs a password, so the private browser can log in for them. This REVERSES the earlier rule "Friday never stores passwords" for website logins only. OTP, card numbers, UPI PIN and bank logins are still never stored.

## The flow
1. The browser flow needs a login and none is saved -> `CredentialService.request_link(user, site, hosts)` returns a one-time link `/connectors/credentials/<token>` (single use, 10 min, 5 tries, cross-site posts refused, `no-store`).
2. The user opens it on their phone and types username + password on that page and ticks the consent box. Never in WhatsApp chat, never through a tool argument, never to a model.
3. `CredentialVault.save` encrypts it (AES-GCM, field cipher, key from `FRIDAY_FIELD_KEY` / KMS) per (user, site); AAD binds it to that user and site; slot ids are blind indexes; a second encrypted "meta" blob lets the user see site names and a masked username (`ra***`), never the password.
4. In the browser worker `CredentialService.autofill(session, ...)` fills the site's own fields, only if the page host matches a host the login was saved for, only for the session's own user and site, only if switched on. The `Credential` object prints as `Credential(***)` and cannot be pickled. Audit records counts only.
5. "forget my logins" -> `CredentialService.forget(user[, site])` deletes slots and revokes open links. Entries also expire after 90 days.

## Refused always
Banks, UPI / payments, cards, government-ID sites (word list in `credentials.py::_BLOCKED_WORDS`, checked on the site key and every host). Edit the list with a test.

## Switches (`FRIDAY_BROWSER_*`, default off)
`CREDENTIALS_ENABLED=false`, `CREDENTIALS_ENABLED_USERS=` (ids or `*`; empty enables nobody; also needs `FRIDAY_BROWSER_ENABLED=true`), `CREDENTIALS_TTL_DAYS=90`, `CREDENTIALS_DIR=var/browser_credentials` (keep `var/` out of git), `CREDENTIALS_LINK_TTL_SECONDS=600`.

## Code and tests
`friday/connectors/session/{credentials,credential_tokens,credential_service}.py`, `friday/api/connectors_credentials.py`, tests `tests/browser_runtime/test_credentials.py` (15: encryption, user isolation, ciphertext swap, consent, blocked sites, host binding, no leak by print/pickle/format, expiry/delete, secure page, autofill, audit has no values).

## NOT done / still needed
- WIRING (same list as the browser): mount `credentials_router(tokens, vault)` under `/connectors` in `friday serve`; build the `CredentialVault` from `FileVaultStore(credentials_dir)` + the live KMS cipher; call `forget` from "delete everything"; WhatsApp commands "my logins" / "forget my logins" (`saved`, `forget`); the connector must call `autofill` with each site's selectors and fall back to the takeover link when it returns False.
- WORDING PENDING founder approval: the secure page text and the consent sentence in `api/connectors_credentials.py`, and the WhatsApp messages that carry the link.
- A real KMS key for live (the dev local key is not for real users); legal read (DPDP: purpose, consent, deletion; site terms for automated login); real-site and real-device test. Passwords of the founder's own accounts only, supervised, until then.
- Known limit: a site that changes its login page needs a selector update; a stolen server + key would expose logins, hence per-tester opt-in and KMS.
