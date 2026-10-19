"""Consumer calls, workstream W1: the BEFORE and AFTER of a call placed for a user.

request -> understand -> brief -> approval -> safety gate -> schedule -> (W2 live call) -> report.
The live conversation is W2's (``friday.calls.interfaces.LiveCallEngine``). See docs/CALLS_W1.md.
The model only proposes; every safety rule here is plain code.
"""
