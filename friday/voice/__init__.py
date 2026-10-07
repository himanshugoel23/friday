"""Voice - telephony, STT/TTS, audio classification and the live call session.

Owner: Voice Engineer.

Implements (factory paths in core/container.py):
  simulator.py            build_simulated_telephony(c) - scripted/LLM businesses, IVR trees,
                          hold queues, busy/no-answer/voicemail, conference & transfer
  telephony/twilio.py     build_twilio(c)   (exotel.py / plivo.py stubs)
  stt/{fake,sarvam,deepgram}.py   build_*_stt(c)
  tts/{fake,sarvam,elevenlabs}.py build_*_tts(c)
  classifier.py           build_audio_classifier(c)  human / IVR / hold music / voicemail
  session.py              build_call_runner(c) -> CallSessionRunner
  http.py                 build_router(c) -> FastAPI APIRouter (provider webhooks, media WS);
                          mounted by friday/api under /voice
Designed for reuse by Phase-2 inbound calls (same runner, different CallBrief).
"""
