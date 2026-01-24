from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from typing import Iterable

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")


def _build_chart(weights: Iterable[tuple[datetime, float]]) -> bytes:
    dates = [item[0] for item in weights]
    values = [item[1] for item in weights]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(dates, values, marker="o", linewidth=2, color="#1f77b4")
    ax.set_title("Динамика веса")
    ax.set_xlabel("Дата")
    ax.set_ylabel("Вес, кг")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()

    buffer = BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer.read()


async def build_weight_chart(weights: Iterable[tuple[datetime, float]]) -> bytes:
    return await asyncio.to_thread(_build_chart, weights)
