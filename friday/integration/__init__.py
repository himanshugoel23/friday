"""Consumer beta integration (W5): one WhatsApp conversation over the four built packages.

  bridge.py     W1 CallBrief/CallOutcome <-> W2 live engine; the LiveCallEngine W1 plugs in
  taskport.py   TaskPort over the task engine's durable queue + the periodic call jobs
  buttons.py    one registry for button ids (call:, led:, bill:, life:...)
  router.py     the front door: which handler gets a WhatsApp message (switches off = no change)
  proactive.py  bill reminders + life-state follow-ups as ProactiveEngine sources
  wiring.py     builds the whole stack from the Container (None while every switch is off)
  sim.py        offline callee personas for tests and `friday consumer demo`
  copy.py       the few lines that belong to the seams (PENDING_FOUNDER_APPROVAL)

See docs/CONSUMER_INTEGRATION.md. Nothing here dials a real number: without a telephony factory
the engine refuses to open a line.
"""
