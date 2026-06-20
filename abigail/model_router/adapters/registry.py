from __future__ import annotations
from .dry_run import DryRunProviderAdapter

_KNOWN_PROVIDERS = frozenset({
    "current_backend", "local", "openai", "anthropic", "gemini", "groq", "xai"
})

_REGISTRY: dict[str, DryRunProviderAdapter] = {
    p: DryRunProviderAdapter(provider_name=p) for p in _KNOWN_PROVIDERS
}

_FALLBACK = DryRunProviderAdapter(provider_name="local")


class ProviderRegistry:
    def get(self, provider_name: str) -> DryRunProviderAdapter:
        """Return dry-run adapter. Fails closed to local if unknown."""
        return _REGISTRY.get(provider_name, _FALLBACK)

    def registered_providers(self) -> list[str]:
        return sorted(_REGISTRY.keys())
