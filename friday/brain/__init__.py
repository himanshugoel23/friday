"""Brain - all language understanding & generation. Pure: no DB, no sending.

Owner: AI Engineer.

Factories (core/container.py):
  llm.py          build_anthropic_llm(c)      -> AnthropicLLM (structured outputs, prompt caching,
                                                 batches, per-purpose token/cache/INR logging)
  fake_llm.py     build_fake_llm(c)           -> FakeLLM (deterministic, keyed on purpose)
  service.py      build_brain(c)              -> FridayBrain (Brain + CallPolicy + Translator)
  extraction.py   build_document_extractor(c) -> LLMDocumentExtractor (vision + batch path)

Modules:
  prompts/        persona (female, honest AI, safety) + per-purpose system prompts
  templates/      BriefTemplate JSON per TaskType (data, not code)
  schemas.py      wire models for structured outputs (+ strict_schema)
  heuristics/     deterministic implementation of every purpose (fake LLM + fallback)
  handlers.py     purpose -> heuristic, shared by the fake LLM and the fallback path
  briefs.py       build_call_brief / build_inbound_brief (minimum disclosure)
  guards.py       hard rules on every call action (approval, delegation, money, safety)
  inbound.py      call-back / missed-call context (BRIEF E-30..37)
  ivr.py          learned IVR maps (replay without LLM)
  routing.py      model routing per purpose, token budgets (cost rule)
  reports.py      summaries, comparisons, shortlist ranking
  sim_business.py AI-13 simulated business replies (for the voice simulator)
"""
