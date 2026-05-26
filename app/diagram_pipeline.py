"""Post-approval diagram generation pipeline for CloudBridge."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from app.architecture_manifest import (
    ArchitectureManifest,
    StandardsMapping,
    StandardsMappingManifest,
)
from app.diagram_renderers import (
    render_manifest_images,
    render_mapping_images,
    write_manifest_markdown,
    write_mapping_markdown,
)
from app.parsers.cloudformation import parse_cloudformation_path
from app.parsers.terraform import parse_terraform_directory


@dataclass(slots=True)
class DiagramPackage:
    output_dir: Path
    artifacts: list[Path]


def generate_diagram_package(
    aws_reference: Path | str,
    gcp_terraform: Path | str,
    output_dir: Path | str,
    *,
    render_images: bool = True,
    approval_confirmed: bool = False,
) -> DiagramPackage:
    """Generate manifests and diagrams from approved AWS references and GCP Terraform."""
    if not approval_confirmed:
        raise ValueError("Diagram generation must run only after human approval.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    aws_manifest = parse_cloudformation_path(aws_reference)
    gcp_manifest = parse_terraform_directory(gcp_terraform)
    mapping_manifest = build_standards_mapping(aws_manifest, gcp_manifest)

    artifacts: list[Path] = []
    manifest_paths = {
        "aws_reference_manifest.json": aws_manifest,
        "gcp_target_manifest.json": gcp_manifest,
    }
    for filename, manifest in manifest_paths.items():
        path = output_path / filename
        manifest.write_json(path)
        artifacts.append(path)

    mapping_path = output_path / "standards_mapping_manifest.json"
    mapping_manifest.write_json(mapping_path)
    artifacts.append(mapping_path)

    markdown_outputs = [
        (output_path / "aws_reference_diagram.md", aws_manifest),
        (output_path / "gcp_target_diagram.md", gcp_manifest),
    ]
    for path, manifest in markdown_outputs:
        write_manifest_markdown(manifest, path)
        artifacts.append(path)

    mapping_md = output_path / "standards_mapping_diagram.md"
    write_mapping_markdown(mapping_manifest, mapping_md)
    artifacts.append(mapping_md)

    index = output_path / "diagram_package.md"
    index.write_text(_index_markdown(artifacts) + "\n")
    artifacts.append(index)

    if render_images:
        artifacts.extend(
            render_manifest_images(aws_manifest, output_path, "aws_reference_diagram")
        )
        artifacts.extend(
            render_manifest_images(gcp_manifest, output_path, "gcp_target_diagram")
        )
        artifacts.extend(
            render_mapping_images(
                mapping_manifest, output_path, "standards_mapping_diagram"
            )
        )

    return DiagramPackage(output_dir=output_path, artifacts=artifacts)


def build_standards_mapping(
    aws_manifest: ArchitectureManifest,
    gcp_manifest: ArchitectureManifest,
) -> StandardsMappingManifest:
    aws_controls = {control.name: control for control in aws_manifest.controls}
    gcp_controls = {control.name: control for control in gcp_manifest.controls}
    controls = sorted(set(aws_controls) | set(gcp_controls))

    mappings: list[StandardsMapping] = []
    for control in controls:
        aws_control = aws_controls.get(control)
        gcp_control = gcp_controls.get(control)
        status = "mapped"
        if aws_control and not gcp_control:
            status = "missing-target"
        elif gcp_control and not aws_control:
            status = "missing-reference"
        elif not aws_control or not gcp_control:
            status = "review"

        mappings.append(
            StandardsMapping(
                control=control,
                aws_resources=aws_control.resource_ids if aws_control else [],
                gcp_resources=gcp_control.resource_ids if gcp_control else [],
                rationale=_mapping_rationale(control),
                status=status,
            )
        )

    return StandardsMappingManifest(
        title="AWS-to-GCP Standards Mapping",
        aws_reference=aws_manifest.title,
        gcp_target=gcp_manifest.title,
        mappings=mappings,
        notes=[
            "AWS resources are standards references, not deployment targets.",
            "GCP resources represent the approved target architecture.",
            "DSPy can later enrich manifests or evaluate diagram quality, but rendering is deterministic.",
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate CloudBridge post-approval architecture diagrams."
    )
    parser.add_argument(
        "--aws-reference",
        required=True,
        help="Approved AWS CloudFormation reference template.",
    )
    parser.add_argument(
        "--gcp-terraform",
        required=True,
        help="Approved GCP Terraform file or directory.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory for manifests and diagram artifacts.",
    )
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Confirm a human approved the Terraform inputs.",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Write JSON/Markdown artifacts without PNG/SVG.",
    )
    args = parser.parse_args(argv)

    package = generate_diagram_package(
        aws_reference=args.aws_reference,
        gcp_terraform=args.gcp_terraform,
        output_dir=args.out,
        render_images=not args.no_images,
        approval_confirmed=args.approved,
    )
    for artifact in package.artifacts:
        print(artifact)
    return 0


def _mapping_rationale(control: str) -> str:
    rationales = {
        "Private database access": "AWS private database posture maps to Cloud SQL private IP.",
        "Storage protection": "AWS S3 protection maps to GCS UBLA and versioning.",
        "Network segmentation": "AWS VPC/subnet boundaries map to GCP VPC/subnetwork boundaries.",
        "IAM least privilege boundary": "AWS IAM boundaries map to service accounts and scoped IAM grants.",
        "Database protection": "Database lifecycle protection maps to Cloud SQL deletion protection.",
        "Database encryption": "Database encryption intent maps to managed Google Cloud encryption controls.",
    }
    return rationales.get(
        control, "Control should be reviewed against the target GCP architecture."
    )


def _index_markdown(artifacts: list[Path]) -> str:
    lines = ["# CloudBridge Diagram Package", "", "Generated artifacts:", ""]
    for artifact in artifacts:
        lines.append(f"- `{artifact.name}`")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
