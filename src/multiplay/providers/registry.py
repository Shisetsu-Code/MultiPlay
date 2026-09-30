from __future__ import annotations

from .base import ProviderRegistry
from .belatra import BelatraProviderAdapter
from .bgaming import BGamingProviderAdapter
from .one_spin4win import OneSpin4WinProviderAdapter
from .pragmatic import PragmaticProviderAdapter
from .redtiger import RedTigerProviderAdapter
from .rubyplay import RubyPlayProviderAdapter
from .three_oaks import ThreeOaksProviderAdapter
from .yggdrasil import YggdrasilProviderAdapter


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(BGamingProviderAdapter())
    registry.register(YggdrasilProviderAdapter())
    registry.register(PragmaticProviderAdapter())
    registry.register(OneSpin4WinProviderAdapter())
    registry.register(BelatraProviderAdapter())
    registry.register(RubyPlayProviderAdapter())
    registry.register(RedTigerProviderAdapter())
    registry.register(ThreeOaksProviderAdapter())
    return registry
