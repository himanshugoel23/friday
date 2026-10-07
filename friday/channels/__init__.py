"""Channels - how Friday talks to users, circle members and businesses.

Owner: Backend Engineer.

  whatsapp.py   build_whatsapp_channel(c) - WhatsApp Cloud API: send text/buttons/
                templates/media, fetch_media, webhook parsing + signature verification
  simulator.py  build_simulator_channel(c) - local chat channel (CLI / HTTP)
  sms.py        build_fake_sms(c), build_msg91_sms(c) - DLT template SMS
  notifier.py   build_notifier(c) - picks channel, enforces 24h window -> template,
                beneficiary opt-in, quiet hours for non-urgent, logs every message
"""
