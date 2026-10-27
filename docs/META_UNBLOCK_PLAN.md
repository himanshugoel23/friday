# WhatsApp is mandatory: plan to get a Meta WhatsApp number (2026-10-28)

Situation: onboarding on the founder's own Meta login stops with "Onboarding failure: You have been temporarily blocked from performing this action." His personal Facebook account has an advertising restriction dated 12 Dec 2022 (Advertising Standards); his business portfolios show no issues. Using another person's login, or an extra account, from the founder's device/email to get around this is NOT used (Meta anti-circumvention; it also appeared to carry the same restriction notice). Meta decides; nothing here has a promised date. All Meta facts are from the screens seen and general knowledge, not from Meta's current text.

## A. Ask Meta directly (the founder's own account) - first thing in the morning
Where: Business Support Home (business.facebook.com/business-support-home) or the Help button in Business Suite, look for chat, "Get support" or "Contact us"; if there is none, the Business Help Centre "Contact support" form.
Message (edit, keep it factual, no claims that are not true):
> My business portfolio "Himanshu Goel" shows no issues. When I add WhatsApp to my app and press Continue, I get "Onboarding failure: You have been temporarily blocked from performing this action." My personal account shows an advertising restriction from 12 Dec 2022. I do not run ads. I only want to use the WhatsApp Business Platform to message my own consenting users. Can you tell me the reason for the block, whether this restriction applies to WhatsApp onboarding, and how to resolve or appeal it?
Keep the ticket number. Do not open duplicate tickets.

## B. Ask WhatsApp providers in writing (Heltar, AiSensy, Gupshup, Interakt, Wati, 360dialog)
Send the same five questions to each (email or their chat). Do not pay or share any password or token.
1. Can you set up a WhatsApp Business number for me if my personal Facebook account has an old (2022) advertising restriction? Do you create the WhatsApp business account under your own Meta account, or must I sign in with my own?
2. Do you give Meta's standard Cloud API format (same webhooks and signature), or your own API? Is WhatsApp calling supported?
3. What are the monthly fee, per-message markup, setup fee and GST in rupees?
4. Do you allow an assistant that chats with users and also phones businesses for them? Which Meta AI-provider rules apply?
5. If I leave, can I move my number and account to another provider?
Decision rule: choose only a provider that answers 1 clearly in writing and passes 4. See docs/WHATSAPP_PROVIDERS_2026-10.md.

## C. A separate legitimate owner (decide with a lawyer)
If a co-founder or the company is the genuine owner of the business, that owner sets everything up ALONE on their own device, with their own email and phone number, accepting that Meta may still link accounts. Ownership of the WhatsApp business account and number is agreed in writing (the company's). It is not a way for the founder to operate while restricted.

## D. Do not wait: keep building and testing
Chat behaviour is testable now without Meta: Chat Lab (friday/lab) and the simulator channel. Calls (Vobiz) run in parallel, they do not replace WhatsApp. Everything that needs only WhatsApp credentials (webhook, verify token, phone number ID, access token) is ready on the server side; when a number exists it is a 10-minute setup.

## E. Things not to do
No extra or someone else's Facebook accounts, no unofficial WhatsApp libraries or WhatsApp Web automation (ban risk), no repeated clicking of the blocked button, no tokens or passwords in chat or git.
