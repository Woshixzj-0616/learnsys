"""今日页聚合：一次算完今日目标，再分发给概览 / 今日 / 三域。

今日页原先同时请求 `/api/overview`、`/api/today`、`/api/home`，
三条路径各算一遍 `day_plan.build`；这里收成一个入口，`learning` 只算一次。
Qt 与其他页面仍可用各自的原接口。
"""
from __future__ import annotations

import datetime

from learnsys.services import home as home_service
from learnsys.services import overview as overview_service
from learnsys.services import today as today_service


def payload(conn, day: str = "") -> dict:
    day = str(day or datetime.date.today().isoformat())[:10]
    learning = today_service.learning_summary(conn, day)
    return {
        "date": day,
        "overview": overview_service.build(conn, day, plan=learning["plan"]),
        "today": today_service.payload(conn, day, learning=learning),
        "home": home_service.payload(conn, day, learning=learning),
    }
