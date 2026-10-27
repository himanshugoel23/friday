"""RIDE use-case models. Money is integer paise. A fare is always a RANGE until the ride starts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Paise

KINDS = ("auto", "bike", "cab", "premium")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VehicleOption(_M):
    vehicle_id: str = Field(min_length=1)
    name: str
    kind: str
    eta_min: int = Field(ge=0, le=240)
    fare_low_paise: Paise
    fare_high_paise: Paise
    surge_x100: int = Field(default=100, ge=100, le=1000)  # 150 = 1.5x
    available: bool = True

    @model_validator(mode="after")
    def _range(self) -> VehicleOption:
        if self.fare_high_paise < self.fare_low_paise:
            raise ValueError("fare range is upside down")
        return self


class RideQuote(_M):
    """What the site shows right before the irreversible 'request ride' click."""

    vehicle_id: str
    name: str
    pickup: str
    drop: str
    fare_low_paise: Paise
    fare_high_paise: Paise
    surge_x100: int = 100
    cancel_fee_paise: Paise = 0


class DriverInfo(_M):
    """Shown to the user as text. It never carries the ride-start code."""

    name: str
    vehicle_no: str = ""
    vehicle_model: str = ""
    rating: str = ""
    eta_min: int | None = None
