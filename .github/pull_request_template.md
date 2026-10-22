## What and why

## Checklist
- [ ] Tests added or updated; `uv run ruff check .` and `uv run pytest -q` pass
- [ ] No secrets: no keys, tokens, passwords, `.env` or `var/` in the diff (names of keys only)
- [ ] No real call, purchase, login or message was made by this change or its tests
- [ ] New switch? Default is OFF, named in `docs/`, shown by `friday doctor`
- [ ] Irreversible action? It goes through the gate (approval first)
- [ ] Per-user isolation kept (no shared state between users)
- [ ] Migration? Single head, upgrade and downgrade tested
- [ ] Spoken lines/voices changed? Audio sample link: (hear before change)
- [ ] Docs updated (`docs/HANDOFF.md` state, relevant doc)
