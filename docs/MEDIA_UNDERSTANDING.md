# Friday understands what you send (founder ask, 21 Oct 2026)

Idea: the user forwards a video, voice note, screenshot, PDF or link to Friday on WhatsApp and Friday understands it: what it is, what matters, and what to do ("add this to my calendar", "remind me to pay this", "find out who this company is", "summarise this and tell me the steps").
Trigger: a competitor video (Instagram) that text-only tools could not see.

## What users will send, and the route for each
| Input | Route | Notes |
|---|---|---|
| Screenshot or photo (bill, ticket, product, chat) | download from WhatsApp, vision model reads it | works today with images in this chat, so the model side is proven; bills feed the savings engine |
| PDF (bill, statement, invoice) | text extraction first, vision as fallback | deterministic parsers for amounts and dates, user confirms |
| Voice note | Sarvam speech-to-text (Hinglish) then the normal brain | already half-built for calls |
| Video file (WhatsApp limit about 16 MB) | ffmpeg: audio track to speech-to-text, plus key frames (scene detection, about 8 to 12 frames) to a vision model, merged into one structured summary | needs ffmpeg on the server |
| Link to YouTube | fetch captions or transcript where public, else ask for the file | |
| Link to Instagram, X, Facebook | blocked behind login walls; Friday says so and asks for the video file or a screen recording | do not scrape; terms and bot blocks |
| Forwarded text | normal brain | |
## Output
A short WhatsApp reply: what it is in two lines, the key facts (who, what, numbers, dates), and 2 to 3 buttons for the likely actions (remind me, add to calendar, research this, save to my notes, ignore). Nothing is done without the user's tap.
## Pipeline
WhatsApp webhook gives a media id -> download through the Graph API with the access token -> encrypted temporary storage -> extraction by type -> a structured result (type, summary, entities, suggested actions, confidence) -> reply and optional follow-up tasks.
## Safety and cost
- Content from media is UNTRUSTED: text inside a video or image never becomes an instruction (prompt-injection test fixtures).
- Per-user limits (files and minutes per day), size and duration caps, cost logging per item.
- Retention: delete the media after processing or after N days (default 7), the user can delete the summary; per-user only, never used for other users or training.
- Consent: first time, one line explains what Friday does with files and how to delete.
- No faces identification or sensitive inferences about people; refuse requests to identify people from images or video.
## Not verified
How well video summaries work from sampled frames; speech-to-text accuracy on music-heavy audio; real WhatsApp media sizes and download behaviour; server memory and CPU for ffmpeg on a small droplet.
## Build outline (a future slice)
media/ package: download adapter (fake in tests), extractors (image, pdf, audio, video, link), merge step, reply builder with buttons, limits and retention, simulation fixtures (sample files created in tests, no real user media), integration with the router (switch FRIDAY_MEDIA_ENABLED, default off).
