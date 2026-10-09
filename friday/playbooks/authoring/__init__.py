"""The script author: drafts a new playbook for a business type, OFFLINE (never during a call).

    knowledge.py / business_types.yaml   what we know about each business type
    prompt.py                            the model's instructions and the reply format
    offline.py                           deterministic template backend (default, no network)
    backends.py                          offline vs --live model, cost routing, budget
    author.py                            generate -> validate -> dry-run -> patch loop
    report.py, promote.py                founder report; confirmed copy into friday/playbooks/data

See docs/PLAYBOOKS.md ("Drafting a playbook for a new business type").
"""
