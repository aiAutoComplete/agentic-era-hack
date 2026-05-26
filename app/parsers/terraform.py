"""Terraform parser for approved GCP target architecture diagrams."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.architecture_manifest import (
    ArchitectureManifest,
    ComplianceControl,
    Relationship,
    ResourceNode,
)

GCP_TYPE_INFO: dict[str, tuple[str, str, str]] = {
    "google_compute_network": ("VPC", "Network", "network"),
    "google_compute_subnetwork": ("VPC", "Subnetwork", "network"),
    "google_compute_firewall": ("VPC", "Firewall", "security"),
    "google_compute_router": ("Cloud Router", "Router", "network"),
    "google_compute_instance": ("Compute Engine", "Instance", "compute"),
    "google_compute_instance_template": (
        "Compute Engine",
        "InstanceTemplate",
        "compute",
    ),
    "google_cloud_run_v2_service": ("Cloud Run", "Service", "compute"),
    "google_container_cluster": ("GKE", "Cluster", "compute"),
    "google_sql_database_instance": ("Cloud SQL", "Database", "database"),
    "google_storage_bucket": ("Cloud Storage", "Bucket", "storage"),
    "google_service_account": ("IAM", "ServiceAccount", "identity"),
    "google_project_iam_member": ("IAM", "IAMMember", "identity"),
    "google_logging_project_sink": ("Cloud Logging", "Sink", "observability"),
    "google_kms_crypto_key": ("Cloud KMS", "CryptoKey", "security"),
}

RESOURCE_START = re.compile(r'resource\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"\s*\{')
REFERENCE = re.compile(r"\b(google_[A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\b")


def parse_terraform_directory(path: Path | str) -> ArchitectureManifest:
    root = Path(path)
    if root.is_file():
        return parse_terraform_manifest(root.read_text(), source=str(root))
    tf_files = sorted(root.glob("*.tf"))
    if not tf_files:
        raise ValueError(f"No .tf files found in {root}")
    text = "\n\n".join(file.read_text() for file in tf_files)
    return parse_terraform_manifest(
        text, source=", ".join(str(file) for file in tf_files)
    )


def parse_terraform_manifest(
    terraform_text: str, source: str = "inline"
) -> ArchitectureManifest:
    blocks = _resource_blocks(terraform_text)
    manifest = ArchitectureManifest(
        provider="gcp",
        purpose="target",
        title="GCP Target Architecture",
        source_files=[source],
    )

    for block in blocks:
        service, kind, category = GCP_TYPE_INFO.get(
            block["type"], ("GCP", block["type"], "other")
        )
        resource_id = f"{block['type']}.{block['name']}"
        manifest.resources.append(
            ResourceNode(
                id=resource_id,
                name=_attribute(block["body"], "name")
                or _attribute(block["body"], "account_id")
                or block["name"],
                kind=kind,
                service=service,
                category=category,
                properties=_properties(block),
            )
        )

    resource_ids = {resource.id for resource in manifest.resources}
    relationships: set[tuple[str, str, str]] = set()
    for block in blocks:
        source_id = f"{block['type']}.{block['name']}"
        for match in REFERENCE.finditer(block["body"]):
            target = f"{match.group(1)}.{match.group(2)}"
            if target in resource_ids and target != source_id:
                relationships.add((source_id, target, "references"))
    manifest.relationships = [
        Relationship(source=source, target=target, label=label)
        for source, target, label in sorted(relationships)
    ]
    manifest.controls = _controls(manifest.resources, blocks)
    return manifest


def _resource_blocks(terraform_text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    position = 0
    while match := RESOURCE_START.search(terraform_text, position):
        start = match.end()
        depth = 1
        cursor = start
        while cursor < len(terraform_text) and depth:
            if terraform_text[cursor] == "{":
                depth += 1
            elif terraform_text[cursor] == "}":
                depth -= 1
            cursor += 1
        body = terraform_text[start : cursor - 1]
        blocks.append(
            {"type": match.group("type"), "name": match.group("name"), "body": body}
        )
        position = cursor
    return blocks


def _attribute(body: str, name: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*\"([^\"]+)\"", body, re.MULTILINE)
    return match.group(1) if match else None


def _bool_attribute(body: str, name: str) -> bool | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(true|false)", body, re.MULTILINE)
    if not match:
        return None
    return match.group(1) == "true"


def _properties(block: dict[str, str]) -> dict[str, Any]:
    body = block["body"]
    properties: dict[str, Any] = {}
    for name in ["name", "account_id", "database_version", "ip_cidr_range"]:
        value = _attribute(body, name)
        if value is not None:
            properties[name] = value
    for name in ["deletion_protection", "uniform_bucket_level_access", "ipv4_enabled"]:
        value = _bool_attribute(body, name)
        if value is not None:
            properties[name] = value
    properties["terraform_type"] = block["type"]
    return properties


def _controls(
    resources: list[ResourceNode], blocks: list[dict[str, str]]
) -> list[ComplianceControl]:
    controls: list[ComplianceControl] = []
    by_type = {f"{block['type']}.{block['name']}": block for block in blocks}
    by_category = _resources_by_category(resources)

    if by_category.get("network"):
        controls.append(
            ComplianceControl(
                id="network-segmentation",
                name="Network segmentation",
                description="Target architecture defines explicit GCP network boundaries.",
                status="present",
                resource_ids=by_category["network"],
            )
        )

    private_db_ids = []
    protected_db_ids = []
    for resource in resources:
        if resource.service != "Cloud SQL":
            continue
        body = by_type.get(resource.id, {}).get("body", "").lower()
        if "ipv4_enabled = false" in body:
            private_db_ids.append(resource.id)
        if "deletion_protection = true" in body:
            protected_db_ids.append(resource.id)
    if private_db_ids:
        controls.append(
            ComplianceControl(
                id="private-database-access",
                name="Private database access",
                description="Cloud SQL does not expose a public IPv4 endpoint.",
                status="present",
                resource_ids=private_db_ids,
                evidence=["ipv4_enabled = false"],
            )
        )
    if protected_db_ids:
        controls.append(
            ComplianceControl(
                id="database-protection",
                name="Database protection",
                description="Cloud SQL deletion protection is enabled.",
                status="present",
                resource_ids=protected_db_ids,
                evidence=["deletion_protection = true"],
            )
        )

    protected_buckets = []
    for resource in resources:
        if resource.service != "Cloud Storage":
            continue
        body = by_type.get(resource.id, {}).get("body", "").lower()
        if "uniform_bucket_level_access = true" in body and "enabled = true" in body:
            protected_buckets.append(resource.id)
    if protected_buckets:
        controls.append(
            ComplianceControl(
                id="storage-protection",
                name="Storage protection",
                description="GCS uses uniform bucket-level access and versioning.",
                status="present",
                resource_ids=protected_buckets,
                evidence=[
                    "uniform_bucket_level_access = true",
                    "versioning.enabled = true",
                ],
            )
        )

    identity_ids = by_category.get("identity", [])
    if identity_ids:
        status = "review"
        forbidden = ("roles/owner", "roles/editor", "*")
        if not any(
            token in by_type.get(resource_id, {}).get("body", "")
            for resource_id in identity_ids
            for token in forbidden
        ):
            status = "present"
        controls.append(
            ComplianceControl(
                id="iam-least-privilege-boundary",
                name="IAM least privilege boundary",
                description="Target IAM avoids broad owner/editor/wildcard grants.",
                status=status,
                resource_ids=identity_ids,
            )
        )

    return controls


def _resources_by_category(resources: list[ResourceNode]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for resource in resources:
        grouped.setdefault(resource.category, []).append(resource.id)
    return grouped
