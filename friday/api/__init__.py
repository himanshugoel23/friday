"""HTTP API - FastAPI app, provider webhooks, health, simulator endpoints.

Owner: Backend Engineer.

  app.py  create_app(container=None) -> FastAPI: lifespan builds the Container,
          /health, /webhooks/whatsapp (GET verify + POST), /sim/* (simulator chat),
          mounts the voice router (container.get("voice_router")) at /voice if available.
"""
