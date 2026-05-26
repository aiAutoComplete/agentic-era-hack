"""Deterministic diagram renderers for architecture manifests."""

from __future__ import annotations

import re
from pathlib import Path

from app.architecture_manifest import (
    ArchitectureManifest,
    StandardsMappingManifest,
)


def write_manifest_markdown(manifest: ArchitectureManifest, path: Path) -> None:
    """Write a detailed Mermaid review diagram for one provider manifest."""
    lines = [
        f"# {manifest.title}",
        "",
        "```mermaid",
        "flowchart TB",
    ]

    for category, resources in _grouped_resources(manifest).items():
        cluster_id = _mermaid_id(f"cluster_{category}")
        lines.append(f'  subgraph {cluster_id}["{category.title()}"]')
        for resource in resources:
            node_id = _mermaid_id(resource.id)
            label = f"{resource.name}\\n{resource.service} {resource.kind}"
            lines.append(f'    {node_id}["{label}"]')
        lines.append("  end")

    for relationship in manifest.relationships:
        lines.append(
            f"  {_mermaid_id(relationship.source)} -->|{_escape(relationship.label)}| {_mermaid_id(relationship.target)}"
        )

    if manifest.controls:
        lines.append('  subgraph controls["Compliance Controls"]')
        for control in manifest.controls:
            control_id = _mermaid_id(f"control_{control.id}")
            label = f"{control.name}\\n{control.status}"
            lines.append(f'    {control_id}["{label}"]')
            for resource_id in control.resource_ids:
                lines.append(f"    {control_id} -.-> {_mermaid_id(resource_id)}")
        lines.append("  end")

    lines.extend(["```", "", "## Resources", ""])
    for resource in manifest.resources:
        lines.append(
            f"- `{resource.id}`: {resource.service} {resource.kind} ({resource.category})"
        )

    lines.extend(["", "## Controls", ""])
    if manifest.controls:
        for control in manifest.controls:
            lines.append(f"- `{control.id}`: {control.name} - {control.status}")
    else:
        lines.append("- none")

    path.write_text("\n".join(lines) + "\n")


def write_mapping_markdown(mapping: StandardsMappingManifest, path: Path) -> None:
    lines = [
        f"# {mapping.title}",
        "",
        "```mermaid",
        "flowchart LR",
    ]

    for item in mapping.mappings:
        aws_id = _mermaid_id(f"aws_{item.control}")
        gcp_id = _mermaid_id(f"gcp_{item.control}")
        status_id = _mermaid_id(f"status_{item.control}")
        lines.append(
            f'  {aws_id}["AWS: {item.control}\\n{", ".join(item.aws_resources) or "missing"}"]'
        )
        lines.append(
            f'  {gcp_id}["GCP: {item.control}\\n{", ".join(item.gcp_resources) or "missing"}"]'
        )
        lines.append(f'  {status_id}["{item.status}"]')
        lines.append(f"  {aws_id} --> {gcp_id} --> {status_id}")

    lines.extend(["```", "", "## Mappings", ""])
    for item in mapping.mappings:
        lines.append(f"- **{item.control}**: {item.status}. {item.rationale}")

    path.write_text("\n".join(lines) + "\n")


def render_manifest_images(
    manifest: ArchitectureManifest, output_dir: Path, stem: str
) -> list[Path]:
    """Render PNG and SVG diagrams with diagrams/Graphviz."""
    artifacts: list[Path] = []
    for output_format in ("png", "svg"):
        _render_manifest_image(manifest, output_dir / stem, output_format)
        artifacts.append(output_dir / f"{stem}.{output_format}")
    return artifacts


def render_mapping_images(
    mapping: StandardsMappingManifest, output_dir: Path, stem: str
) -> list[Path]:
    artifacts: list[Path] = []
    for output_format in ("png", "svg"):
        _render_mapping_image(mapping, output_dir / stem, output_format)
        artifacts.append(output_dir / f"{stem}.{output_format}")
    return artifacts


