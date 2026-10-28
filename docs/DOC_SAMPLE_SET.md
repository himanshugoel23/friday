# Sample document set: measure how well Friday reads real documents

Goal: find out, with real documents, which fields the OpenAI reader gets right before the document switch is shown to
anyone else. Nothing here is stored by the command, and nothing leaves your machine except the call to OpenAI
(same `OPENAI_API_KEY` the brain uses).

## What to photograph (one file each, 2 to 3 variants if you can)

| # | Document | Why | Variants worth trying |
|---|---|---|---|
| 1 | IRCTC train ticket (app screenshot or PDF) | PNR, train no./name, class, berth, boarding station, date/time | screenshot; the emailed PDF |
| 2 | Flight e-ticket (airline PDF or email screenshot) | PNR, flight no., airports, dep/arr times, passenger names | PDF; phone screenshot; a printed copy photographed in poor light |
| 3 | Hotel booking voucher / confirmation | hotel, city, check-in/out dates, guest, booking id | OTA email screenshot; a PDF |
| 4 | Utility bill (electricity, gas, phone, broadband) | amount due, due date, minimum due, consumer no. | a Devanagari/regional-language bill; a photo of a paper bill |
| 5 | Shop receipt (paper) | merchant, date, total | crumpled or slightly blurred photo |

Rules for the set: use your own documents only, hide or crop what you do not want to test (the reader refuses Aadhaar,
PAN, driving licence and voter-ID documents on purpose; do not include them). Do NOT put the folder in the repo (it is
public). Keep it somewhere like `~/doc-samples/`.

## Run it

```
export FRIDAY_DOCS_VISION_PROVIDER=openai     # optional: FRIDAY_DOCS_VISION_MODEL=<a vision-capable chat model>
uv run friday docs eval ~/doc-samples          # add --json for machine-readable output
```

It prints, per file: outcome, detected type, overall confidence, every field with its confidence and whether it would
need your confirmation, validator issues, and an `INJECTION-FLAG` if the file contained instruction-like text.
Nothing is written to the database. Costs a little per file (one OpenAI call each).

## How to score

Keep a simple sheet (outside the repo): for each file and each field, mark right / wrong / missing / wrongly-confident
(wrong but not flagged "needs confirm"). The number that matters most is **wrongly-confident**: it must be near zero.
Suggested bar before widening the test: type correct on 9 of 10 files, key fields (date, amount, PNR, names) right on
at least 8 of 10, and no wrongly-confident passenger name, date or amount.
