"""
Расчёт нормы калорий (Mifflin–St Jeor), ИМТ и целевой калорийности.
Формулы: Mifflin-St Jeor (1990), стандартные коэффициенты активности.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# Коэффициенты активности (Total Daily Energy Expenditure = BMR × multiplier)
ACTIVITY_SEDENTARY = 1.2      # Почти нет движения
ACTIVITY_LIGHT = 1.375        # 1–3 дня в неделю лёгкая активность
ACTIVITY_MODERATE = 1.55      # 3–5 дней умеренная
ACTIVITY_ACTIVE = 1.725       # 6–7 дней активность
ACTIVITY_VERY_ACTIVE = 1.9    # Тяжёлые тренировки, физическая работа

ACTIVITY_MULTIPLIERS: dict[str, float] = {
    "sedentary": ACTIVITY_SEDENTARY,
    "light": ACTIVITY_LIGHT,
    "moderate": ACTIVITY_MODERATE,
    "active": ACTIVITY_ACTIVE,
    "very_active": ACTIVITY_VERY_ACTIVE,
}

# Дефицит/профицит по цели (ккал)
DEFICIT_LOSE = 500    # ~0.5 кг/нед
SURPLUS_GAIN = 400    # ~0.3–0.4 кг/нед


def bmr_mifflin_st_jeor(
    weight_kg: float,
    height_cm: float,
    age_years: int,
    gender: Literal["m", "f"],
) -> float:
    """
    BMR по формуле Mifflin–St Jeor (1990).
    weight: кг, height: см, age: годы.
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    if gender == "m":
        return base + 5
    return base - 161


def tdee(bmr: float, activity_level: str) -> float:
    """Суточная норма калорий (TDEE) = BMR × коэффициент активности."""
    mult = ACTIVITY_MULTIPLIERS.get(activity_level or "sedentary", ACTIVITY_SEDENTARY)
    return round(bmr * mult, 0)


def bmi(weight_kg: float, height_cm: float) -> float:
    """ИМТ = вес (кг) / рост (м)²."""
    if height_cm <= 0:
        return 0.0
    h_m = height_cm / 100
    return round(weight_kg / (h_m * h_m), 1)


def bmi_category(bmi_val: float) -> str:
    """Категория по ИМТ (ВОЗ)."""
    if bmi_val < 18.5:
        return "недостаток массы"
    if bmi_val < 25:
        return "норма"
    if bmi_val < 30:
        return "избыток массы"
    return "ожирение"


def daily_calorie_target(
    tdee_val: float,
    goal: Literal["lose", "maintain", "gain"],
) -> int:
    """Целевая калорийность в день по цели."""
    if goal == "lose":
        return max(1200, int(tdee_val - DEFICIT_LOSE))
    if goal == "gain":
        return int(tdee_val + SURPLUS_GAIN)
    return int(tdee_val)


def age_from_birth_year(birth_year: int, now: datetime | None = None) -> int:
    """Возраст по году рождения."""
    from datetime import datetime
    n = now or datetime.now()
    return max(0, n.year - birth_year)


@dataclass
class CalorieProfile:
    """Результат расчёта: BMR, TDEE, ИМТ, целевые калории."""
    bmr: float
    tdee: float
    bmi: float
    bmi_category: str
    daily_target: int
    goal: str


def compute_calorie_profile(
    weight_kg: float,
    height_cm: float | None,
    birth_year: int | None,
    gender: str | None,
    activity_level: str | None,
    goal: str | None,
    now: datetime | None = None,
) -> CalorieProfile | None:
    """
    Считает BMR, TDEE, ИМТ и целевую калорийность.
    Возвращает None, если не хватает данных (рост, год рождения, пол).
    """
    if not height_cm or height_cm <= 0 or not birth_year or birth_year <= 0:
        return None
    g = (gender or "m").strip().lower()
    if g not in ("m", "f"):
        g = "m"
    act = (activity_level or "sedentary").strip().lower()
    if act not in ACTIVITY_MULTIPLIERS:
        act = "sedentary"
    gl = (goal or "maintain").strip().lower()
    if gl not in ("lose", "maintain", "gain"):
        gl = "maintain"

    age = age_from_birth_year(birth_year, now)
    bmr_val = bmr_mifflin_st_jeor(weight_kg, height_cm, age, g)
    tdee_val = tdee(bmr_val, act)
    bmi_val = bmi(weight_kg, height_cm)
    target = daily_calorie_target(tdee_val, gl)

    return CalorieProfile(
        bmr=round(bmr_val, 0),
        tdee=round(tdee_val, 0),
        bmi=bmi_val,
        bmi_category=bmi_category(bmi_val),
        daily_target=target,
        goal=gl,
    )