def _render_manifest_image(
    manifest: ArchitectureManifest, filename: Path, output_format: str
) -> None:
    try:
        from diagrams import Cluster, Diagram, Edge
        from diagrams.generic.blank import Blank
    except ImportError as exc:
        raise RuntimeError(
            "Install the 'diagrams' package to render PNG/SVG artifacts."
        ) from exc

    graph_attr = {
        "fontsize": "18",
        "pad": "0.5",
        "splines": "ortho",
        "nodesep": "0.65",
        "ranksep": "0.85",
    }
    with Diagram(
        manifest.title,
        filename=str(filename),
        outformat=output_format,
        show=False,
        direction="TB",
        graph_attr=graph_attr,
    ):
        nodes = {}
        for category, resources in _grouped_resources(manifest).items():
            with Cluster(category.title()):
                for resource in resources:
                    node_class = (
                        _node_class(manifest.provider, resource.service, resource.kind)
                        or Blank
                    )
                    nodes[resource.id] = node_class(
                        f"{resource.name}\n{resource.service} {resource.kind}"
                    )
        for relationship in manifest.relationships:
            if relationship.source in nodes and relationship.target in nodes:
                (
                    nodes[relationship.source]
                    >> Edge(label=relationship.label)
                    >> nodes[relationship.target]
                )


def _render_mapping_image(
    mapping: StandardsMappingManifest, filename: Path, output_format: str
) -> None:
    try:
        from diagrams import Diagram, Edge
        from diagrams.generic.blank import Blank
    except ImportError as exc:
        raise RuntimeError(
            "Install the 'diagrams' package to render PNG/SVG artifacts."
        ) from exc

    with Diagram(
        mapping.title,
        filename=str(filename),
        outformat=output_format,
        show=False,
        direction="LR",
    ):
        for item in mapping.mappings:
            aws = Blank(
                f"AWS\n{item.control}\n{', '.join(item.aws_resources) or 'missing'}"
            )
            gcp = Blank(
                f"GCP\n{item.control}\n{', '.join(item.gcp_resources) or 'missing'}"
            )
            status = Blank(item.status)
            (
                aws
                >> Edge(label="standard maps to")
                >> gcp
                >> Edge(label="coverage")
                >> status
            )


def _grouped_resources(manifest: ArchitectureManifest):
    grouped = {}
    for resource in manifest.resources:
        grouped.setdefault(resource.category, []).append(resource)
    return dict(sorted(grouped.items()))


def _node_class(provider: str, service: str, kind: str):
    try:
        if provider == "aws":
            from diagrams.aws.compute import EC2
            from diagrams.aws.database import RDS
            from diagrams.aws.network import ALB, VPC, PrivateSubnet
            from diagrams.aws.security import IAM, KMS
            from diagrams.aws.storage import S3

            return {
                "VPC": VPC,
                "Subnet": PrivateSubnet,
                "LoadBalancer": ALB,
                "Instance": EC2,
                "LaunchTemplate": EC2,
                "Database": RDS,
                "Bucket": S3,
                "Role": IAM,
                "Policy": IAM,
                "ManagedPolicy": IAM,
                "Key": KMS,
            }.get(kind)
        if provider == "gcp":
            from diagrams.gcp.compute import GCE, GKE, Run
            from diagrams.gcp.database import SQL
            from diagrams.gcp.network import FirewallRules, Network
            from diagrams.gcp.security import KMS, Iam
            from diagrams.gcp.storage import GCS

            if service == "Cloud Run":
                return Run
            if service == "GKE":
                return GKE
            return {
                "Network": Network,
                "Subnetwork": Network,
                "Firewall": FirewallRules,
                "Instance": GCE,
                "InstanceTemplate": GCE,
                "Database": SQL,
                "Bucket": GCS,
                "ServiceAccount": Iam,
                "IAMMember": Iam,
                "CryptoKey": KMS,
            }.get(kind)
    except ImportError:
        return None
    return None


def _mermaid_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _escape(value: str) -> str:
    return value.replace('"', "'")
