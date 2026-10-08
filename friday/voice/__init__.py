"""Voice - telephony, STT/TTS, audio classification and the live call session.

Owner: Voice Engineer.

Factories (core/container.py FACTORIES):
  simulator.py            build_simulated_telephony(c) - simworld personas, IVR trees, hold
                          queues, conference, inbound call-backs / missed calls, alt numbers
  telephony/twilio.py     build_twilio(c)  - Media Streams, conference bridge (disabled by default)
  telephony/exotel.py     build_exotel(c)  - Voicebot stream, transfer bridge (disabled by default)
  telephony/sarvam.py     build_sarvam_telephony(c) - THE live provider (Sarvam only for now;
                          capability matrix + degrade paths in its docstring)
  telephony/routing.py    RoutedTelephony (explicit opt-in); default route = Sarvam only
  worker.py               VoiceWorker: claims call.place jobs with capacity, call pinning,
                          lease heartbeat, graceful drain (S-9)
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
