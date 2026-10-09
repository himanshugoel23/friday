"""Playbooks: deterministic, script-following outbound calls, one data file per business type.

    friday/playbooks/data/<name>.yaml     the script (fixed Hinglish lines + a state machine)
    friday/playbooks/model.py             file format, loader, validator
    friday/playbooks/engine.py            CallPolicy that walks a playbook (no model-written words)
    friday/playbooks/understand.py        the ONE model use: classify the other side's reply
    friday/playbooks/dryrun.py            simulated personas, scoring, baseline
    friday playbook list | validate <name> | dry-run <name>      (friday/playbooks/cli.py)

See docs/PLAYBOOKS.md.
"""

from friday.playbooks.model import (
    Playbook,
    PlaybookError,
    get_playbook,
    list_playbooks,
    load_playbook,
    validate_data,
)

__all__ = [
    "Playbook",
    "PlaybookError",
    "get_playbook",
    "list_playbooks",
    "load_playbook",
    "validate_data",
]
