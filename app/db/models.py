from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    tg_id: int
    target_weight: Optional[float] = None

    @field_validator("target_weight")
    @classmethod
    def validate_target_weight(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("weight must be positive")
        return value


class ScheduleCreate(BaseModel):
    user_id: int
    weekday: int = Field(ge=0, le=6)
    time: str
    week_type: str = "any"

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if not value:
            raise ValueError("time is required")
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("invalid time format")
        hour_str, minute_str = parts
        if not (hour_str.isdigit() and minute_str.isdigit()):
            raise ValueError("invalid time format")
        hour = int(hour_str)
        minute = int(minute_str)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("invalid time format")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("week_type")
    @classmethod
    def validate_week_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"any", "even", "odd"}:
            raise ValueError("invalid week_type")
        return normalized


class WeightEntry(BaseModel):
    user_id: int
    weight: float
    date: datetime

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("weight must be positive")
        return value


class WorkoutLogCreate(BaseModel):
    user_id: int
    date: datetime
    status: str
    duration: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"done", "missed"}:
            raise ValueError("invalid status")
        return normalized

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        if value < 0:
            raise ValueError("duration must be >= 0")
        return value


class WeekdaysInput(BaseModel):
    days: list[int]

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("days list is empty")
        normalized = sorted(set(value))
        for day in normalized:
            if day < 0 or day > 6:
                raise ValueError("weekday out of range")
        return normalized
