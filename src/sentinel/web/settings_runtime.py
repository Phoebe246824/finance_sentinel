"""设置页运行时配置的快照与管理器。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sentinel.config import SentinelSettings


@dataclass
class RuntimeSettingsSnapshot:
    settings: SentinelSettings
    updated_at: str


class RuntimeSettingsManager:
    def __init__(self, initial_settings: SentinelSettings) -> None:
        self._snapshot = RuntimeSettingsSnapshot(
            settings=initial_settings,
            updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._lock = asyncio.Lock()

    def get_active_settings(self) -> SentinelSettings:
        return self._snapshot.settings

    def get_updated_at(self) -> str:
        return self._snapshot.updated_at

    async def replace(self, settings: SentinelSettings) -> None:
        async with self._lock:
            self._snapshot = RuntimeSettingsSnapshot(
                settings=settings,
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )
