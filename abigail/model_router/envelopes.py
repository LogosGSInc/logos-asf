from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


class ProviderRequestEnvelope(BaseModel):
    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    route_card_id: str = ""
    selected_provider: str = "current_backend"
    model_hint: Optional[str] = None
    request_type: str = "normal_chat"
    data_sensitivity: str = "public"
    output_contract: str = "freeform"
    tool_required: str = "none"
    review_required: bool = False
    # Redacted summary only — must never contain raw user prompt text
    messages_summary: str = ""
    # Policy label only — must never contain full system prompt text
    system_policy_summary: str = ""
    redaction_applied: bool = False
    dry_run: bool = True  # MR-02: always True
    blocked_reason: Optional[str] = None


class ProviderResponseEnvelope(BaseModel):
    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: str = "unknown"
    model: Optional[str] = None
    dry_run: bool = True
    output_text: str = ""
    structured_output: Optional[dict] = None
    tool_calls: List[dict] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    safety_flags: List[str] = Field(default_factory=list)
    memory_recommendation: Optional[str] = None
    error: Optional[str] = None
