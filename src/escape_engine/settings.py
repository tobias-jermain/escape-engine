"""User settings chosen in first-run setup. Used as defaults by the menu and ``escape check``."""

from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel, ValidationError, field_validator

from escape_engine.core import airports
from escape_engine.core.models import TripRules
from escape_engine.core.parse import parse_clock, parse_duration, parse_return_by


def settings_path() -> Path:
    return Path(user_config_dir("escape-engine")) / "settings.json"


class Settings(BaseModel):
    home: str = "LON"
    max_price: str = "75"
    currency: str = "GBP"
    depart_after: str = "05:00"
    return_by: str = "23:59"
    min_ground: str = "6h"
    auto_update_check: bool = True
    setup_done: bool = False

    @field_validator("home")
    @classmethod
    def _home(cls, v: str) -> str:
        try:
            airports.resolve(v)
        except LookupError as exc:  # pydantic only converts ValueError into a validation error
            raise ValueError(str(exc)) from None
        return v.upper()

    def rules(self, **overrides: object) -> TripRules:
        """Trip rules from these settings, with any explicit overrides applied."""
        fields: dict[str, object] = {
            "max_price": self.max_price,
            "currency": self.currency,
            "depart_after": parse_clock(self.depart_after),
            "return_by": parse_return_by(self.return_by),
            "min_ground": parse_duration(self.min_ground),
        }
        fields.update({k: v for k, v in overrides.items() if v is not None})
        return TripRules.model_validate(fields)


def load(path: Path | None = None) -> Settings:
    """Saved settings, or defaults if none are saved or the file is unreadable."""
    try:
        return Settings.model_validate(json.loads((path or settings_path()).read_text("utf-8")))
    except (OSError, ValueError, ValidationError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), "utf-8")
