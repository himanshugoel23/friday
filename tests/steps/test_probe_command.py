# ruff: noqa: E501
"""The founder reads the site probe report in the chat ('browser status')."""

from __future__ import annotations


async def test_browser_status_command_is_founder_only_and_needs_the_probe_switch(media_world, tmp_path):
    from friday.sitemcp.probestore import ProbeStore

    w = await media_world(site_mcp_probe_enabled=True, site_mcp_dir=str(tmp_path))
    ProbeStore(tmp_path).save_live(
        {"site": "control", "kb_version": 1, "kb_status": "control", "overall": "ok", "items_found": 0, "priced": 0, "screenshot": False,
         "finished_at": "2026-10-30T07:00:00", "steps": [{"step": "open example.com", "status": "ok", "ms": 900, "detail": "http=200"}]}, None)
    st = w.c.settings
    st.admin_phones = []
    st.pilot_allowed_numbers = [w.user.phone]  # first allow-listed number = the founder
    out = [m.text or "" for m in await w.say("browser status")]
    assert any("control" in o and "open example.com" in o for o in out)
    st.pilot_allowed_numbers = ["+910000000000"]  # not the founder: the command is ignored (falls through to normal chat)
    out = [m.text or "" for m in await w.say("browser status")]
    assert not any("open example.com" in o for o in out)
