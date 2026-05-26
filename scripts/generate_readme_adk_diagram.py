#!/usr/bin/env python3
"""Generate the README CloudBridge ADK flow diagram."""

from __future__ import annotations

from pathlib import Path

try:
    from diagrams import Cluster, Diagram, Edge
    from diagrams.aws.management import Cloudformation
    from diagrams.gcp.compute import Run
    from diagrams.gcp.database import SQL
    from diagrams.gcp.devtools import Code
    from diagrams.gcp.ml import VertexAI
    from diagrams.gcp.network import LoadBalancing, VirtualPrivateCloud
    from diagrams.gcp.security import Iam
    from diagrams.gcp.storage import Storage
    from diagrams.onprem.client import Users
    from diagrams.onprem.iac import Terraform
    from diagrams.programming.language import Python
except ModuleNotFoundError as exc:  # pragma: no cover - manual script guard
    raise SystemExit(
        "Missing optional dependency 'diagrams'. Run with:\n"
        "  uv run --with diagrams python scripts/generate_readme_adk_diagram.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = REPO_ROOT / "docs" / "assets"

GRAPH_ATTR = {
    "bgcolor": "#ffffff",
    "pad": "0.5",
    "ranksep": "1.0",
    "nodesep": "0.55",
    "splines": "ortho",
    "fontname": "Helvetica",
    "fontsize": "20",
    "labelloc": "t",
    "labeljust": "c",
}
NODE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "11",
    "fontcolor": "#1f2937",
    "margin": "0.08",
}
EDGE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "10",
    "color": "#64748b",
    "penwidth": "2.0",
    "arrowsize": "0.8",
}

REQUEST = Edge(color="#2563eb", penwidth="2.4")
MODEL_CALL = Edge(color="#7c3aed", style="dashed", penwidth="2.0")
APPROVAL = Edge(color="#16a34a", penwidth="2.4", label="human approval: yes")
OUTPUT = Edge(color="#ea580c", penwidth="2.2")


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    output = ASSET_DIR / "cloudbridge-adk-flow"

    with Diagram(
        "CloudBridge ADK Flow",
        filename=str(output),
        direction="LR",
        curvestyle="ortho",
        outformat=["png", "svg"],
        show=False,
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        team = Users("Team reviewer")

        with Cluster("Inputs"):
            cfn = Cloudformation("CloudFormation\nreference YAML")

        with Cluster("Google ADK app"):
            adk_runtime = Run("ADK Web / Cloud Run\napp")
            root = Python("cloudbridge_architect\nroot agent")

            with Cluster("conversion_pipeline"):
                source = Python("source_loader")
                translator = Python("translator")
                writer = Python("terraform_writer")
                reviewer = Python("compliance_reviewer")
                output_writer = Python("output_writer")

            (
                adk_runtime
                >> REQUEST
                >> root
                >> REQUEST
                >> source
                >> REQUEST
                >> translator
                >> REQUEST
                >> writer
                >> REQUEST
                >> reviewer
                >> REQUEST
                >> output_writer
            )

        with Cluster("Model and review loop"):
            vertex = VertexAI("Vertex AI\nGemini")
            approval = Users("Human review\nreply yes")

        with Cluster("Generated review artifacts"):
            terraform = Terraform("Terraform bundle\nmain/vars/iam/outputs")
            report = Code("Compliance report\narchitecture summary")
            diagrams = Code("Architecture diagrams\nPNG / SVG / Markdown")

        with Cluster("GCP target architecture"):
            lb = LoadBalancing("Load Balancing")
            vpc = VirtualPrivateCloud("VPC")
            sql = SQL("Cloud SQL")
            storage = Storage("Cloud Storage")
            iam = Iam("IAM")

        team >> REQUEST >> cfn >> REQUEST >> adk_runtime
        root >> MODEL_CALL >> vertex
        translator >> MODEL_CALL >> vertex
        writer >> MODEL_CALL >> vertex
        reviewer >> MODEL_CALL >> vertex
        output_writer >> APPROVAL >> approval >> OUTPUT >> terraform
        output_writer >> OUTPUT >> report
        output_writer >> OUTPUT >> diagrams
        terraform >> OUTPUT >> lb >> OUTPUT >> vpc
        terraform >> OUTPUT >> sql
        terraform >> OUTPUT >> storage
        terraform >> OUTPUT >> iam

    print(f"Wrote {output.with_suffix('.svg').relative_to(REPO_ROOT)}")
    print(f"Wrote {output.with_suffix('.png').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
