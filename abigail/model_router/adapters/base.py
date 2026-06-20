from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from ..envelopes import ProviderRequestEnvelope, ProviderResponseEnvelope


class BaseProviderAdapter(ABC):
    provider_name: str = "base"

    @abstractmethod
    def supports(self, route_card: dict) -> bool:
        ...

    @abstractmethod
    def build_request(
        self,
        route_card: dict,
        session=None,
        tacit_card: Optional[dict] = None,
    ) -> ProviderRequestEnvelope:
        ...

    @abstractmethod
    def execute(self, request_envelope: ProviderRequestEnvelope) -> ProviderResponseEnvelope:
        ...

    def normalize_response(self, raw_response) -> ProviderResponseEnvelope:
        if isinstance(raw_response, ProviderResponseEnvelope):
            return raw_response
        return ProviderResponseEnvelope(
            provider=self.provider_name,
            dry_run=True,
            output_text="[DRY_RUN]",
        )
