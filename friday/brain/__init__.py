"""Brain - all language understanding & generation. Pure: no DB, no sending.

Owner: AI Engineer.

Implements (see friday/core/interfaces.py and the factory paths in core/container.py):
  llm.py          build_anthropic_llm(c)   -> LLMClient (Anthropic SDK)
  fake_llm.py     build_fake_llm(c)        -> deterministic LLMClient for tests/offline
  service.py      build_brain(c)           -> Brain (interpret, resolve_references,
                                              onboarding_turn, build_call_brief, shortlist,
                                              next_call_action, translate, summarize_call,
                                              compare_quotes, judge_nudge, template_for)
  extraction.py   build_document_extractor(c) -> DocumentExtractor (vision)
  templates/      BriefTemplate data per TaskType (YAML/JSON) - data, not code branches
  prompts/        persona + system prompts (Hinglish, tone, disclosure honesty, safety)
"""
