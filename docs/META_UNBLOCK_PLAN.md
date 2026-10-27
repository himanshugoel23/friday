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

## F. Facts added 2026-10-28 (founder): proprietorship with GST
A proprietorship is legally the founder, so any provider or Meta may link the business to his restricted identity. Send this to each provider (B above) as the opening paragraph:
> My business is a proprietorship with GST. The owner's personal Facebook account has an old (Dec 2022) advertising restriction and my own Meta WhatsApp onboarding is blocked. I do not run ads. Can you onboard my GST-registered business to the WhatsApp Business Platform, with the WhatsApp business account hosted under your own Meta partner account, without requiring me to sign in to my own Meta account? Please answer in writing before I pay anything.
Documents to have ready (needed by most providers and by Meta business verification anyway): GST certificate, PAN, business address proof, a website or landing page on your own domain with a business email on that domain, a privacy policy page, a Grievance Officer name. Never paste numbers or documents into chat; upload only on a provider's own secure form after they confirm in writing.
Long-term clean option (ask a CA or lawyer, time and cost unknown): a separate legal entity (LLP or Pvt Ltd) with the co-founder as partner/director, set up by them with their own Meta account on their own device. Not a quick fix and not a way for the restricted owner to run Meta.

## G. Fact added 2026-10-28 (founder): the proprietorship is registered in his MOTHER's name
The legal owner of the GST business is therefore a different person. If she consents, this is the strongest legitimate route:
1. She is the Meta business owner: her own Facebook account, her own device, email and phone, her own two-step code. The founder never logs in as her and never holds her password.
2. She understands in plain words that Meta may link accounts (the GST contact email and phone are the founder's) and could restrict her personal Facebook too. Her decision.
3. A written authorization letter from her lets the founder run the product on her behalf (ask a CA for the wording). Ownership of the WhatsApp business account and number is stated in writing.
4. Be plain with providers and Meta: say the proprietor is a different person, that the founder operates it with her authorization, and that the founder's own account has an old ad restriction. Do not hide it.
5. Updated opening line for the provider message: "My business is a GST-registered proprietorship in my mother's name; I operate it on her behalf with her written authorization. My own personal Facebook account has an old (Dec 2022) advertising restriction. Can you onboard the business with the WhatsApp account hosted under your own Meta account, and what do you need from the proprietor? Please answer in writing before I pay."
Never put her details, GST or PAN numbers in chat or git.
