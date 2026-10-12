# Scope: vendor categories and request buckets (draft v1)

Source of categories: Justdial's own public annual search reports (self-reported; no scraping) plus our judgement of what a phone call can solve. Rankings below are a hypothesis to be replaced by our own request data after the beta.

## 1. Vendor categories (what people look for locally)
Justdial reports name: schools, restaurants, hospitals, beauty parlours, PG accommodation, hobby classes, dermatologists/dentists/ENT, packers and movers, pest control, AC repair, mobile dealers.

### Wave 1 (beta, 20 categories): high volume and a phone call really helps
1. Salon / parlour / spa (quote, book)
2. Doctors / dentists / dermatologists / clinics (appointment, fee, timings)
3. Diagnostic labs (test price, home collection slot)
4. AC repair / appliance repair (visit charge, visit slot)
5. Plumber / electrician / carpenter (visit charge, availability today)
6. Packers and movers (quote from several, comparison)
7. Pest control (quote per BHK)
8. Car service / garage / car wash (quote, slot)
9. Restaurants / banquet / caterers (table booking, availability, quote)
10. Coaching / hobby classes / schools (fees, demo class, admission enquiry)
11. PG / rental / real-estate enquiry (availability, rent, visit slot)
12. Mobile and electronics dealers (stock, price)
13. Gyms and yoga (membership price, trial)
14. Event services: photographer, decorator, DJ (quote, date availability)
15. Vets and pet grooming (appointment, price)
16. Wedding vendors: makeup, mehendi, planners (quote, date)
17. Driving schools (fees, batch timing)
18. Cab hire / travel agents (quote, availability)
19. Laundry / dry-clean / tailors (rate, pickup slot)
20. Florists and gift shops (price, same-day delivery)

### Wave 2 (next ~15): opticians, home cleaning, interior designers, CA/tax services, tutors, courier, insurance agents, water tanker / RO service, hospitals (department, bed enquiry), legal services, car rental, furniture shops, catering for home events, printing, security services.


## 2. Request buckets (what the user wants the agent to do)
The user speaks on WhatsApp; a classifier picks ONE bucket (plus a vendor category), and the bucket's agent runs the call. Unsure → ask one clarifying question on WhatsApp.

| # | Bucket | Example | Calls to | Output |
|---|--------|---------|----------|--------|
| 1 | Price quote | "haircut kitna lega?" | up to 3-5 vendors | comparison table |
| 2 | Availability check | "aaj shaam slot hai?" | 1-5 | yes/no + times |
| 3 | Book (delegated) | "book kar do, 5 baje, max 800" | 1 | confirmed booking (only with delegation) |
| 4 | Booking confirmation / reminder | "kal ki booking confirm karo" | 1 | confirmed / changed |
| 5 | Reschedule or cancel | "kal nahi, parso karo" | 1 | new slot / cancelled |
| 6 | Information enquiry | "timings, address, kya services?" | 1 | short answer |
| 7 | Service visit request | "AC thik karne aaj aa sakte ho?" | 1-3 | visit slot + visit charge |
| 8 | Follow-up / status | "mera order/repair ready hai?" | 1 | status |
| 9 | Complaint / escalation (later) | "service galat thi" | 1 | logged + reply (needs care) |
| 10 | Anything else | free-form | none | human-in-loop, wishlist capture |

Each (category x bucket) pair is a playbook; most are small variations of 4 archetypes: quote, availability/booking, service-visit, information. That is what the vendor archetype builder already covers.

## 3. Routing
1. WhatsApp text/voice → intent classifier (gpt-5.4-mini, closed set: bucket + category + slots such as when/where/budget/people).
2. Missing slots asked on WhatsApp (max 2 questions).
3. Bucket agent runs the call playbook; outcomes return to WhatsApp (and SMS fallback).
4. Unmapped request → bucket 10 and we store it for the wishlist, which drives which playbooks to build next.

## 4. Open decisions for the founder
- Is the 20-category Wave 1 right, or should some be swapped?
- Beta calls live for salon + 2-3 more first (suggest: salon, clinic, AC/plumber); the other categories are built and tested but enabled one by one.
- Bucket 3/4/5 (booking changes) only with explicit delegation; OK?
- Complaints stay out of the beta; OK?
