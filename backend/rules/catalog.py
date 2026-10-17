from __future__ import annotations

from pathlib import Path

import yaml

from backend.audit.models import RuleDefinition, Severity

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"


def get_rule_catalog() -> tuple[str, list[RuleDefinition]]:
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    version = str(raw.get("version", "1.0"))
    rules = []
    for item in raw["rules"]:
        rules.append(
            RuleDefinition(
                rule_id=item["rule_id"],
                standard_section=item["standard_section"],
                title=item["title"],
                description=item["description"],
                type=item["type"],
                required_inputs=item.get("required_inputs", []),
                threshold=item.get("threshold"),
                severity_if_failed=Severity(item["severity_if_failed"]),
                remediation=item.get("remediation", ""),
            )
        )
    return version, rules


def get_rule_map() -> dict[str, RuleDefinition]:
    _, rules = get_rule_catalog()
    return {r.rule_id: r for r in rules}
