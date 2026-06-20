import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.adapters.registry import ProviderRegistry
from abigail.model_router.adapters.dry_run import DryRunProviderAdapter

_REGISTRY = ProviderRegistry()


def test_registry_returns_adapter_for_openai():
    adapter = _REGISTRY.get("openai")
    assert isinstance(adapter, DryRunProviderAdapter)
    assert adapter.provider_name == "openai"


def test_registry_returns_adapter_for_anthropic():
    adapter = _REGISTRY.get("anthropic")
    assert adapter.provider_name == "anthropic"


def test_registry_returns_adapter_for_groq():
    adapter = _REGISTRY.get("groq")
    assert adapter.provider_name == "groq"


def test_registry_returns_adapter_for_current_backend():
    adapter = _REGISTRY.get("current_backend")
    assert adapter.provider_name == "current_backend"


def test_registry_falls_back_to_local_for_unknown():
    adapter = _REGISTRY.get("unknown_provider_xyz")
    assert isinstance(adapter, DryRunProviderAdapter)
    assert adapter.provider_name == "local"


def test_all_known_providers_registered():
    providers = _REGISTRY.registered_providers()
    for expected in ("current_backend", "local", "openai", "anthropic", "gemini", "groq", "xai"):
        assert expected in providers


def test_backend_dispatch_not_referenced_in_adapters():
    adapter_dir = Path(__file__).parent.parent / "adapters"
    for py_file in adapter_dir.glob("*.py"):
        content = py_file.read_text()
        assert "BACKEND_DISPATCH" not in content, (
            f"BACKEND_DISPATCH referenced in {py_file.name} — must not be touched by MR-02"
        )


def test_no_real_sdk_imports_in_adapters():
    adapter_dir = Path(__file__).parent.parent / "adapters"
    forbidden = ("import openai", "import anthropic", "import groq", "import google",
                 "from openai", "from anthropic", "from groq", "from google",
                 "import httpx", "import requests", "import urllib")
    for py_file in adapter_dir.glob("*.py"):
        content = py_file.read_text()
        for pattern in forbidden:
            assert pattern not in content, (
                f"Forbidden import '{pattern}' found in {py_file.name}"
            )


def test_no_api_key_reads_in_adapters():
    adapter_dir = Path(__file__).parent.parent / "adapters"
    for py_file in adapter_dir.glob("*.py"):
        content = py_file.read_text()
        assert "os.environ" not in content, f"os.environ found in {py_file.name}"
        assert "API_KEY" not in content, f"API_KEY reference found in {py_file.name}"
