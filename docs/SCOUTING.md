# Scouting (roster agents 6-12): `friday/scouting/`

Finds the BEST vendors for a request, not only the nearest. Small single-job modules, typed pydantic in/out
(`models.py`). Code does everything deterministic; LLMs sit behind interfaces with closed schemas and code-side
verification. Raw review text lives in memory only; only scores and short reasons leave the package.

| Agent | Module | Notes |
|---|---|---|
| 5 (lite) query builder | `categories.py` | table lookup: Wave 1 categories, EN/Hinglish queries, expected Google types, service synonyms, radii |
| 6 place searcher | `searcher.py` | wraps `GooglePlacesDirectory` + `GoogleGeocoder` (not edited); wider field mask adds types and hours (same SKU tier as phone/rating); `FixturePlaceSearcher` replays recorded JSON through the same parser |
| 7 eligibility | `eligibility.py` | drops closed, no phone, toll-free, wrong type, outside radius, duplicates (same phone or same name core within 150 m), each with a reason |
| 8 review fetcher | `reviews.py` | Place Details `reviews` field only, max 5 per place, in memory |
| 9 authenticity | `authenticity.py` | rules: review bursts (>=3 within 48 h), duplicate/near-duplicate text, one-line generic praise, low-history reviewers, rating oddities. Optional `TextPatternJudge` (LLM) with closed flag codes; ids verified; failure never blocks |
| 10 evidence | `evidence.py` | `EvidenceLLM` interface returns closed JSON; code verifies review id exists, quote is literally in that review, label in closed vocabulary, price digits inside quote. Bad JSON: retry once then `status="unsure"`. `KeywordEvidenceLLM` is a deterministic stand-in used by the CLI |
| 11 fit | `fit.py` | service coverage (confirmed by quote = 1, unknown = 0.4), complaint themes, gender, budget, home visit |
| 12 ranker | `ranker.py` | Bayesian-smoothed rating (prior 4.2 x 50), genuineness blended to a neutral prior by confidence, fit, distance, open-now; weights 0.30/0.25/0.25/0.15/0.05 |
| wiring | `pipeline.py` | `scout(req, searcher, fetcher, evidence_llm=None, text_judge=None)`; pre-ranks without reviews and fetches reviews only for the best 8 |

## Distance rule (founder, hard filter)
Each category has `default_radius_km` and `max_radius_km` (salon/gym/florist/PG 5/10, clinic/lab/vet 8/15, restaurant 5/12,
home-service visits 10/20, movers/events/wedding/cab 20/40, coaching/driving 8/15, car service/electronics 8/15 are our pick).
`ScoutRequest.radius_km=None` means the default; the caller (project manager) may widen it, and `effective_radius_km` caps it at the hard
max. Beyond that nothing is shown. Inside the widened radius, places beyond the default are only used to fill leftover slots,
are flagged `beyond_default_radius` (`BEYOND_DEFAULT_RADIUS`) and the PM must ask the user first. The shortlist returns
`best_in_range`, `nearest_good`, `radius_km`, `default_radius_km`, `widened`, and every item carries `distance_km`.
Straight-line distance for now.

## Honest limits
- Places returns at most 5 reviews per place and NO reviewer history, so `author_review_count` is `None` live and that rule only fires when known; confidence is "low" under 3 reviews and the ranker leans on a neutral prior.
- Expected Google types per category are hypotheses; `friday scout-report` measures them.
- Fixtures (`friday/scouting/fixtures/`) are synthetic but shaped like Places responses (not real businesses).

## CLI
- `friday scout --category salon --area "Sector 56 Gurgaon" --services "haircut" --top 3 [--radius-km 8] [--fixtures]`: live Google when the key env var (`GOOGLE_PLACES_API_KEY`) exists, otherwise fixtures (says so). The key is never printed.
- `friday scout-report --categories all --areas "Sector 56 Gurgaon;Indiranagar Bangalore" [--max-queries 2]`: per category % with phone, % with hours, % with expected type, avg review count, calls made. Live only; without a key it skips and calls nothing. Cost: categories x areas x max-queries searches.

## What the quotes flow must call
```python
from friday.scouting.pipeline import scout
from friday.scouting.models import ScoutRequest
res = await scout(ScoutRequest(category="salon", area=..., near=GeoPoint|None, services=[...],
                               radius_km=None_or_widened, top_n=3),
                  GooglePlaceSearcher(directory, GeocoderAreaResolver(geocoder)), GoogleReviewFetcher(directory),
                  evidence_llm=<real EvidenceLLM or None>, text_judge=<optional>)
res.shortlist.items            # RankedItem: rank, place.candidate (phone, name), distance_km, reasons, flags
res.shortlist.best_in_range / nearest_good / widened
```
Use `items[i].place.candidate` to build CallTasks. If `len(items) < N` the PM may call again with a larger `radius_km` (capped by code) after asking the user when `beyond_default_radius` items appear. Agents 13 (explainer) can turn `reasons` into WhatsApp text.

## Live scout-report (2026-10-12, Sector 56 Gurgaon, 1 query per category, 20 results max)
Phone present 60-100% (lowest: pg_rental 60%, appliance_repair/pest_control/car_service/florist_gift 70%). Hours 70-100%.
**Type match is the weak spot**: our guessed Google types match only 0% pest_control, 0% driving_school, 5% coaching_classes, 10% appliance_repair, 20% event_services, 50% packers_movers/pg_rental/wedding_vendors. The eligibility filter would drop real vendors in these categories; fix the `types` lists in `categories.py` (inspect the real `types` of the results) before enabling them. Salon, clinic, lab, restaurant, gym, vet are fine (>= 95-100%).
Note: pest_control returned 10 and driving_school 5 places for one query (thin supply; add queries).

### Fix + re-measure (2026-10-12, same area, 2 queries per category)
Google gives several trades only the generic type "service", so `Category.name_keywords` now accepts a generic-typed place when its NAME carries a trade word, and a few observed types were added (electrician, general_contractor, transportation_service, makeup_artist, ...). Type match after the fix: appliance_repair 94%, pest_control 100%, home_repair 100%, coaching_classes 69%, driving_school 100%, event_services 70%, wedding_vendors 100%, packers_movers 100%, pg_rental 59% (phone only 56%: weakest category, expect fewer calls). Tests: tests/scouting/test_name_keywords.py.
