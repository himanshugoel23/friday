"""Understanding photos and documents the user sends on WhatsApp (docs/DOCUMENT_UNDERSTANDING.md).

Bytes are processed in memory and discarded. Only minimal extracted fields are kept, and only
after the user says "sahi hai". Document text is untrusted data: it can never become an
instruction (this package has no access to tasks, calls or the brain).
"""
