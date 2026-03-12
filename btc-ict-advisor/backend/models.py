from pydantic import BaseModel, Field


class IndicatorSettingsUpdate(BaseModel):
    active_indicators: list[str] = Field(default_factory=list)
    min_score_threshold: int = 70
    signal_cooldown_hours: int = 4
    primary_timeframe: str = "1h"
    confirmation_timeframe: str = "4h"
