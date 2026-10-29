# Reply writer: one interface for "what to text and how to text it"

Founder, 2026-10-29: he wants a small trained model that only decides what to text and how to text. I recommended
building the interface and collecting approved examples first; he said yes, and yes to storing tester chat data
(testers only: the founder and his wife; deletable; nothing leaves the server without his approval).

Status: built. Switches `FRIDAY_REPLY_WRITER_ENABLED` (default **OFF**) and `FRIDAY_REPLY_LOG_ENABLED` (default **OFF**;
`deploy/enable-web-test.sh` turns the LOG on because the founder approved it, and leaves the WRITER off). With both off
nothing changes: no service is built and every gateway sends its own text. **All new chat wording is PENDING founder
approval** (greeting, store-scoped ack, "compare with the others?", plain-words failure lines, the proof-card next step).

## Design

```
gateway (shopping / planner / intents)
   builds ReplyInput (typed facts) + its own text ("legacy")
        |
   ReplyService.respond(user, ReplyInput, legacy)
        |-- writer OFF  -> the gateway's own text, unchanged
        '-- writer ON   -> write_reply(ReplyInput) -> ReplyOutput
                              |-- LlmWriter (OpenAI client + friday/style prompt block, strict JSON)
                              |      '-- FACT CHECK + style post-check on EVERY output
                              |            pass -> use it        fail -> TemplateWriter
                              '-- TemplateWriter (existing style templates; always available; the fallback)
        |
   ReplyLog.record(...)  (only when the log switch is on; whichever writer produced the text)
```

* `friday/replywriter/schema.py`: the closed contract (pydantic, `extra="forbid"`).
  `ReplyInput`: intent kind, typed `Facts` (store, product, prices in paise, pack, delivery minutes, status codes, proof
  refs, missing fields, links, as-of time), user language + script + formality, mood flag, the ONE open question
  (`pending`), style flags, offered buttons, an optional `draft` (the gateway's own text, trusted).
  `ReplyOutput`: 1-5 messages of 1-5 lines, at most one question (the last line of the last message), optional buttons
  (only from the offered list), proof refs (only from the facts), which writer, the fact-check result.
  There is no phone number, user id or raw user text anywhere in the contract.
* `templates.py` `TemplateWriter`: deterministic, built from `friday/style`, `friday/shopping/wording` and a few new lines.
  A test checks that its output passes the style post-check in English and Hinglish for every intent.
* `writer.py` `LlmWriter` + `write_reply`: system prompt = reply-writer rules + `STYLE_BLOCK`; the user message is the
  input JSON plus the template's reply as a reference. Strict JSON with a schema; 6 s timeout; any error => template.
* `factcheck.py`: **every number, price, store name, pack size and URL in the text must appear in the input facts** after
  normalisation (commas, trailing zeros, "5kg" = "5 kg", paise to rupees, list ordinals ignored, URL scheme/`www`/trailing
  slash ignored). Also: no internal status code is printed (`no_result`, `lookup:blocked`), buttons and proofs must be
  ones the caller offered, and the style rules hold: each message at most 5 lines and 450 characters, no markdown
  header, at most one question in the whole reply, no flat refusal ("did not understand", "can't" with no alternative),
  script mirrors the user. One violation rejects the whole model output and the TemplateWriter answer is used; the
  rejection is logged by code only.
* Intents that are not typed enough for a model (`passthrough`, `proof`, `confirm`) always keep the gateway's own text.
* Hooks (minimal edits, `getattr(pipeline, "reply_service")`, so nothing changes when it is None):
  shopping (ack, price comparison, failed lookup), planner (ack, lookup result or failure), intents (every playbook
  reply, plus a bare "Hi" from an active user).

## Fixes from the first live chat (all in this change)

1. **"Hi" got the salon-service question.** Cause: an open parlour conversation in `friday/quotes` (state COLLECTING,
   asking "services") consumed "Hi" as the answer, found no service and asked again ("Kaunsi service chahiye? Jaise
   haircut, beard trim, facial, waxing."). A bare greeting now passes through that flow (the question stays open) and the
   brain's small-talk reply is a warm general opener: name, who she is, three example buckets (food, shopping,
   calls/trips/reminders), one question. The same text is the TemplateWriter's `greeting`.
2. **Proof card leaked `no_result`.** A failed or blocked lookup now starts with what happened in plain words, then the
   what/where/when lines, then what Friday can do next. The code to words table is `friday/replywriter/status_words.py`
   (English and Roman Hinglish): could not read live prices, the site blocked us, the page looked different than expected,
   the site did not accept the location, it took too long, I can't look this up right now, something went wrong on the
   page. Unknown codes get a safe sentence; stored evidence carries no code either.
3. **Store scoping.** If the user names ONE store ("from blinkit") only that store is asked first (the PM gets
   `only=`), the ack line says so ("Checking only Blinkit for atta, as you asked."), and the single closing question is
   "Want me to compare with Zepto, Instamart and BigBasket too?" (buttons Compare / No thanks, or yes/no in text).
   "Yes" compares all and then asks Home or PG as before. All stores are compared at once only when no store is named or
   the user asks to compare. If the single store cannot be read the reply says why in plain words and offers the others.

## Data policy (training-data log)

* Only when `FRIDAY_REPLY_LOG_ENABLED`. Testers only (the founder and his wife; the server has no other users). Nothing
  leaves the server: `export` writes a local file and never uploads; there is no network code in the log.
* Table-free local append-only JSONL: `var/replylog/replies.jsonl` (directory 0700, file 0600; `var/` is git-ignored).
  Each line is encrypted with the existing field cipher (AES-GCM, same keys as the database) when one is available;
  otherwise a plain 0600 file.
* One record per writer call: the `ReplyInput` (facts only), the chosen output, which writer produced it
  (`llm` / `template` / `legacy` = the gateway's own text), the fact-check result, a timestamp, a pseudonymous user
  reference (hash of the internal user id, never a phone). Digit runs that look like phone numbers are masked, URL
  queries are cut, the user's first name is replaced by `<name>`, and the contract has no field for raw user text.
* Later events are appended, never edited in place: the tester's thumbs up/down (from the web chat feedback buttons,
  matched to the reply by a hash of the text), and the founder's review (approved / rejected / edited with his version as
  the gold answer).
