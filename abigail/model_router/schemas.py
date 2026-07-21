from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


class ModelRouteCard(BaseModel):
    card_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_type: str
    risk_level: str
    data_sensitivity: str
    freshness_required: bool = False
    tool_required: str = "none"
    latency_need: str = "normal"
    cost_ceiling: str = "medium"
    output_contract: str = "freeform"
    selected_provider: str = "current_backend"
    fallback_provider: Optional[str] = None
    review_required: bool = False
    reviewer_provider: Optional[str] = None
    swarm_recommended: bool = False
    swarm_parent: Optional[str] = None
    swarm_children: List[str] = Field(default_factory=list)
    memory_policy: str = "ephemeral"
    reason_for_route: str = ""
    blocked_reason: Optional[str] = None
