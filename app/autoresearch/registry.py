import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_DIR = Path(__file__).parent.parent.parent / "data" / "registry"


def register_version(
    component: str,
    version: str,
    params: dict,
    metrics: dict | None = None,
    dataset: str | None = None,
    notes: str = "",
) -> str:
    """Register a new version of a component (model, prompt, config)."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "component": component,
        "version": version,
        "params": params,
        "metrics": metrics or {},
        "dataset": dataset,
        "notes": notes,
        "created_at": datetime.now(UTC).isoformat(),
        "promoted": False,
    }

    filepath = REGISTRY_DIR / f"{component}_{version}.json"
    with open(filepath, "w") as f:
        json.dump(entry, f, indent=2)

    logger.info("Registered %s version %s", component, version)
    return str(filepath)


def get_version(component: str, version: str) -> dict | None:
    filepath = REGISTRY_DIR / f"{component}_{version}.json"
    if not filepath.exists():
        return None
    with open(filepath) as f:
        return json.load(f)


def list_versions(component: str) -> list[dict]:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    versions = []
    for filepath in sorted(REGISTRY_DIR.glob(f"{component}_*.json")):
        with open(filepath) as f:
            versions.append(json.load(f))
    return versions


def get_promoted(component: str) -> dict | None:
    versions = list_versions(component)
    promoted = [v for v in versions if v.get("promoted")]
    return promoted[-1] if promoted else None


def promote_version(component: str, version: str) -> bool:
    filepath = REGISTRY_DIR / f"{component}_{version}.json"
    if not filepath.exists():
        return False

    # Demote all other versions
    for other in REGISTRY_DIR.glob(f"{component}_*.json"):
        with open(other) as f:
            data = json.load(f)
        if data.get("promoted"):
            data["promoted"] = False
            with open(other, "w") as f:
                json.dump(data, f, indent=2)

    # Promote this one
    with open(filepath) as f:
        data = json.load(f)
    data["promoted"] = True
    data["promoted_at"] = datetime.now(UTC).isoformat()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Promoted %s version %s", component, version)
    return True
