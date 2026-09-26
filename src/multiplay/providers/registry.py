from __future__ import annotations

from .base import ProviderRegistry
from .bgaming import BGamingProviderAdapter


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(BGamingProviderAdapter())
    return registry