* Retention 90 days by default (`FRIDAY_REPLY_LOG_RETENTION_DAYS`), size cap 20 MB (`FRIDAY_REPLY_LOG_MAX_MB`, oldest
  first), checked on append (hourly) and by `friday replylog prune`.
* Erasure: "delete everything" removes that tester's records (even when the log switch is off); `friday replylog delete
  --user <id>`; `friday replylog delete --all` is a hard delete of every record and every export (file removed).
* Commands (local only): `friday replylog stats`, `friday replylog export --approved-only [--out FILE]`,
  `friday replylog delete --all`, `friday replylog prune`.
* Review page: `GET /web/admin/<FRIDAY_WEB_ADMIN_TOKEN>/review` (404 without the token; off unless the admin token is
  set). Lists recent replies with the writer, fact-check result and tester reactions, and Approve / Save my version /
  Reject. "Save my version" stores the founder's text as the gold answer. The page and its JSON API expose no user
  reference.
* Not covered yet: legal read of storing tester chat under DPDP (testers are two consenting adults; the privacy page is
  still a placeholder), and what to do before any non-tester uses Friday (do not turn the log on for them without
  a consent line and a new decision).

## Fine-tuning plan (honest)

1. Collect: run with the log on and the writer off. The founder reviews replies on the review page (approve, or write the
   better version). Edited answers are the most valuable examples.
2. **Wait for about 1,000 approved examples** before a fine-tune is worth trying. With the two testers that will take
   weeks of real use, and some intents (failed lookups, scoped checks) will have far fewer. Fewer examples teach tone
   but not reliability; do not train on a few dozen.
3. Export locally with `friday replylog export --approved-only` (OpenAI chat fine-tuning JSONL: system / user = the
   `ReplyInput` JSON / assistant = the `ReplyOutput` JSON). Upload is a separate, explicit founder decision; the code
   never uploads.
4. A fine-tuned model replaces only the `LlmWriter` backend behind the same interface. It must (a) **beat the prompt
   writer on the bench** (`friday bench run`, the style and parity scenarios, plus a held-out set of reviewed examples
   not used in training), and (b) **keep the fact check**: the fact check stays on every output, whatever model wrote
   it. A model that fails the fact check more often than the prompt writer does not ship.
5. Until then the prompt writer (switch OFF by default) is itself unproven: its quality needs the founder's ear on real
   replies, and the checks only guard shape and grounding, not taste.

## Honest limits of this build

* Never run against a real model: the LlmWriter and its prompt are tested with a scripted fake client only.
* The fact check is a floor: it cannot tell that a true price was attached to the wrong product, or that advice is bad.
  A made-up word that is not a number, a known store name or a URL passes.
* Known store names are a fixed list (`factcheck.KNOWN_STORES`); a store missing from it is not caught.
* The intents gateway has no typed facts for playbook replies, so for those the model only restyles the gateway's own
  draft (its numbers are allowed because the draft is ours); the free-form review value there is low.
* Reaction matching is by text: two identical replies map to the newest record.
* With the log on and the writer off, a bare "Hi" is answered by the intents gateway (same opener text as the brain's)
  instead of the brain, so the greeting is logged.
