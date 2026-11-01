"""Review locked application and model licenses with a conservative policy gate."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from collections import Counter, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROHIBITED = re.compile(r"(?i)AGPL|SSPL|BUSL|COMMONS[ -]CLAUSE|ELASTIC[ -]LICENSE")
REVIEW_REQUIRED = re.compile(r"(?i)(?<!L)GPL|LGPL|CC-BY|CC BY")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_direct_requirements() -> set[str]:
    direct: set[str] = set()
    for raw_line in (ROOT / "apps/api/requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        direct.add(canonical(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]))
    return direct


def distribution_license(distribution: importlib.metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression", "").strip()
    if expression:
        return expression
    license_value = distribution.metadata.get("License", "").strip()
    if license_value and license_value.upper() != "UNKNOWN":
        return " ".join(license_value.split())
    classifiers = distribution.metadata.get_all("Classifier", [])
    approved = [
        value.removeprefix("License :: OSI Approved :: ")
        for value in classifiers
        if value.startswith("License :: OSI Approved :: ")
    ]
    return " OR ".join(approved) if approved else "UNKNOWN"


def python_inventory() -> list[dict[str, str]]:
    by_name = {
        canonical(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    direct = python_direct_requirements()
    pending = deque(sorted(direct))
    visited: set[str] = set()
    rows: list[dict[str, str]] = []
    while pending:
        name = pending.popleft()
        if name in visited:
            continue
        visited.add(name)
        distribution = by_name.get(name)
        if distribution is None:
            if name in direct:
                rows.append({"name": name, "version": "MISSING", "license": "UNKNOWN"})
            continue
        rows.append(
            {
                "name": name,
                "version": distribution.version,
                "license": distribution_license(distribution),
            }
        )
        for requirement in distribution.requires or []:
            dependency = canonical(re.split(r"[<>=!~\[; (]", requirement, maxsplit=1)[0])
            if dependency in by_name and dependency not in visited:
                pending.append(dependency)
    return sorted(rows, key=lambda row: row["name"])


def node_inventory() -> list[dict[str, str]]:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for path, metadata in lock.get("packages", {}).items():
        if (
            not path
            or "node_modules/" not in path
            or metadata.get("link")
            or path.rsplit("node_modules/", 1)[-1].startswith("@classvoice/")
        ):
            continue
        rows.append(
            {
                "name": path.rsplit("node_modules/", 1)[-1],
                "version": str(metadata.get("version", "UNKNOWN")),
                "license": str(metadata.get("license", "UNKNOWN")),
            }
        )
    return sorted(rows, key=lambda row: (row["name"], row["version"]))


def model_inventory() -> list[dict[str, str]]:
    manifest = json.loads(
        (ROOT / "infra/model-registry/manifest.json").read_text(encoding="utf-8")
    )
    return [
        {
            "name": f"{model['model_key']}@{model['version']}",
            "version": model["checkpoint_sha256"],
            "license": model.get("license_name", "UNKNOWN"),
            "review": model.get("license_review_status", "missing"),
            "enabled": str(bool(model.get("enabled", False))).lower(),
        }
        for model in manifest.get("models", [])
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check dependency and model licenses.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    python_rows = python_inventory()
    node_rows = node_inventory()
    model_rows = model_inventory()
    all_rows = [("python", row) for row in python_rows] + [
        ("node", row) for row in node_rows
    ]
    prohibited = [
        {"ecosystem": ecosystem, **row}
        for ecosystem, row in all_rows
        if PROHIBITED.search(row["license"])
    ]
    unknown = [
        {"ecosystem": ecosystem, **row}
        for ecosystem, row in all_rows
        if row["license"] == "UNKNOWN"
    ]
    review = [
        {"ecosystem": ecosystem, **row}
        for ecosystem, row in all_rows
        if REVIEW_REQUIRED.search(row["license"])
    ]
    invalid_models = [
        row
        for row in model_rows
        if row["review"] != "approved" or row["license"] == "UNKNOWN"
    ]
    status = "fail" if prohibited or unknown or invalid_models else "pass"
    report = {
        "status": status,
        "python_packages": len(python_rows),
        "node_packages": len(node_rows),
        "python_licenses": dict(Counter(row["license"] for row in python_rows)),
        "node_licenses": dict(Counter(row["license"] for row in node_rows)),
        "review_required": review,
        "prohibited": prohibited,
        "unknown": unknown,
        "models": model_rows,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            f"License gate {status}: {len(python_rows)} Python, "
            f"{len(node_rows)} Node, {len(model_rows)} model entries."
        )
        print(f"Review-required reciprocal/attribution entries: {len(review)}")
        for row in review:
            print(f"- {row['ecosystem']} {row['name']} {row['version']}: {row['license']}")
        for row in model_rows:
            print(
                f"- model {row['name']}: {row['license']}, review={row['review']}, "
                f"enabled={row['enabled']}"
            )
        if prohibited:
            print(f"Prohibited licenses: {len(prohibited)}")
        if unknown:
            print(f"Unknown licenses: {len(unknown)}")
        if invalid_models:
            print(f"Unapproved model entries: {len(invalid_models)}")
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
