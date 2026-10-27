"""The WhatsApp chatbot pilot: first-run onboarding, menu and help, capture, off-topic redirect.

``ChatbotService`` is built by the inbound pipeline only when ``FRIDAY_CHATBOT_ONBOARDING`` is on
(otherwise ``pipeline.chatbot`` is None and nothing here runs). Three hooks:

* ``handle_unknown(msg)``: a first message from a number we do not know. Pilot gate (waitlist),
  then ONE intro with consent buttons. Nothing is stored about the person until they agree, except
  a row keyed by a hash of the number (the step they are on); a refusal stores only that refusal.
  Replies before consent are sent straight to the channel and are not logged.
* ``pre(user, msg)``: before the consumer router. Buttons of this flow (``cb:``), the commands
  (menu, human, stop, delete everything), the answer to a pending question (a nickname, a place
  label), a shared contact card, a location pin and the answer to the current onboarding step.
* ``post(user, msg)``: after every other handler and before the brain. A typed phone number becomes
  a contact; a clear general-knowledge question gets the polite redirect and is kept for the
  founder's review.

Every message goes through :class:`friday.chatbot.composer.Composer` (length, one question, buttons,
no repeats, the plain statement). Every word is in ``friday/chatbot/copy.py`` (pending approval).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from friday.chatbot import commands as cmd
from friday.chatbot import copy, guards, templates
from friday.chatbot.composer import Composed, Composer, buttons_for, mirror_language
from friday.chatbot.parity import hooks as parity_hooks
from friday.chatbot.parity.invites import InviteLedger
from friday.chatbot.scope import is_out_of_scope, mask_numbers
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    AutonomyCategory,
    Channel,
    Consent,
    ConsentKind,
    GeoPoint,
    InboundMessage,
    Language,
    ListMenu,
    ListRow,
    LocationPin,
    MessageKind,
    OnboardingStep,
    OutboundMessage,
    Place,
    ReplyButton,
    User,
    UserStatus,
    normalize_phone,
)
from friday.db.repositories._base import phone_index
from friday.db.repositories.chatbot import Session

if TYPE_CHECKING:
    from friday.api.inbound import InboundPipeline

log = get_logger(__name__)

RESUME_AFTER = timedelta(hours=6)  # a person who comes back after this gets a "welcome back"
PENDING_TTL = timedelta(minutes=30)  # an unanswered nickname / place question is dropped
REFUSAL_COOLDOWN = timedelta(hours=1)  # after "Nahi", only a greeting restarts the intro sooner
MAX_FAILS = 2  # a step the person cannot or will not answer is skipped after this many tries

STEPS = ("consent", "name", "language", "city", "win", "done")
BUTTON_PREFIX = "cb:"

_LANG_ENUM = {"hinglish": Language.HINGLISH, "hi": Language.HI, "en": Language.EN}
_CATEGORIES = list(AutonomyCategory)


class _Ctx:
    """Who we are talking to in one turn."""

    def __init__(self, phone: str, lang: str, user: User | None, sess: Session | None) -> None:
        self.phone, self.lang, self.user, self.sess = phone, lang, user, sess


class ChatbotService:
    def __init__(self, pipeline: InboundPipeline) -> None:
        self.p = pipeline
        self.settings = pipeline.settings
        self.clock = pipeline.clock
        self.composer = Composer(strict=self.settings.env == "test")
        self._invites = InviteLedger()  # in memory until a table exists (docs/INSTINCT_PARITY.md)

    # ========== small helpers
    @property
    def repo(self) -> Any:
        return self.p.repos.chatbot

    def _parity_on(self) -> bool:
        s = self.settings
        return bool(s.parity_invites or s.parity_ride_links or s.parity_inr_only)

    def _now(self) -> datetime:
        return self.clock.now()

    def _allowlist(self) -> set[str]:
        s = self.settings
        out: set[str] = set()
        for raw in [*s.pilot_allowed_numbers, *s.chatbot_testers, *s.admin_phones]:
            try:
                out.add(normalize_phone(raw, s.default_country_code))
            except ValueError:
                continue
        return out

    def gate(self, phone: str) -> str:
        """ "open" (may onboard here), "waitlist" (pilot is on and the number is not a tester) or
        "old" (leave this number to the invite-code onboarding)."""
        s = self.settings
        if phone in self._allowlist():
            return "open"
        if s.pilot:
            return "waitlist"
        return "old" if s.invite_only else "open"

    def _features(self) -> dict[str, bool]:
        s = self.settings
        return {
            "call": s.consumer_calls_enabled,
            "card": s.savings_enabled,
            "day": s.lifestate_enabled,
        }

    def _wins(self) -> list[str]:
        on = self._features()
        order = [w for w in self.settings.chatbot_first_wins if w in on]
        return [w for w in order if on[w]][:3]

    async def _lang_of(self, user: User, sess: Session | None) -> str:
        profile = await self.p.repos.profiles.get_or_default(user.id)
        code = getattr(profile.language, "value", str(profile.language))
        if code in copy.LANGUAGES:
            return code
        return sess.lang if sess and sess.lang in copy.LANGUAGES else copy.DEFAULT_LANGUAGE

    async def _session(self, user: User, lang: str) -> Session:
        """The user's chatbot session; one is created (already done) for people who never went
        through this onboarding, so a pending question has somewhere to live."""
        sess = await self.repo.session_for_user(user.id)
        if sess is None:
            sess = Session(
                phone_hash=phone_index(user.phone), step="done", lang=lang, step_at=self._now(),
                user_id=user.id,
            )  # fmt: skip
            await self.repo.save_session(sess)
        return sess

    # ------------------------------------------------------------------ sending
    async def _send(
        self,
        ctx: _Ctx,
        text: str,
        *,
        buttons: list[ReplyButton] | None = None,
        menu: ListMenu | None = None,
        kind: str = "default",
        alt: str | None = None,
        dedupe: bool = False,
        step: bool = False,
    ) -> bool:
        footer = (
            copy.line("footer_short", ctx.lang)
            if step and self.settings.chatbot_disclosure_every_step
            else None
        )
        comp = self.composer.compose(
            text, buttons=buttons or [], list_menu=menu, kind=kind, lang=ctx.lang,
            last_digest=ctx.sess.last_hash if (dedupe and ctx.sess) else None, alt=alt,
            footer=footer,
        )  # fmt: skip
        if comp is None:
            return False
        ok = await self._deliver(ctx, comp)
        if ctx.sess is not None:
            ctx.sess.last_hash = comp.digest
        return ok

    async def _deliver(self, ctx: _Ctx, comp: Composed) -> bool:
        if ctx.user is not None:
            messaging = self.p._opt("messaging")
            out = OutboundMessage(
                channel=messaging.channel if messaging else Channel.WHATSAPP,
                to_phone=ctx.user.phone, user_id=ctx.user.id, text=comp.text,
                buttons=comp.buttons, list_menu=comp.list_menu,
            )  # fmt: skip
            receipt = await self.p.notifier.send(out)
            return bool(receipt.ok)
        # before consent there is no user: send straight to the channel and do not log it
        messaging = self.p._opt("messaging")
        if messaging is None:
            return False
        out = OutboundMessage(
            channel=messaging.channel, to_phone=ctx.phone, text=comp.text, buttons=comp.buttons,
            list_menu=comp.list_menu,
        )  # fmt: skip
        try:
            receipt = await messaging.send(out)
        except Exception as e:  # noqa: BLE001 - a send failure never breaks the webhook
            log.warning("chatbot send to %s failed: %s", mask_phone(ctx.phone), type(e).__name__)
            return False
        return bool(receipt.ok)

    async def _save(self, ctx: _Ctx) -> None:
        if ctx.sess is not None:
            await self.repo.save_session(ctx.sess)

    @staticmethod
    def _consent_buttons(lang: str, *, details: bool = True) -> list[ReplyButton]:
        pairs = [("cb:consent:yes", copy.button("consent_yes", lang))]
        if details:
            pairs.append(("cb:consent:details", copy.button("consent_details", lang)))
        pairs.append(("cb:consent:no", copy.button("consent_no", lang)))
        return buttons_for(*pairs)

    # ========== 1. unknown numbers
    async def handle_unknown(self, msg: InboundMessage) -> bool:
        """True when this service took the message (the invite-code onboarding must not run)."""
        if msg.kind == MessageKind.SYSTEM:
            return False
        phone = msg.from_phone
        gate = self.gate(phone)
        if gate == "old":
            return False
        if gate == "waitlist":
            await self._waitlist(msg)
            return True
        now = self._now()
        text = (msg.text or "").strip()
        sess = await self.repo.session_for_phone(phone)
        if sess is not None and sess.user_id:
            # the user it belonged to is gone (erased): start again from nothing
            await self.repo.delete_session(sess.phone_hash)
            sess = None
        if sess is None:
            lang = mirror_language(text, copy.DEFAULT_LANGUAGE)
            sess = Session(phone_hash=phone_index(phone), step="consent", lang=lang, step_at=now)
            await self._intro(_Ctx(phone, lang, None, sess))
            return True
        ctx = _Ctx(phone, sess.lang, None, sess)
        if sess.step == "refused":
            quiet = sess.refused_at is not None and now - sess.refused_at < REFUSAL_COOLDOWN
            if quiet and not cmd.GREETING.match(text):
                return True  # they said no a moment ago: stay quiet
            sess.step, sess.refused_at, sess.step_at = "consent", None, now
            await self._intro(ctx)
            return True
        choice = self._consent_choice(msg)
        if choice == "yes":
            await self._grant_consent(ctx, msg)
        elif choice == "no":
            await self._refuse(ctx)
        elif choice == "details":
            await self._send(
                ctx,
                copy.line("details", ctx.lang),
                buttons=self._consent_buttons(ctx.lang, details=False),
                kind=copy.kind_of("details"),
                dedupe=True,
                alt=copy.line("consent_reprompt", ctx.lang),
            )
            await self._save(ctx)
        else:
            await self._intro(ctx, dedupe=True)
        return True

    async def _waitlist(self, msg: InboundMessage) -> None:
        new = await self.repo.waitlist_add(msg.from_phone)
        if not new:
            return  # one polite reply, then silence
        lang = mirror_language(msg.text, copy.DEFAULT_LANGUAGE)
        await self._send(
            _Ctx(msg.from_phone, lang, None, None), copy.line("waitlist", lang),
            kind=copy.kind_of("waitlist"),
        )  # fmt: skip

    async def _intro(self, ctx: _Ctx, *, dedupe: bool = False) -> None:
        await self._send(
            ctx, copy.line("intro", ctx.lang), buttons=self._consent_buttons(ctx.lang),
            kind=copy.kind_of("intro"), dedupe=dedupe,
            alt=copy.line("consent_reprompt", ctx.lang),
        )  # fmt: skip
        await self._save(ctx)

    @staticmethod
    def _consent_choice(msg: InboundMessage) -> str | None:
        if msg.kind == MessageKind.BUTTON_REPLY and msg.button_id:
            return {
                "cb:consent:yes": "yes", "cb:consent:no": "no", "cb:consent:details": "details",
            }.get(msg.button_id)  # fmt: skip
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return None
        t = cmd.norm(msg.text)
        if cmd.YES.match(t):
            return "yes"
        if cmd.NO.match(t):
            return "no"
        if cmd.DETAILS.match(t):
            return "details"
        return None

    async def _refuse(self, ctx: _Ctx) -> None:
        sess = ctx.sess
        assert sess is not None
        now = self._now()
        sess.step, sess.refused_at, sess.step_at = "refused", now, now
        sess.pending, sess.pending_kind = {}, None
        await self._send(ctx, copy.line("refused", ctx.lang))
        sess.last_hash = None
        await self._save(ctx)

    async def _grant_consent(self, ctx: _Ctx, msg: InboundMessage) -> None:
        """Consent given: create the user, record the consent, ask the first question."""
        sess = ctx.sess
        assert sess is not None
        now = self._now()
        user = User(
            phone=msg.from_phone, status=UserStatus.ACTIVE, onboarding_step=OnboardingStep.DONE,
            invites_remaining=0, created_at=now, updated_at=now, last_inbound_at=msg.received_at,
        )  # fmt: skip
        await self.p.repos.users.add(user)
        msg.user_id = user.id
        await self.p.audit("user.created", user, via="chatbot")
        via = f"button {msg.button_id}" if msg.button_id else "typed"
        evidence = (
            f"{via}: {(msg.text or '')[:80]} | lang={sess.lang} | wording={copy.WORDING_VERSION}"
        )
        await self.p.repos.consents.add(
            Consent(
                user_id=user.id,
                kind=ConsentKind.TERMS_PRIVACY,
                granted=True,
                policy_version=copy.WORDING_VERSION,
                evidence_text=evidence[:500],
                message_id=msg.id,
                recorded_at=now,
            )  # fmt: skip
        )
        await self.p.audit(
            "consent.granted", user, kind=ConsentKind.TERMS_PRIVACY.value,
            wording=copy.WORDING_VERSION, language=sess.lang, via="chatbot",
        )  # fmt: skip
        await self.p._log_inbound(user, msg, redact=False)
        await self.p.apply_profile_updates(user, {"language": _LANG_ENUM[sess.lang]})
        sess.user_id, sess.step, sess.step_at, sess.refused_at = user.id, "name", now, None
        ctx.user = user
        await self._prompt(ctx, "name")

    # ========== 2. known users, before the router
    async def pre(self, user: User, msg: InboundMessage) -> bool:
        if user.status != UserStatus.ACTIVE:
            return False
        sess = await self.repo.session_for_user(user.id)
        if msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith(BUTTON_PREFIX):
            lang = await self._lang_of(user, sess)
            return await self._button(_Ctx(user.phone, lang, user, sess), msg)
        if msg.kind == MessageKind.BUTTON_REPLY and not msg.button_id:
            # a tap on a template quick reply: the channel does not carry its payload yet, so the
            # title says what it means (friday/chatbot/templates.py button_action)
            action = templates.button_action(None, msg.text)
            if action is not None:
                lang = await self._lang_of(user, sess)
                return await self._template_action(_Ctx(user.phone, lang, user, sess), action)
        if msg.kind == MessageKind.CONTACT:
            lang = await self._lang_of(user, sess)
            return await self._contact_card(_Ctx(user.phone, lang, user, sess), msg)
        if msg.kind == MessageKind.LOCATION and msg.location is not None:
            lang = await self._lang_of(user, sess)
            return await self._location_pin(_Ctx(user.phone, lang, user, sess), msg)
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        t = cmd.norm(text)
        lang = await self._lang_of(user, sess)
        ctx = _Ctx(user.phone, lang, user, sess)
        if self.settings.chatbot_guards and await self._guards(ctx, text):
            return True
        if self._parity_on() and (reply := parity_hooks.text_reply(
                self.settings, self._invites, user.id, text, lang)) is not None:
            await self._send(ctx, reply)
            return True
        if (reply := await self._memory_chat(ctx, text)) is not None:
            await self._send(ctx, reply, kind="list")
            return True
        if cmd.MENU.match(t):
            return await self._menu(ctx)
        if (m := cmd.HUMAN.match(t)) is not None:
            return await self._human(ctx, (m.group("rest") or "").strip())
        if cmd.STOP.match(t) and not await self._quotes_busy(user):
            return await self._stop(ctx)
        if cmd.RESUME.match(t) and await self._paused(user):
            return await self._resume(ctx)
        if cmd.DELETE_ALL.match(t):
            return await self._delete(ctx)
        pending = sess is not None and sess.pending_kind and self._pending_fresh(sess)
        if pending and await self._pending_answer(ctx, msg):
            return True
        if sess is not None and sess.step in ("name", "language", "city", "win"):
            return await self._step_answer(ctx, msg)
        return False

    async def _guards(self, ctx: _Ctx, text: str) -> bool:
        """Fixed lines for an emergency, a medicine ask or a fake-bill ask, and "reply in Hindi"
        (docs/CHATBOT_PERSONA.md appendix C). Runs before any flow so a real emergency is never
        swallowed by a pending question."""
        kind = guards.safety_kind(text)
        if kind is not None:
            await self._send(ctx, copy.line(
                {"emergency": "safety_emergency", "medicine": "safety_medicine",
                 "forgery": "refuse_forgery"}[kind], ctx.lang))
            return True
        code = guards.language_request(text)
        if code is not None and ctx.user is not None:
            await self.p.apply_profile_updates(ctx.user, {"language": _LANG_ENUM[code]})
            sess = ctx.sess or await self._session(ctx.user, code)
            sess.lang = ctx.lang = code
            ctx.sess = sess
            await self._save(ctx)
            await self._send(ctx, copy.line("lang_set", code, language=copy.LANGUAGE_NAMES[code]))
            return True
        return False

    async def _memory_chat(self, ctx: _Ctx, text: str) -> str | None:
        """"What do you remember about me" and "forget <item>" (friday/memory/chat.py)."""
        if ctx.user is None:
            return None
        from friday.memory import chat as memory_chat

        try:
            return await memory_chat.handle(self.p.repos, self.p.clock, ctx.user.id, text, ctx.lang)
        except Exception:  # noqa: BLE001 - never block a message on the memory list
            return None

    async def _quotes_busy(self, user: User) -> bool:
        try:
            return await self.p.quotes.store.active_for_user(user.id) is not None
        except Exception:  # noqa: BLE001
            return False

    def _pending_fresh(self, sess: Session) -> bool:
        try:
            at = datetime.fromisoformat(str(sess.pending.get("at")))
        except ValueError:
            return False
        return self._now() - at < PENDING_TTL

    # ========== onboarding steps
    async def _prompt(
        self, ctx: _Ctx, step: str, *, prefix: list[str] | None = None, dedupe: bool = False
    ) -> None:
        """Ask the question of ``step`` (after the ``prefix`` lines) and persist the step."""
        sess = ctx.sess
        assert sess is not None
        lang = ctx.lang
        parts = list(prefix or [])
        buttons: list[ReplyButton] = []
        if step == "name":
            parts.append(copy.line("ask_name", lang))
            buttons = buttons_for(("cb:skip", copy.button("skip", lang)))
            alt = copy.line("reprompt_name", lang)
        elif step == "language":
            parts.append(copy.line("ask_language", lang, current=copy.LANGUAGE_NAMES[lang]))
            buttons = buttons_for(
                ("cb:lang:hinglish", copy.button("lang_hinglish", lang)),
                ("cb:lang:hi", copy.button("lang_hi", lang)),
                ("cb:lang:en", copy.button("lang_en", lang)),
            )
            alt = copy.line("reprompt_language", lang)
        elif step == "city":
            parts.append(copy.line("ask_city", lang))
            buttons = buttons_for(("cb:skip", copy.button("skip", lang)))
            alt = copy.line("reprompt_city", lang)
        elif step == "win":
            wins = self._wins()
            if not wins:
                await self._finish(ctx, prefix=parts)
                return
            parts.append(copy.line("ask_win", lang))
            buttons = buttons_for(*[(f"cb:win:{w}", copy.button(f"win_{w}", lang)) for w in wins])
            alt = copy.line("reprompt_win", lang)
        else:
            raise ValueError(step)
        sess.step, sess.step_at = step, self._now()
        await self._send(ctx, "\n".join(parts), buttons=buttons, dedupe=dedupe, alt=alt, step=True)
        await self._save(ctx)

    async def _finish(self, ctx: _Ctx, *, prefix: list[str] | None = None) -> None:
        sess = ctx.sess
        assert sess is not None
        sess.step, sess.step_at, sess.pending = "done", self._now(), {}
        # the closing message is the plain statement; a prefix would push it past the cap, so it
        # is sent on its own when there is one
        if prefix:
            await self._send(ctx, "\n".join(prefix))
        await self._send(ctx, copy.line("done", ctx.lang), kind=copy.kind_of("done"))
        await self.p.audit("onboarding_completed", ctx.user, via="chatbot")
        await self._save(ctx)

    async def _advance(self, ctx: _Ctx, from_step: str, prefix: list[str]) -> None:
        nxt = STEPS[STEPS.index(from_step) + 1]
        if not ctx.sess.pending_kind:  # type: ignore[union-attr]
            ctx.sess.pending = {}  # type: ignore[union-attr]
        if nxt == "done":
            await self._finish(ctx, prefix=prefix)
        else:
            await self._prompt(ctx, nxt, prefix=prefix)

    async def _step_answer(self, ctx: _Ctx, msg: InboundMessage) -> bool:
        """The message is (maybe) the answer to the current question. True == consumed."""
        sess, user = ctx.sess, ctx.user
        assert sess is not None and user is not None
        step, lang, text = sess.step, ctx.lang, (msg.text or "").strip()
        t = cmd.norm(text)
        skipped = bool(cmd.SKIP.match(t))
        if step == "name":
            name = None if skipped else cmd.parse_name(text)
            if skipped or name:
                if name:
                    await self.p.apply_profile_updates(user, {"name": name})
                ack = (
                    copy.line("ack_name", lang, name=name)
                    if name
                    else copy.line("ack_name_skip", lang)
                )
                await self._advance(ctx, "name", [ack])
                return True
        elif step == "language":
            code = None if skipped else cmd.parse_language(text)
            if skipped or code:
                prefix: list[str] = []
                if code:
                    await self.p.apply_profile_updates(user, {"language": _LANG_ENUM[code]})
                    sess.lang = ctx.lang = code
                    prefix = [copy.line("ack_language", code, language=copy.LANGUAGE_NAMES[code])]
                await self._advance(ctx, "language", prefix)
                return True
        elif step == "city":
            city = None if skipped else cmd.parse_city(text)
            if skipped or city:
                if city:
                    await self.p.apply_profile_updates(user, {"city": city})
                ack = (
                    copy.line("ack_city", lang, city=city)
                    if city
                    else copy.line("ack_city_skip", lang)
                )
                await self._advance(ctx, "city", [ack])
                return True
        elif step == "win":
            win = cmd.parse_win(text)
            if win:
                await self._run_win(ctx, win)
                return True
            if skipped:
                await self._finish(ctx)
                return True
            if cmd.GREETING.match(t):
                await self._reprompt(ctx, step)
                return True
            # anything else is a real request: onboarding is complete, the router gets the message
            await self._finish_quietly(ctx)
            return False
        # not an answer
        if self._looks_like_request(text):
            return False  # the router / brain answers it; the question stays open
        return await self._invalid(ctx, step)

    @staticmethod
    def _looks_like_request(text: str) -> bool:
        return cmd._REQUESTISH.search(text) is not None or len(text.split()) > 6  # noqa: SLF001

    async def _invalid(self, ctx: _Ctx, step: str) -> bool:
        sess = ctx.sess
        assert sess is not None
        fails = int(sess.pending.get("fails", 0)) + 1
        if fails >= MAX_FAILS:
            sess.pending = {}
            await self._advance(ctx, step, [])  # skip what they cannot or will not answer
            return True
        sess.pending = {"fails": fails}
        await self._reprompt(ctx, step)
        return True

    async def _reprompt(self, ctx: _Ctx, step: str) -> None:
        sess = ctx.sess
        assert sess is not None
        prefix = (
            [copy.line("resume_prefix", ctx.lang)]
            if self._now() - sess.step_at > RESUME_AFTER
            else []
        )
        await self._prompt(ctx, step, prefix=prefix, dedupe=True)

    async def _finish_quietly(self, ctx: _Ctx) -> None:
        sess = ctx.sess
        assert sess is not None
        sess.step, sess.step_at, sess.pending = "done", self._now(), {}
        await self.p.audit("onboarding_completed", ctx.user, via="chatbot")
        await self._save(ctx)

    async def _run_win(self, ctx: _Ctx, win: str) -> None:
        on = self._features().get(win, False)
        await self._send(ctx, copy.line(f"win_{win}" if on else "win_soon", ctx.lang))
        await self._finish(ctx)

    # ========== buttons
    async def _button(self, ctx: _Ctx, msg: InboundMessage) -> bool:
        parts = (msg.button_id or "").split(":")
        group = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        sess = ctx.sess
        if group == "consent":
            # a tap from the "agree again" template (the first consent was given long ago)
            action = {"yes": "consent_yes", "no": "consent_no", "details": "details"}.get(value)
            return await self._template_action(ctx, action) if action else True
        if group == "tpl":
            return await self._template_action(ctx, value)
        if group == "menu":
            return await self._menu_pick(ctx, value)
        if group == "skip":
            return await self._skip(ctx)
        if group == "lang":
            if sess is not None and sess.step == "language" and value in copy.LANGUAGES:
                word = {"hinglish": "hinglish", "hi": "hindi", "en": "english"}[value]
                return await self._step_answer(ctx, msg.model_copy(update={"text": word}))
            return True
        if group == "win":
            if sess is not None and sess.step == "win" and value in self._features():
                await self._run_win(ctx, value)
            return True
        if group in ("nick", "place"):
            if sess is not None and sess.pending_kind and self._pending_fresh(sess):
                title = {"mummy": "mummy", "papa": "papa", "home": "ghar", "office": "office"}.get(
                    value, value
                )
                return await self._pending_answer(ctx, msg.model_copy(update={"text": title}))
            return True
        return True

    async def _template_action(self, ctx: _Ctx, action: str) -> bool:
        """What a tap on a button of an outside-the-window template means."""
        user = ctx.user
        assert user is not None
        if action == "stop":
            return await self._stop(ctx)
        if action == "human":
            return await self._human(ctx, "")
        if action == "details":
            await self._send(
                ctx,
                copy.line("details", ctx.lang),
                buttons=self._consent_buttons(ctx.lang, details=False),
                kind=copy.kind_of("details"),
            )
            return True
        if action in ("consent_yes", "consent_no"):
            granted = action == "consent_yes"
            await self.p.repos.consents.add(
                Consent(
                    user_id=user.id,
                    kind=ConsentKind.TERMS_PRIVACY,
                    granted=granted,
                    policy_version=copy.WORDING_VERSION,
                    evidence_text=f"template re-request: {'yes' if granted else 'no'}",
                    recorded_at=self._now(),
                )
            )
            await self.p.audit(
                "consent.renewed" if granted else "consent.withdrawn",
                user,
                kind=ConsentKind.TERMS_PRIVACY.value,
                wording=copy.WORDING_VERSION,
                via="chatbot",
            )
            if not granted and not await self._paused(user):
                await self._set_proactive(user, False, "consent withdrawn")
            await self._send(
                ctx, copy.line("consent_renewed" if granted else "consent_withdrawn", ctx.lang)
            )
            return True
        return True  # "ok": the tap opened the window, nothing to say

    async def _skip(self, ctx: _Ctx) -> bool:
        sess = ctx.sess
        if sess is None:
            return True
        if sess.pending_kind and self._pending_fresh(sess):
            return await self._pending_answer(ctx, InboundMessage(
                channel=Channel.WHATSAPP, from_phone=ctx.phone, text="skip"))  # fmt: skip
        if sess.step in ("name", "language", "city"):
            fake = InboundMessage(channel=Channel.WHATSAPP, from_phone=ctx.phone, text="skip")
            return await self._step_answer(ctx, fake)
        return True

    # ========== menu, stop, human, delete
    async def _menu(self, ctx: _Ctx) -> bool:
        lang, on = ctx.lang, self._features()
        rows: list[ListRow] = []
        for key in copy.ROWS:
            title, desc = copy.row(key, lang)
            if key in copy.PILOT_ROWS:
                mark = copy.line("mark_pilot" if on.get(key, False) else "mark_soon", lang)
                desc = f"{desc} {mark}"
            rows.append(ListRow(id=f"cb:menu:{key}", title=title, description=desc[:72]))
        menu = ListMenu(button=copy.button("menu_open", lang), rows=rows)
        await self._send(ctx, copy.line("menu_header", lang), menu=menu)
        return True

    async def _menu_pick(self, ctx: _Ctx, key: str) -> bool:
        on = self._features()
        if key in ("call", "card", "day"):
            line = f"win_{key}" if on.get(key) else "win_soon"
        elif key in ("contact", "place", "stop", "human", "delete"):
            line = f"hint_{key}"
        else:
            return True
        await self._send(ctx, copy.line(line, ctx.lang))
        return True

    async def _paused(self, user: User) -> bool:
        c = await self.p.repos.consents.latest(user.id, ConsentKind.PROACTIVE)
        return bool(c and not c.granted)

    async def _set_proactive(self, user: User, on: bool, evidence: str) -> None:
        repos = self.p.repos
        for cat in _CATEGORIES:
            cur = await repos.autonomy.get(user.id, cat)
            await repos.autonomy.upsert(cur.model_copy(update={"enabled": on}))
        if getattr(repos, "life", None) is not None:
            await repos.life.set_topic(user.id, "all", muted=not on)
        if not on:
            await self.p.apply_profile_updates(user, {"morning_briefing": False})
        await repos.consents.add(
            Consent(
                user_id=user.id,
                kind=ConsentKind.PROACTIVE,
                granted=on,
                policy_version=copy.WORDING_VERSION,
                evidence_text=evidence,
                recorded_at=self._now(),
            )  # fmt: skip
        )
        await self.p.audit("proactive.on" if on else "proactive.off", user, via="chatbot")

    async def _stop(self, ctx: _Ctx) -> bool:
        user = ctx.user
        assert user is not None
        if await self._paused(user):
            await self._send(ctx, copy.line("stop_already", ctx.lang))
            return True
        await self._set_proactive(user, False, "user wrote stop")
        await self._send(ctx, copy.line("stop_done", ctx.lang))
        return True

    async def _resume(self, ctx: _Ctx) -> bool:
        user = ctx.user
        assert user is not None
        await self._set_proactive(user, True, "user asked to start again")
        await self._send(ctx, copy.line("resume_done", ctx.lang))
        return True

    async def _human(self, ctx: _Ctx, rest: str) -> bool:
        user = ctx.user
        assert user is not None
        masked = mask_numbers(rest or "-")
        await self.repo.inbox_add("support", masked, user_id=user.id, lang=ctx.lang)
        await self.p.audit("support.requested", user, via="chatbot")
        profile = await self.p.repos.profiles.get_or_default(user.id)
        forwarded = False
        target = self._support_phone()
        if target is not None:
            out = OutboundMessage(
                channel=Channel.WHATSAPP, to_phone=target,
                text=copy.line(
                    "support_forward", "en", name=profile.name or "-", phone=mask_phone(user.phone),
                    text=masked,
                ),
            )  # fmt: skip
            comp = self.composer.compose(out.text or "", kind="internal", lang="en")
            if comp is not None:
                out.text = comp.text
                try:
                    forwarded = bool((await self.p.notifier.send(out, sms_fallback=False)).ok)
                except Exception as e:  # noqa: BLE001
                    log.warning("support forward failed: %s", type(e).__name__)
        await self._send(
            ctx, copy.line("human_forwarded" if forwarded else "human_noted", ctx.lang)
        )
        return True

    def _support_phone(self) -> str | None:
        raw = self.settings.support_inbox
        if not raw:
            return None
        try:
            return normalize_phone(raw, self.settings.default_country_code)
        except ValueError:
            return None

    async def _delete(self, ctx: _Ctx) -> bool:
        """ "delete everything" joins the existing flow: the next message "DELETE" is read by the
        pipeline's pending ``delete_confirm`` (which runs ``delete_everything``). A user who set a
        PIN keeps the PIN-protected path (the message goes on to the brain as before)."""
        user = ctx.user
        assert user is not None
        if user.pin_hash:
            return False
        from friday.api.state import PendingAction

        await self.p.state.set_pending(
            user.id,
            PendingAction(
                kind="delete_confirm", interpretation=None, message=None,
                expires_at=self._now() + self.p.PENDING_TTL,
            ),
        )  # fmt: skip
        await self._send(ctx, copy.line("delete_confirm", ctx.lang))
        return True

    # ========== 3. contact capture
    async def _contact_card(self, ctx: _Ctx, msg: InboundMessage) -> bool:
        user = ctx.user
        assert user is not None
        from friday.calls.numbers import canonical, is_emergency

        raw = msg.contact_phone
        if not raw:
            await self._send(ctx, copy.line("contact_invalid", ctx.lang))
            return True
        if is_emergency(raw):
            await self._send(ctx, copy.line("contact_emergency", ctx.lang))
            return True
        e164 = canonical(raw)
        if e164 is None:
            await self._send(ctx, copy.line("contact_invalid", ctx.lang))
            return True
        await self._ask_nick(ctx, name=(msg.text or "").strip()[:60], number=e164)
        return True

    async def _ask_nick(self, ctx: _Ctx, *, name: str, number: str) -> None:
        assert ctx.user is not None
        sess = ctx.sess or await self._session(ctx.user, ctx.lang)
        ctx.sess = sess
        sess.pending_kind = "contact_nick"
        sess.pending = {"name": name, "number": number, "at": self._now().isoformat()}
        lang = ctx.lang
        if name:
            text = copy.line("contact_ask_nick", lang, name=name)
        else:
            text = copy.line("contact_ask_nick_number", lang)
        await self._send(
            ctx, text,
            buttons=buttons_for(
                ("cb:nick:mummy", copy.button("nick_mummy", lang)),
                ("cb:nick:papa", copy.button("nick_papa", lang)),
                ("cb:skip", copy.button("skip", lang)),
            ),
        )  # fmt: skip
        await self._save(ctx)

    async def _save_contact(self, ctx: _Ctx, name: str, number: str, nick: str | None) -> None:
        from friday.calls.contacts import RELATION_WORDS, ContactBook
        from friday.calls.numbers import NumberHasher

        user = ctx.user
        assert user is not None
        book = ContactBook(self.p.repos.consumer_contacts, NumberHasher(), self.clock)
        relation = None
        if nick:
            low = nick.lower()
            relation = next((rel for rel, words in RELATION_WORDS.items() if low in words), None)
        display = name or (nick or "").title()
        try:
            await book.add(
                user.id, display, number, nicknames=[nick] if nick else [], relationship=relation,
                confirmed=False,
            )  # fmt: skip
        except ValueError:
            await self._send(ctx, copy.line("contact_invalid", ctx.lang))
            return
        who = (nick or name or "").strip().title() or cmd.mask_last2(number)
        await self.p.audit("contact.saved", user, via="chatbot")
        await self._send(
            ctx, copy.line("contact_saved", ctx.lang, who=who, masked=cmd.mask_last2(number))
        )

    # ========== 4. location / place capture
    async def _location_pin(self, ctx: _Ctx, msg: InboundMessage) -> bool:
        user, pin = ctx.user, msg.location
        assert user is not None and pin is not None
        sess = ctx.sess or await self._session(user, ctx.lang)
        ctx.sess = sess
        onboarding_city = sess.step == "city"
        if onboarding_city:
            city = await self._reverse_city(pin)
            if city:
                await self.p.apply_profile_updates(user, {"city": city})
        sess.pending_kind = "place"
        sess.pending = {
            "lat": pin.lat, "lng": pin.lng, "name": pin.name, "address": pin.address,
            "at": self._now().isoformat(), "after": "win" if onboarding_city else "",
        }  # fmt: skip
        if onboarding_city:
            sess.step, sess.step_at = "win", self._now()
        lang = ctx.lang
        await self._send(
            ctx, copy.line("place_ask", lang),
            buttons=buttons_for(
                ("cb:place:home", copy.button("place_home", lang)),
                ("cb:place:office", copy.button("place_office", lang)),
                ("cb:skip", copy.button("skip", lang)),
            ),
        )  # fmt: skip
        await self._save(ctx)
        return True

    async def _reverse_city(self, pin: LocationPin) -> str | None:
        geocoder = self.p._opt("geocoder")
        if geocoder is None:
            return None
        try:
            res = await geocoder.reverse(GeoPoint(lat=pin.lat, lng=pin.lng))
        except Exception as e:  # noqa: BLE001 - geocoding is best effort
            log.info("reverse geocoding failed: %s", type(e).__name__)
            return None
        return getattr(res, "city", None) if res else None

    # ========== pending questions
    async def _pending_answer(self, ctx: _Ctx, msg: InboundMessage) -> bool:
        sess, user = ctx.sess, ctx.user
        assert sess is not None and user is not None
        kind, data = sess.pending_kind, dict(sess.pending)
        text = (msg.text or "").strip()
        t = cmd.norm(text)
        skipped = bool(cmd.SKIP.match(t))
        after = data.get("after", "")

        def clear() -> None:
            sess.pending_kind, sess.pending = None, {}

        if kind == "contact_nick":
            nick = None if skipped else cmd.parse_nickname(text)
            if not skipped and nick is None:
                clear()
                await self._save(ctx)
                return False  # not a nickname: drop the question, the message is something else
            clear()
            await self._save(ctx)
            if skipped and not data.get("name"):
                await self._send(ctx, copy.line("contact_dropped", ctx.lang))
                return True
            await self._save_contact(ctx, data.get("name", ""), data["number"], nick)
            return True
        if kind == "place":
            label = None if skipped else cmd.parse_place_label(text)
            if not skipped and label is None:
                if self._looks_like_request(text):
                    clear()
                    await self._save(ctx)
                    return False
                await self._send(
                    ctx, copy.line("place_reprompt", ctx.lang), dedupe=True,
                    alt=copy.line("place_reprompt", ctx.lang),
                )  # fmt: skip
                await self._save(ctx)
                return True
            clear()
            ack: str
            if label is None:
                ack = copy.line("place_skipped", ctx.lang)
            else:
                name, aliases = label
                pin = LocationPin(
                    lat=data["lat"],
                    lng=data["lng"],
                    name=data.get("name"),
                    address=data.get("address"),
                )
                fake = InboundMessage(
                    channel=Channel.WHATSAPP, from_phone=user.phone, kind=MessageKind.LOCATION,
                    location=pin,
                )  # fmt: skip
                await self.p.save_place(
                    user, Place(owner_user_id=user.id, label=name, aliases=aliases), fake
                )
                ack = copy.line("place_saved", ctx.lang, label=name)
            if after == "win" and sess.step == "win":
                await self._prompt(ctx, "win", prefix=[ack])
            else:
                await self._send(ctx, ack)
                await self._save(ctx)
            return True
        clear()
        await self._save(ctx)
        return False

    # ========== 5. after every handler
    async def post(self, user: User, msg: InboundMessage) -> bool:
        if user.status != UserStatus.ACTIVE or msg.kind not in (
            MessageKind.TEXT, MessageKind.VOICE_NOTE,
        ):  # fmt: skip
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        sess = await self.repo.session_for_user(user.id)
        lang = await self._lang_of(user, sess)
        ctx = _Ctx(user.phone, lang, user, sess)
        if (parts := cmd.split_phone(text)) is not None:
            return await self._typed_number(ctx, *parts)
        if self.settings.chatbot_quick_answers and (
            quick := guards.quick_answer(text, self._now())
        ) is not None:
            await self._send(ctx, copy.line(quick[0], lang, **quick[1]))
            return True
        mode = self.settings.chatbot_offtopic
        if mode != "off" and is_out_of_scope(text):
            last = await self.repo.last_inbox_text("wishlist", user.id)
            masked = mask_numbers(text)
            if last != masked:
                await self.repo.inbox_add("wishlist", masked, user_id=user.id, lang=lang)
            if mode == "redirect":
                await self._send(ctx, copy.line("offtopic", lang))
                return True
        return False

    async def _typed_number(self, ctx: _Ctx, number_text: str, rest: str) -> bool:
        from friday.calls.numbers import canonical, is_emergency

        if is_emergency(number_text):
            await self._send(ctx, copy.line("contact_emergency", ctx.lang))
            return True
        e164 = canonical(number_text)
        if e164 is None:
            await self._send(ctx, copy.line("contact_invalid", ctx.lang))
            return True
        nick = cmd.parse_nickname(rest) if rest else None
        if nick:
            await self._save_contact(ctx, "", e164, nick)
            return True
        await self._ask_nick(ctx, name="", number=e164)
        return True
