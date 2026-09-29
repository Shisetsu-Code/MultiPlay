from __future__ import annotations

from .base import ProviderRegistry
from .bgaming import BGamingProviderAdapter
from .yggdrasil import YggdrasilProviderAdapter


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(BGamingProviderAdapter())
    registry.register(YggdrasilProviderAdapter())
    return registry
