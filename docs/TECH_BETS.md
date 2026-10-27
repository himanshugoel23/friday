# Which AI technologies to deep dive on (2026-10-26)

Input: course titles the founder screenshotted (A2A, Chroma retrieval, JAX LLM, JetBrains local coding, LangGraph, Neo4j graph construction, Oracle agent memory and adaptive agents, Jamba long context, LlamaIndex agentic RAG, Qdrant on-device memory, AGI Inc browser agents). Only titles and blurbs were seen; nothing about the technologies is verified here. Test applied: does it change what the user feels (speed, being understood, things actually getting done) AND is it hard for a copycat to match?

## Deep dive (these change the product)
1. **Agent memory (Oracle memory-aware and adaptive agents, Qdrant on-device memory).** Moat: a memory that gets better the longer someone uses Friday (names, places, habits, past outcomes) is the one thing a new entrant cannot copy on day one. Today: structured life state plus the Speech Understander's name/place list. Gaps to study: what to store (facts vs episodes), consolidation and forgetting, learning from corrections ("nahi, Shriya nahi"), per-user isolation, delete-everything (DPDP). On-device angle is a trust story, not a pilot need.
2. **Browser agents (AGI Inc).** Moat is reliability on Indian sites plus the login vault: the long tail of sites that have no API. Already built (fakes only). Study: failure recovery, verification of each step, replay tests, when to hand over to the user. Gate: legal read per site.
3. **Voice speed and Indic speech quality (not on the list, but it is the experience).** Reply gap under 1 s, Hinglish accuracy on 8 kHz phone audio, barge-in. No course covers it; measure on real calls first.

## Study lightly (useful once the pilot shows the need)
4. **Retrieval (Chroma advanced retrieval, LlamaIndex agentic RAG).** Needed when memory is too big to hand over whole: pull the right 10 facts, rewrite the query, re-rank. Start with the database's own vector search; no new vendor.
5. **Knowledge graphs (Neo4j).** A graph of people, places and relations ("mummy", "Rahul bhaiya", "Shreya Salon") fits memory, but at pilot scale ordinary tables do the job. Revisit at thousands of users.
6. **Small-model tuning (not on the list).** The founder's own earlier ask. Distil the Speech Understander and intent routing into a small tuned model once the eval set and real transcripts exist; it cuts cost and latency.

## Watch, do not build now
7. **A2A (agent-to-agent protocol).** Only valuable when businesses run agents Friday can talk to. Most Indian vendors are not there; keep the quote flow protocol-neutral and revisit in a year.
8. **LangGraph.** A framework; Friday already has its own state machines with approvals. Borrow the ideas (checkpoint and resume, human-in-the-loop), do not adopt.

## Skip
9. **Training an LLM in JAX, Jamba long context, local AI coding workflows.** Pretraining is not our business; selecting the right memory beats stuffing a long context and costs less; coding workflows are for the builders, not the user.

## Next step if the founder agrees
Write a one-page design for item 1 (memory: what is stored, how it is corrected, how it is deleted, how the Speech Understander and chat read it) and measure item 3 on the first real calls.
