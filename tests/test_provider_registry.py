from multiplay.providers.base import ProviderAdapter, ProviderDecision, ProviderRegistry


class Dummy(ProviderAdapter):
    key = "dummy"
    display_name = "Dummy"

    def recognize(self, evidence, contracts):
        return ProviderDecision(self.key, True, 1.0)

    def validate(self, evidence, contracts):
        return []


def test_provider_registry_rejects_duplicates():
    registry = ProviderRegistry()
    registry.register(Dummy())

    try:
        registry.register(Dummy())
    except ValueError as exc:
        assert "duplicate provider" in str(exc)
    else:
        raise AssertionError("expected ValueError")
