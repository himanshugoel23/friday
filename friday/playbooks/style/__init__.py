"""The founder's script style: a dictionary that grows with every correction he gives.

Not machine learning: a small, readable rules-and-examples file (``style.yaml``) plus a log of his
corrections (``learned.yaml``). It checks and drafts; it never edits a live playbook by itself
(hear-before-change still applies).
"""

from friday.playbooks.style.core import (  # noqa: F401
    Issue,
    StyleBook,
    autofix,
    learn,
    lint_line,
    lint_playbook,
    load_style,
)
