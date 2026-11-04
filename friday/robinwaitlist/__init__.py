"""Robin waitlist: a public 'about to launch' page that collects interest while the product is built.

Off by default (``FRIDAY_ROBIN_WAITLIST_ENABLED``). Honest copy only: Robin is not live, not an emergency service,
no testimonials or fake counts. Sign-ups are stored locally (var/robin_waitlist, 0600, encrypted lines when the
field cipher exists); the founder reads counts in the chat ('waitlist') or /ops-status/<token>/waitlist.
"""
