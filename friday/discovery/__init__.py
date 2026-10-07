"""Discovery - finding and vetting who to call. Read-mostly external data.

Owner: Backend Engineer (shortlisting judgement lives in friday/brain).

  simulator.py         build_simulated_directory(c), build_simulated_geocoder(c)
  google_places.py     build_google_places_directory(c) - Places API (New)
  google_geocoder.py   build_google_geocoder(c) - Geocoding API + maps-link resolution
  official_numbers.py  build_official_numbers(c) - curated customer-care numbers (data file)
  verify.py            build_number_verifier(c) - scam/fake-number check
  hotels/simulator.py  build_simulated_hotels(c)
  hotels/expedia.py    build_expedia_rapid(c) - Expedia Rapid (stub OK in Phase 1)
"""
