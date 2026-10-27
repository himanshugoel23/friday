# The Ken: "The Great Rewiring" (AI agents for Indian consumers): notes for Friday

Source read: https://the-ken.com/the-great-rewiring/ (The Ken Case Competition 2026 page; student prototypes + reader survey, no adoption data). The Ken article "The next 10 years of AI for India" is paywalled; only its intro was readable. If the founder meant a different Ken article, send the link or screenshots.

## What people want delegated
Tedious tasks scattered across apps: trip planning across sites, meals with a cook, bank statements for visas, reimbursement claims, expense logging.
Never delegate (survey): family health 21.7%, running a wedding 20.2%.

## What the page says makes agents work (mapped to Friday)
| Point | Friday status |
|---|---|
| Spending limits set by the user + verifiable record | Approval before any payment, receipts; per-user caps not built |
| Money held until outcome confirmed, refunds | Friday never pays today (BBPS decision open) |
| Proof of completion (not the agent's claim) | Call reports exist; add evidence line (recording/screenshot) |
| Human handoff to a named person | Not built: add "hand to a person" on failures |
| Reversibility (cancel/refund paths) | Cancel flows in browser/bookings; no refund tracking |
| Voice in local languages | Core (Ritu, Hinglish); other languages later |
| Documents/photos to data | Media understanding designed (slice 4b), not built |
| Open partner rails/APIs | Vobiz, Sarvam, Google, BBPS partner TBD |
| Simple interface | WhatsApp-only, 3-line replies |
| Users trade unusual access for effort | Gmail/Calendar consent; no WhatsApp group access |

## Candidate additions (not decided)
1. Per-user daily/transaction spending cap shown at consent.
2. "Done" message always carries proof (call summary, screenshot, order id).
3. Named human fallback (founder/support number) when a task fails twice.
4. Treat health and weddings as assist-only, never auto-act (matches the guardrail list).
