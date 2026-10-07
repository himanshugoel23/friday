"""Voice - telephony, STT/TTS, audio classification and the live call session.

Owner: Voice Engineer.

Factories (core/container.py FACTORIES):
  simulator.py            build_simulated_telephony(c) - simworld personas, IVR trees, hold
                          queues, conference, inbound call-backs / missed calls, alt numbers
  telephony/twilio.py     build_twilio(c)  - Media Streams, conference bridge (international)
  telephony/exotel.py     build_exotel(c)  - Voicebot stream, transfer bridge (India fallback)
  telephony/sarvam.py     build_sarvam_telephony(c) - Vobiz/Sarvam media stream (India primary;
                          not yet in FACTORIES - see docs/CORE_CHANGES.md)
  telephony/routing.py    RoutedTelephony: Sarvam > Exotel > Twilio, per-call capability fallback
  telephony/plivo.py      stub
  stt/{fake,sarvam,deepgram}.py   build_*_stt(c)
  tts/{fake,sarvam,elevenlabs}.py build_*_tts(c);  tts/cache.py pre-rendered fixed lines
  classifier.py           build_audio_classifier(c)  human / IVR / hold music / voicemail
  session.py              build_call_runner(c) -> CallRunner (run, run_inbound, cancel)
  http.py                 build_router(c) -> APIRouter (Twilio/Exotel/Sarvam webhooks + media WS,
                          /sim helpers); mounted by friday/api under /voice
Helpers: voicenote.py (WhatsApp OGG -> STT), events.py (inbound/missed/cost/latency events),
callerid.py (sticky caller ID), audio.py, text.py, latency.py.
"""
