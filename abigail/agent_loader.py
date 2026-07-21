# agent_loader.py — LOGOS Governance Systems Inc.
# Loads YAML agent definitions and surfaces system prompts for dispatch.
import os
import yaml
from pathlib import Path

_default_agents_dir = Path(__file__).resolve().parent / "agents"
_host_agents_dir = Path(__file__).resolve().parent.parent / "agents"

AGENTS_DIR = Path(
    os.environ.get(
        "ABIGAIL_AGENTS_DIR",
        str(_default_agents_dir if _default_agents_dir.exists() else _host_agents_dir),
    )
)


def load_all_agents() -> dict:
    agents = {}
    for yaml_file in AGENTS_DIR.rglob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and "agent" in data:
                a = data["agent"]
                aid = a.get("id")
                if aid:
                    agents[aid] = a
        except Exception:
            pass
    return agents


def get_agent(agent_id: str) -> dict | None:
    return load_all_agents().get(agent_id)


def get_agent_system_prompt(agent_id: str) -> str | None:
    a = get_agent(agent_id)
    return a.get("system_prompt") if a else None


def list_agents() -> list:
    return [
        {"id": a.get("id"), "name": a.get("name"),
         "specialty": a.get("specialty"), "department": a.get("department")}
        for a in load_all_agents().values()
    ]
