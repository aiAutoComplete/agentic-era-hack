"""Structured architecture manifests for post-approval diagram generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Provider = Literal["aws", "gcp"]
Purpose = Literal["reference", "target"]


@dataclass(slots=True)
class ResourceNode:
    """A cloud resource as it should appear in review diagrams."""

    id: str
    name: str
    kind: str
    service: str
    category: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Relationship:
    """A directed relationship between two resources."""

    source: str
    target: str
    label: str


@dataclass(slots=True)
class ComplianceControl:
    """A control inferred from an approved reference or target architecture."""

    id: str
    name: str
    description: str
    status: Literal["present", "missing", "review"]
    resource_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ArchitectureManifest:
    """A provider-specific architecture model used by deterministic renderers."""

    provider: Provider
    purpose: Purpose
    title: str
    source_files: list[str]
    resources: list[ResourceNode] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    controls: list[ComplianceControl] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


@dataclass(slots=True)
class StandardsMapping:
    """A control-level mapping from AWS reference standards to GCP controls."""

    control: str
    aws_resources: list[str]
    gcp_resources: list[str]
    rationale: str
    status: Literal["mapped", "missing-target", "missing-reference", "review"]


@dataclass(slots=True)
class StandardsMappingManifest:
    """The combined AWS-to-GCP standards mapping used for review diagrams."""

    title: str
    aws_reference: str
    gcp_target: str
    mappings: list[StandardsMapping] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
