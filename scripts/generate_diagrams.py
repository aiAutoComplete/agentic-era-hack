#!/usr/bin/env python3
"""Generate beautiful AWS/GCP architecture diagrams for CloudBridge inputs.

This is intentionally separate from the ADK app so the working playground flow
is not affected. Run it manually with:

    uv run --with diagrams python scripts/generate_diagrams.py --all
    uv run --with diagrams python scripts/generate_diagrams.py input/lambda-reverse-proxy.yaml

Outputs are written to output/diagrams as PNG and SVG.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from diagrams import Cluster, Diagram, Edge
    from diagrams.aws.compute import EC2, Lambda
    from diagrams.aws.database import RDS, Dynamodb
    from diagrams.aws.integration import SQS
    from diagrams.aws.network import (
        ELB,
        VPC,
        APIGateway,
        CloudFront,
        PrivateSubnet,
        PublicSubnet,
    )
    from diagrams.aws.security import IAMRole
    from diagrams.aws.storage import S3
    from diagrams.gcp.analytics import PubSub
    from diagrams.gcp.compute import GCE, Functions, Run
    from diagrams.gcp.database import SQL, Firestore
    from diagrams.gcp.network import CDN, FirewallRules, LoadBalancing
    from diagrams.gcp.network import VPC as GcpVPC
    from diagrams.gcp.security import Iam
    from diagrams.gcp.storage import GCS
    from diagrams.onprem.client import Users
    from diagrams.onprem.network import Internet
except ModuleNotFoundError as exc:  # pragma: no cover - manual script guard
    raise SystemExit(
        "Missing optional dependency 'diagrams'. Run with:\n"
        "  uv run --with diagrams python scripts/generate_diagrams.py --all"
    ) from exc

from app.parser import parse_cfn

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"
OUTPUT_DIR = REPO_ROOT / "output" / "diagrams"

GRAPH_ATTR = {
    "bgcolor": "#ffffff",
    "pad": "0.45",
    "ranksep": "1.0",
    "nodesep": "0.55",
    "splines": "ortho",
    "fontname": "Helvetica",
    "fontsize": "18",
    "labelloc": "t",
    "labeljust": "c",
}
NODE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "12",
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
AWS_EDGE = Edge(color="#ff9900", penwidth="2.4")
GCP_EDGE = Edge(color="#4285f4", penwidth="2.4")
MAPPING_EDGE = Edge(color="#7c3aed", style="dashed", penwidth="2.0", label="maps to")


@dataclass(frozen=True)
class TemplateShape:
    path: Path
    slug: str
    title: str
    aws_types: set[str]

    def has(self, aws_type: str) -> bool:
        return aws_type in self.aws_types


def slugify(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()
    return value or "diagram"


def load_shape(path: Path) -> TemplateShape:
    parsed = parse_cfn(path.read_text())
    resources = [*parsed.resources, *parsed.unsupported]
    aws_types = {resource.aws_type for resource in resources}
    title = path.stem.replace("-", " ").title()
    return TemplateShape(
        path=path, slug=slugify(path.stem), title=title, aws_types=aws_types
    )


def is_static_site(shape: TemplateShape) -> bool:
    return shape.has("AWS::CloudFront::Distribution") and shape.has("AWS::S3::Bucket")


def is_lambda_proxy(shape: TemplateShape) -> bool:
    return shape.has("AWS::ApiGatewayV2::Api") and shape.has("AWS::Lambda::Function")


def is_event_pipeline(shape: TemplateShape) -> bool:
    return shape.has("AWS::SQS::Queue") and shape.has("AWS::DynamoDB::Table")


def is_three_tier(shape: TemplateShape) -> bool:
    return shape.has("AWS::EC2::VPC") and shape.has("AWS::RDS::DBInstance")


def diagram_kwargs(title: str, filename: Path) -> dict:
    return {
        "name": title,
        "filename": str(filename),
        "direction": "LR",
        "curvestyle": "ortho",
        "outformat": ["png", "svg"],
        "show": False,
        "graph_attr": GRAPH_ATTR,
        "node_attr": NODE_ATTR,
        "edge_attr": EDGE_ATTR,
    }


def render_aws(shape: TemplateShape, out_dir: Path) -> list[Path]:
    base = out_dir / f"aws-{shape.slug}"
    with Diagram(**diagram_kwargs(f"AWS Source Architecture — {shape.title}", base)):
        user = Users("Users")
        if is_static_site(shape):
            with Cluster("AWS Static Website"):
                cdn = CloudFront("CloudFront\nDistribution")
                bucket = S3("Private S3\nContent Bucket")
                iam = IAMRole("OAC + Bucket\nPolicy")
            user >> AWS_EDGE >> cdn >> AWS_EDGE >> bucket
            iam >> Edge(color="#64748b", style="dotted", label="read access") >> bucket
        elif is_lambda_proxy(shape):
            with Cluster("AWS Serverless Reverse Proxy"):
                api = APIGateway("API Gateway\nHTTP API")
                fn = Lambda("Lambda\nReverse Proxy")
                role = IAMRole("Execution\nRole")
                upstream = Internet("Upstream\nService")
            user >> AWS_EDGE >> api >> AWS_EDGE >> fn >> AWS_EDGE >> upstream
            role >> Edge(color="#64748b", style="dotted", label="logs") >> fn
        elif is_event_pipeline(shape):
            with Cluster("AWS Event Ingestion"):
                bucket = S3("Inbound S3\nBucket")
                queue = SQS("SQS Queue\n+ DLQ")
                fn = Lambda("Lambda\nProcessor")
                db = Dynamodb("DynamoDB\nMetadata")
                role = IAMRole("Processor\nRole")
            (
                user
                >> AWS_EDGE
                >> bucket
                >> AWS_EDGE
                >> queue
                >> AWS_EDGE
                >> fn
                >> AWS_EDGE
                >> db
            )
            role >> Edge(color="#64748b", style="dotted", label="least privilege") >> fn
        elif is_three_tier(shape):
            with Cluster("AWS Three-Tier VPC"):
                vpc = VPC("VPC")
                public = PublicSubnet("Public Web\nSubnet")
                private = PrivateSubnet("Private App/DB\nSubnets")
                web = EC2("EC2 / Launch\nTemplate")
                db = RDS("RDS PostgreSQL")
                bucket = S3("S3 Content\nBucket")
            (
                user
                >> AWS_EDGE
                >> ELB("Web Entry")
                >> AWS_EDGE
                >> public
                >> AWS_EDGE
                >> web
                >> AWS_EDGE
                >> private
                >> AWS_EDGE
                >> db
            )
            vpc >> Edge(color="#64748b", style="dotted") >> public
            web >> Edge(color="#64748b", style="dotted") >> bucket
        else:
            with Cluster("AWS Source"):
                aws = S3("CloudFormation\nResources")
                notes = IAMRole("IAM / Service\nPermissions")
            user >> AWS_EDGE >> aws >> Edge(color="#64748b") >> notes
    return [base.with_suffix(".png"), base.with_suffix(".svg")]


def render_gcp(shape: TemplateShape, out_dir: Path) -> list[Path]:
    base = out_dir / f"gcp-{shape.slug}"
    with Diagram(**diagram_kwargs(f"GCP Target Architecture — {shape.title}", base)):
        user = Users("Users")
        if is_static_site(shape):
            with Cluster("Google Cloud Static Site"):
                cdn = CDN("Cloud CDN")
                lb = LoadBalancing("HTTPS Load\nBalancer")
                bucket = GCS("Cloud Storage\nProtected Bucket")
                iam = Iam("IAM: storage\nviewer only")
            user >> GCP_EDGE >> cdn >> GCP_EDGE >> lb >> GCP_EDGE >> bucket
            iam >> Edge(color="#64748b", style="dotted", label="restricted") >> bucket
        elif is_lambda_proxy(shape):
            with Cluster("Google Cloud Reverse Proxy"):
                api = LoadBalancing("HTTPS LB /\nAPI Gateway")
                run = Run("Cloud Run\nReverse Proxy")
                iam = Iam("Service\nAccount")
                upstream = Internet("Upstream\nService")
            user >> GCP_EDGE >> api >> GCP_EDGE >> run >> GCP_EDGE >> upstream
            iam >> Edge(color="#64748b", style="dotted", label="logs only") >> run
        elif is_event_pipeline(shape):
            with Cluster("Google Cloud Event Pipeline"):
                bucket = GCS("Cloud Storage\nInbound Bucket")
                topic = PubSub("Pub/Sub\nTopic")
                fn = Functions("Cloud Function\nProcessor")
                db = Firestore("Firestore\nMetadata")
                iam = Iam("Service\nAccount")
            (
                user
                >> GCP_EDGE
                >> bucket
                >> GCP_EDGE
                >> topic
                >> GCP_EDGE
                >> fn
                >> GCP_EDGE
                >> db
            )
            iam >> Edge(color="#64748b", style="dotted", label="least privilege") >> fn
        elif is_three_tier(shape):
            with Cluster("Google Cloud Three-Tier Network"):
                vpc = GcpVPC("VPC Network")
                lb = LoadBalancing("HTTPS Load\nBalancer")
                vm = GCE("Compute Engine\n/ Template")
                sql = SQL("Cloud SQL\nPostgreSQL")
                bucket = GCS("Cloud Storage\nProtected Bucket")
                fw = FirewallRules("Firewall\nRules")
            user >> GCP_EDGE >> lb >> GCP_EDGE >> vm >> GCP_EDGE >> sql
            (
                vpc
                >> Edge(color="#64748b", style="dotted")
                >> fw
                >> Edge(color="#64748b", style="dotted")
                >> vm
            )
            vm >> Edge(color="#64748b", style="dotted") >> bucket
        else:
            with Cluster("Google Cloud Target"):
                run = Run("Cloud Run /\nCloud Functions")
                store = GCS("Cloud Storage")
                iam = Iam("Least-Privilege\nIAM")
            user >> GCP_EDGE >> run >> GCP_EDGE >> store
            iam >> Edge(color="#64748b", style="dotted") >> run
    return [base.with_suffix(".png"), base.with_suffix(".svg")]


def render_conversion(shape: TemplateShape, out_dir: Path) -> list[Path]:
    base = out_dir / f"conversion-{shape.slug}"
    with Diagram(
        **diagram_kwargs(f"CloudBridge AWS → GCP Conversion — {shape.title}", base)
    ):
        user = Users("Users")
        with Cluster("AWS source"):
            if is_static_site(shape):
                aws_entry = CloudFront("CloudFront")
                aws_core = S3("S3 Site Bucket")
            elif is_lambda_proxy(shape):
                aws_entry = APIGateway("API Gateway")
                aws_core = Lambda("Lambda Proxy")
            elif is_event_pipeline(shape):
                aws_entry = S3("S3 Events")
                aws_core = SQS("SQS + Lambda")
            elif is_three_tier(shape):
                aws_entry = EC2("EC2 App")
                aws_core = RDS("RDS PostgreSQL")
            else:
                aws_entry = S3("CloudFormation")
                aws_core = IAMRole("AWS Resources")
            aws_entry >> AWS_EDGE >> aws_core

        with Cluster("CloudBridge agents"):
            loader = Run("source_loader")
            mapper = Run("translator")
            writer = Run("terraform_writer")
            review = Run("compliance_reviewer")
            (
                loader
                >> Edge(color="#7c3aed")
                >> mapper
                >> Edge(color="#7c3aed")
                >> writer
                >> Edge(color="#7c3aed")
                >> review
            )

        with Cluster("GCP target"):
            if is_static_site(shape):
                gcp_entry = CDN("Cloud CDN")
                gcp_core = GCS("Cloud Storage")
            elif is_lambda_proxy(shape):
                gcp_entry = LoadBalancing("HTTPS LB / API")
                gcp_core = Run("Cloud Run Proxy")
            elif is_event_pipeline(shape):
                gcp_entry = GCS("Cloud Storage")
                gcp_core = PubSub("Pub/Sub + Function")
            elif is_three_tier(shape):
                gcp_entry = GCE("Compute Engine")
                gcp_core = SQL("Cloud SQL")
            else:
                gcp_entry = Run("Cloud Run")
                gcp_core = GCS("Cloud Storage")
            gcp_entry >> GCP_EDGE >> gcp_core

        user >> AWS_EDGE >> aws_entry
        aws_core >> MAPPING_EDGE >> loader
        review >> MAPPING_EDGE >> gcp_entry
    return [base.with_suffix(".png"), base.with_suffix(".svg")]


def write_index(paths: list[Path], out_dir: Path) -> Path:
    by_input: dict[str, list[Path]] = {}
    for path in paths:
        key = path.name.split("-", 1)[1].rsplit(".", 1)[0]
        by_input.setdefault(key, []).append(path)

    lines = [
        "# CloudBridge Generated Architecture Diagrams",
        "",
        "Generated by `scripts/generate_diagrams.py` using Graphviz and the Python `diagrams` package.",
        "",
        "These diagrams are optional artifacts and are not part of the ADK runtime path.",
        "",
    ]
    for key in sorted(by_input):
        lines.extend([f"## {key}", ""])
        for path in sorted(by_input[key]):
            rel = path.relative_to(REPO_ROOT)
            lines.append(f"- `{rel}`")
        lines.append("")
    index = out_dir / "README.md"
    index.write_text("\n".join(lines))
    return index


def generate(paths: list[Path], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for path in paths:
        shape = load_shape(path)
        generated.extend(render_aws(shape, out_dir))
        generated.extend(render_gcp(shape, out_dir))
        generated.extend(render_conversion(shape, out_dir))
    generated.append(write_index(generated, out_dir))
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate CloudBridge AWS/GCP architecture diagrams."
    )
    parser.add_argument(
        "templates",
        nargs="*",
        type=Path,
        help="CloudFormation template paths under input/.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate diagrams for every input/*.yaml template.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory. Default: output/diagrams",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all:
        templates = sorted(INPUT_DIR.glob("*.yaml"))
    elif args.templates:
        templates = args.templates
    else:
        templates = sorted(INPUT_DIR.glob("*.yaml"))

    templates = [
        (REPO_ROOT / p).resolve() if not p.is_absolute() else p.resolve()
        for p in templates
    ]
    for template in templates:
        if not template.exists():
            raise SystemExit(f"Template not found: {template}")

    generated = generate(templates, args.out_dir)
    print("Generated diagrams:")
    for path in generated:
        print(
            f"- {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}"
        )


if __name__ == "__main__":
    main()
