# ruff: noqa: E501
"""Robin human operations desk (docs/ROBIN_CONCIERGE_DESK.md): lane 1 concierge errands, lane 2 emergency desk minimum.

Everything is behind ``FRIDAY_ROBIN_CONCIERGE_ENABLED`` (default OFF). Real adapters (masked-contact bridge, TOTP
verifier, staff directory, pager) are unbuilt [U]; the ports in ``ports.py`` have fakes and the tests use them.
"""
