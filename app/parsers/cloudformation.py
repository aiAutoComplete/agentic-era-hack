"""CloudFormation reference parser for architecture diagrams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.architecture_manifest import (
    ArchitectureManifest,
    ComplianceControl,
    Relationship,
    ResourceNode,
)

AWS_TYPE_INFO: dict[str, tuple[str, str, str]] = {
    "AWS::EC2::VPC": ("Network", "VPC", "network"),
    "AWS::EC2::Subnet": ("Network", "Subnet", "network"),
    "AWS::EC2::SecurityGroup": ("Network", "SecurityGroup", "security"),
    "AWS::ElasticLoadBalancingV2::LoadBalancer": ("ELB", "LoadBalancer", "ingress"),
    "AWS::EC2::Instance": ("EC2", "Instance", "compute"),
    "AWS::AutoScaling::LaunchConfiguration": ("EC2", "LaunchConfiguration", "compute"),
    "AWS::EC2::LaunchTemplate": ("EC2", "LaunchTemplate", "compute"),
    "AWS::RDS::DBInstance": ("RDS", "Database", "database"),
    "AWS::S3::Bucket": ("S3", "Bucket", "storage"),
    "AWS::IAM::Role": ("IAM", "Role", "identity"),
    "AWS::IAM::Policy": ("IAM", "Policy", "identity"),
    "AWS::IAM::ManagedPolicy": ("IAM", "ManagedPolicy", "identity"),
    "AWS::Logs::LogGroup": ("CloudWatch", "LogGroup", "observability"),
    "AWS::KMS::Key": ("KMS", "Key", "security"),
}


def parse_cloudformation_path(path: Path | str) -> ArchitectureManifest:
    path = Path(path)
    if path.is_dir():
        files = sorted(
            file
            for pattern in ("*.yaml", "*.yml", "*.json")
            for file in path.glob(pattern)
        )
        if not files:
            raise ValueError(
                f"No CloudFormation .yaml, .yml, or .json files found in {path}"
            )
        manifests = [parse_cloudformation_file(file) for file in files]
        return _merge_manifests(manifests)
    return parse_cloudformation_file(path)


def parse_cloudformation_file(path: Path | str) -> ArchitectureManifest:
    path = Path(path)
    return parse_cloudformation_manifest(path.read_text(), source=str(path))


def parse_cloudformation_manifest(
    template_text: str, source: str = "inline"
) -> ArchitectureManifest:
    template = _load_template(template_text)
    resources = template.get("Resources", {})
    if not isinstance(resources, dict):
        raise ValueError("CloudFormation template must contain a Resources mapping.")

    manifest = ArchitectureManifest(
        provider="aws",
        purpose="reference",
        title="AWS Reference Standards",
        source_files=[source],
    )
    resource_bodies: dict[str, dict[str, Any]] = {}

    for logical_id, body in resources.items():
        if not isinstance(body, dict):
            manifest.notes.append(
                f"Skipped {logical_id}: resource body is not an object."
            )
            continue

        aws_type = str(body.get("Type", "Unknown"))
        properties = body.get("Properties", {})
        if not isinstance(properties, dict):
            properties = {}
        service, kind, category = AWS_TYPE_INFO.get(
            aws_type, ("AWS", aws_type, "other")
        )
        resource_id = str(logical_id)
        resource_bodies[resource_id] = body
        manifest.resources.append(
            ResourceNode(
                id=resource_id,
                name=_display_name(resource_id, properties),
                kind=kind,
                service=service,
                category=category,
                properties={"aws_type": aws_type, **_safe_properties(properties)},
            )
        )

    manifest.relationships.extend(_relationships(resource_bodies))
    manifest.controls.extend(_controls(manifest.resources, resource_bodies))
    return manifest


def _load_template(template_text: str) -> dict[str, Any]:
    try:
        loaded = json.loads(template_text)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        pass

    try:
        import yaml

        class CfnLoader(yaml.SafeLoader):
            pass

        def construct_unknown(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            if isinstance(node, yaml.MappingNode):
                return loader.construct_mapping(node)
            return None

        CfnLoader.add_constructor(None, construct_unknown)
        loaded = yaml.load(template_text, Loader=CfnLoader)
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        raise ValueError(f"Template must be valid JSON or YAML: {exc}") from exc


def _display_name(logical_id: str, properties: dict[str, Any]) -> str:
    tags = properties.get("Tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("Key") == "Name" and tag.get("Value"):
                return str(tag["Value"])
    return logical_id


def _safe_properties(properties: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "CidrBlock",
        "Engine",
        "PubliclyAccessible",
        "StorageEncrypted",
        "MapPublicIpOnLaunch",
        "VersioningConfiguration",
        "PublicAccessBlockConfiguration",
    ]
    return {key: properties[key] for key in keep if key in properties}


def _relationships(resource_bodies: dict[str, dict[str, Any]]) -> list[Relationship]:
    relationships: list[Relationship] = []
    for source, body in resource_bodies.items():
        refs = sorted(_find_refs(body))
        for target in refs:
            if target in resource_bodies and target != source:
                relationships.append(
                    Relationship(source=source, target=target, label="references")
                )
    return relationships


def _find_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"Ref", "!Ref"} and isinstance(item, str):
                refs.add(item)
            else:
                refs.update(_find_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_find_refs(item))
    return refs


def _controls(
    resources: list[ResourceNode], resource_bodies: dict[str, dict[str, Any]]
) -> list[ComplianceControl]:
    controls: list[ComplianceControl] = []
    by_category = _resources_by_category(resources)

    if {"network", "security"} & set(by_category):
        controls.append(
            ComplianceControl(
                id="network-segmentation",
                name="Network segmentation",
                description="Reference architecture defines explicit network boundaries.",
                status="present",
                resource_ids=by_category.get("network", [])
                + by_category.get("security", []),
            )
        )

    private_db_ids = []
    encrypted_db_ids = []
    for resource in resources:
        if resource.service != "RDS":
            continue
        properties = resource_bodies.get(resource.id, {}).get("Properties", {})
        if (
            isinstance(properties, dict)
            and properties.get("PubliclyAccessible") is False
        ):
            private_db_ids.append(resource.id)
        if isinstance(properties, dict) and properties.get("StorageEncrypted") is True:
            encrypted_db_ids.append(resource.id)

    if private_db_ids:
        controls.append(
            ComplianceControl(
                id="private-database-access",
                name="Private database access",
                description="Database references are not publicly accessible.",
                status="present",
                resource_ids=private_db_ids,
                evidence=["RDS PubliclyAccessible is false"],
            )
        )
    if encrypted_db_ids:
        controls.append(
            ComplianceControl(
                id="database-encryption",
                name="Database encryption",
                description="Database storage encryption is enabled in the reference.",
                status="present",
                resource_ids=encrypted_db_ids,
                evidence=["RDS StorageEncrypted is true"],
            )
        )

    protected_buckets = []
    for resource in resources:
        if resource.service != "S3":
            continue
        properties = resource_bodies.get(resource.id, {}).get("Properties", {})
        if not isinstance(properties, dict):
            continue
        has_versioning = (
            isinstance(properties.get("VersioningConfiguration"), dict)
            and properties["VersioningConfiguration"].get("Status") == "Enabled"
        )
        has_public_block = isinstance(
            properties.get("PublicAccessBlockConfiguration"), dict
        )
        if has_versioning or has_public_block:
            protected_buckets.append(resource.id)
    if protected_buckets:
        controls.append(
            ComplianceControl(
                id="storage-protection",
                name="Storage protection",
                description="Object storage includes versioning or public access protections.",
                status="present",
                resource_ids=protected_buckets,
            )
        )

    identity_ids = by_category.get("identity", [])
    if identity_ids:
        controls.append(
            ComplianceControl(
                id="iam-least-privilege-boundary",
                name="IAM least privilege boundary",
                description="Reference template declares IAM boundaries that must be mapped carefully.",
                status="review",
                resource_ids=identity_ids,
            )
        )

    return controls


def _resources_by_category(resources: list[ResourceNode]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for resource in resources:
        grouped.setdefault(resource.category, []).append(resource.id)
    return grouped


def _merge_manifests(manifests: list[ArchitectureManifest]) -> ArchitectureManifest:
    merged = ArchitectureManifest(
        provider="aws",
        purpose="reference",
        title="AWS Reference Standards",
        source_files=[
            source for manifest in manifests for source in manifest.source_files
        ],
    )
    seen: set[str] = set()
    for manifest in manifests:
        prefix = (
            Path(manifest.source_files[0]).stem
            if manifest.source_files
            else "reference"
        )
        for resource in manifest.resources:
            if resource.id in seen:
                resource.id = f"{prefix}_{resource.id}"
            seen.add(resource.id)
            merged.resources.append(resource)
        merged.relationships.extend(manifest.relationships)
        merged.controls.extend(manifest.controls)
        merged.notes.extend(manifest.notes)
    return merged
