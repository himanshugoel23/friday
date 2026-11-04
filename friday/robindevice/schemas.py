"""Strict wire schemas for the device API (``extra=forbid`` everywhere).

Signals are counts, timestamps and enums only. There is NO free-text field in any signal: a message,
a notification body, a contact name or a payee name cannot be expressed, and an unknown field is
rejected (never stored, never echoed). Numbers are only a class and an optional salted hash that the
phone computes (the salt never leaves the phone).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

NumberClass = Literal["international", "voip_like", "mobile", "landline", "toll_free", "shortcode"]
RemoteApp = Literal["anydesk", "teamviewer", "quicksupport", "rustdesk", "airdroid", "other_remote"]
PaymentApp = Literal[
    "gpay", "phonepe", "paytm", "bhim", "cred", "amazon_pay", "whatsapp_pay", "sbi_yono", "hdfc",
    "icici", "axis", "kotak", "pnb", "bob", "canara", "union", "indusind", "idfc", "other_bank", "other_upi",
]
PayeeKind = Literal["known", "new", "unknown", "merchant"]
Direction = Literal["debit", "credit"]
SourceClass = Literal["browser", "messaging_app", "file_manager", "unknown"]

EVENT_ID = r"^[A-Za-z0-9_-]{8,64}$"
CALL_ID = r"^[A-Za-z0-9_-]{1,64}$"
HASH64 = r"^[0-9a-f]{64}$"
MAX_MS = 4_102_444_800_000  # year 2100


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _Ev(_Strict):
    id: str = Field(pattern=EVENT_ID)
    ts_ms: int = Field(ge=1_600_000_000_000, le=MAX_MS)


class UnknownCallStarted(_Ev):
    type: Literal["unknown_call_started"]
    call_id: str = Field(pattern=CALL_ID)
    number_class: NumberClass
    number_hash: str | None = Field(default=None, pattern=HASH64)
    direction: Literal["incoming", "outgoing"] = "incoming"


class UnknownCallEnded(_Ev):
    type: Literal["unknown_call_ended"]
    call_id: str = Field(pattern=CALL_ID)
    duration_s: int = Field(ge=0, le=86_400)
    answered: bool


class CallStateOffhook(_Ev):
    type: Literal["call_state_offhook"]
    call_id: str | None = Field(default=None, pattern=CALL_ID)
    duration_s: int = Field(ge=0, le=86_400)
    ongoing: bool


class CameraStart(_Ev):
    type: Literal["camera_in_use_start"]


class CameraStop(_Ev):
    type: Literal["camera_in_use_stop"]


class RemoteAccessOpened(_Ev):
    type: Literal["remote_access_app_opened"]
    app: RemoteApp


class RemoteAccessInstalled(_Ev):
    type: Literal["remote_access_app_installed"]
    app: RemoteApp


class PaymentAppForeground(_Ev):
    type: Literal["payment_app_foreground"]
    app: PaymentApp


class PaymentNotification(_Ev):
    type: Literal["payment_notification"]
    app: PaymentApp
    direction: Direction
    amount_paise: int = Field(ge=1, le=100_000_000_000)
    payee_kind: PayeeKind


class AppInstalledUnknownSource(_Ev):
    type: Literal["app_installed_unknown_source"]
    source_class: SourceClass


class PhoneHeartbeatMissing(_Ev):
    type: Literal["phone_heartbeat_missing"]
    gap_s: int = Field(ge=60, le=30 * 86_400)


SignalEvent = Annotated[
    UnknownCallStarted
    | UnknownCallEnded
    | CallStateOffhook
    | CameraStart
    | CameraStop
    | RemoteAccessOpened
    | RemoteAccessInstalled
    | PaymentAppForeground
    | PaymentNotification
    | AppInstalledUnknownSource
    | PhoneHeartbeatMissing,
    Field(discriminator="type"),
]
_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(SignalEvent)

# signal type -> the consent item that must be granted for the server to keep it
SIGNAL_CONSENT: dict[str, str] = {
    "unknown_call_started": "calls",
    "unknown_call_ended": "calls",
    "call_state_offhook": "calls",
    "camera_in_use_start": "camera",
    "camera_in_use_stop": "camera",
    "remote_access_app_opened": "remote_access",
    "remote_access_app_installed": "remote_access",
    "payment_app_foreground": "payment_app",
    "payment_notification": "payment_notifications",
    "app_installed_unknown_source": "unknown_sources",
    "phone_heartbeat_missing": "heartbeat",
}
SIGNAL_TYPES = tuple(SIGNAL_CONSENT)


def validate_event(raw: Any) -> tuple[Any | None, str | None]:
    """(event, None) or (None, reason_code). The reason never echoes the offending value."""
    if not isinstance(raw, dict):
        return None, "not_an_object"
    if raw.get("type") not in SIGNAL_CONSENT:
        return None, "unknown_type"
    try:
        return _EVENT_ADAPTER.validate_python(raw), None
    except ValidationError as e:
        kinds = {err["type"] for err in e.errors()}
        return None, "extra_field" if "extra_forbidden" in kinds else "bad_value"


# ----------------------------------------------------------------------------- API bodies


class PairIn(_Strict):
    code: str = Field(pattern=r"^[A-Z2-9]{8}$")
    app_version: str = Field(pattern=r"^[0-9][0-9A-Za-z._+-]{0,23}$")
    os_sdk: int = Field(ge=21, le=60)


class Roles(_Strict):
    call_screening: bool = False
    phone_state: bool = False
    notification_access: bool = False
    location: bool = False
    package_visibility: bool = False
    usage_access: bool = False
    post_notifications: bool = False


class HeartbeatIn(_Strict):
    app_version: str = Field(pattern=r"^[0-9][0-9A-Za-z._+-]{0,23}$")
    os_sdk: int = Field(ge=21, le=60)
    roles: Roles
    battery_low: bool = False
    ts_ms: int = Field(ge=1_600_000_000_000, le=MAX_MS)


class SignalBatchIn(_Strict):
    events: list[Any] = Field(max_length=100)


class ShareIn(_Strict):
    kind: Literal["text", "url", "phone", "app_name", "file_name", "screenshot_ref"]
    value: str = Field(min_length=1, max_length=2000)


class LocationIn(_Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class AckIn(_Strict):
    kind: Literal["this_was_fine", "i_am_ok", "sos", "dismissed", "call_son_tapped"]
    prompt_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{6,64}$")
    location: LocationIn | None = None


class ConsentIn(_Strict):
    items: dict[str, bool] = Field(max_length=32)


class PauseIn(_Strict):
    minutes: int = Field(ge=5, le=1440)
