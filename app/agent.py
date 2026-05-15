# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""CloudBridge ADK app.

CloudBridge turns a small AWS CloudFormation template into a first-pass Google
Cloud Terraform bundle and a concise compliance report.  This file keeps the
Google Agent Starter Pack shape (`root_agent` plus `app = App(...)`) while
adding the CloudBridge parser, deterministic conversion tools, specialist
sub-agents, and local input/output helpers described in README.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.auth.exceptions import DefaultCredentialsError
from google.genai import types
from pydantic import BaseModel, Field

# Preserve the generated Google Cloud/Vertex configuration, but make imports
# work on a laptop that does not yet have ADC configured.
try:
    _, project_id = google.auth.default()
except DefaultCredentialsError:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "cloudbridge-local")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

MODEL_NAME = os.getenv("CLOUDBRIDGE_MODEL", "gemini-3-flash-preview")
REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"
OUTPUT_DIR = REPO_ROOT / "output"

SUPPORTED_TYPES: dict[str, str] = {
    "AWS::EC2::VPC": "google_compute_network",
    "AWS::EC2::Subnet": "google_compute_subnetwork",
    "AWS::EC2::SecurityGroup": "google_compute_firewall",
    "AWS::EC2::Instance": "google_compute_instance",
    "AWS::EC2::LaunchTemplate": "google_compute_instance_template",
    "AWS::RDS::DBInstance": "google_sql_database_instance",
    "AWS::S3::Bucket": "google_storage_bucket",
    "AWS::IAM::Role": "google_service_account",
    "AWS::IAM::Policy": "google_project_iam_member",
    "AWS::IAM::ManagedPolicy": "google_project_iam_member",
}


class ParsedResource(BaseModel):
    logical_id: str
    aws_type: str
    gcp_target: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ResourceList(BaseModel):
    resources: list[ParsedResource]
    unsupported: list[ParsedResource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MappingItem(BaseModel):
    aws_logical_id: str
    aws_type: str
    gcp_resource_type: str
    gcp_name: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)


class TranslationPlan(BaseModel):
    mappings: list[MappingItem]
    iam_bindings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TerraformBundle(BaseModel):
    main_tf: str
    variables_tf: str = ""
    iam_tf: str = ""
    outputs_tf: str = ""
    architecture_summary_md: str = ""


class ComplianceFinding(BaseModel):
    rule_id: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    resource: str
    issue: str
    recommended_fix: str


class ComplianceResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    findings: list[ComplianceFinding] = Field(default_factory=list)


class FinalPackage(BaseModel):
    files: dict[str, str]
    compliance: ComplianceResult
    parsed: ResourceList | None = None
    translation: TranslationPlan | None = None
    output_dir: str | None = None


def _snake(name: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower().strip("_")
    return value or "resource"


def _tf_ref(value: Any) -> str | None:
    """Return a CloudFormation reference logical id when our YAML loader flattens it."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("Ref", "Fn::Ref"):
            if key in value:
                return str(value[key])
    return None


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return str(value)
    return default


def _load_template(template_text: str) -> dict[str, Any]:
    """Load CloudFormation JSON/YAML. Unknown tags like !Ref are kept readable."""
    try:
        return json.loads(template_text)
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
        return loaded or {}
    except Exception as exc:
        raise ValueError(f"Template must be valid JSON or YAML: {exc}") from exc


def parse_cfn(node_input: str | dict[str, Any]) -> ResourceList:
    """Parse CloudFormation into supported and unsupported resource lists."""
    if isinstance(node_input, dict):
        template_text = node_input.get("template") or node_input.get("message") or json.dumps(node_input)
    else:
        template_text = node_input

    template = _load_template(template_text)
    resources = template.get("Resources", {})
    if not isinstance(resources, dict):
        raise ValueError("CloudFormation template must contain a Resources mapping.")

    supported: list[ParsedResource] = []
    unsupported: list[ParsedResource] = []
    warnings: list[str] = []

    for logical_id, body in resources.items():
        if not isinstance(body, dict):
            warnings.append(f"Skipped {logical_id}: resource body is not an object.")
            continue
        aws_type = str(body.get("Type", ""))
        properties = body.get("Properties", {}) if isinstance(body.get("Properties", {}), dict) else {}
        item = ParsedResource(
            logical_id=str(logical_id),
            aws_type=aws_type,
            gcp_target=SUPPORTED_TYPES.get(aws_type),
            properties=properties,
        )
        if item.gcp_target:
            supported.append(item)
        else:
            unsupported.append(item)
            warnings.append(f"Unsupported for MVP: {logical_id} ({aws_type})")

    return ResourceList(resources=supported, unsupported=unsupported, warnings=warnings)


def parse_cloudformation_tool(template: str) -> dict[str, Any]:
    """ADK tool: parse a pasted CloudFormation YAML/JSON template."""
    return parse_cfn(template).model_dump()


def read_input_template(filename: str = "sample-three-tier.yaml") -> str:
    """ADK tool: read a template from the local input/ directory."""
    safe_name = Path(filename).name
    path = INPUT_DIR / safe_name
    if not path.exists():
        available = sorted(p.name for p in INPUT_DIR.glob("*.y*ml")) if INPUT_DIR.exists() else []
        raise FileNotFoundError(f"No input template named {safe_name}. Available: {available}")
    return path.read_text()


def service_mapping_catalog() -> dict[str, str]:
    """ADK tool: return the fixed MVP AWS-to-GCP mapping catalog."""
    return SUPPORTED_TYPES


def _mapping_for_resource(resource: ParsedResource) -> MappingItem:
    gcp_type = resource.gcp_target or "unsupported"
    return MappingItem(
        aws_logical_id=resource.logical_id,
        aws_type=resource.aws_type,
        gcp_resource_type=gcp_type,
        gcp_name=_snake(resource.logical_id),
        rationale=f"{resource.aws_type} maps to {gcp_type} for the CloudBridge MVP.",
        assumptions=[
            "Generated Terraform is starter code for review, not an automatic production deployment.",
            "Region, project, naming, and CIDR choices should be verified by the migration team.",
        ],
    )


def translate_resources(parsed: ResourceList | dict[str, Any]) -> TranslationPlan:
    """Create a deterministic first-pass AWS-to-GCP architecture mapping."""
    if isinstance(parsed, dict):
        parsed = ResourceList.model_validate(parsed)

    mappings = [_mapping_for_resource(resource) for resource in parsed.resources]
    iam_bindings: list[dict[str, Any]] = []
    for resource in parsed.resources:
        if resource.aws_type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}:
            iam_bindings.append(
                {
                    "source": resource.logical_id,
                    "member": "serviceAccount:${google_service_account.app.email}",
                    "roles": ["roles/logging.logWriter", "roles/storage.objectViewer"],
                }
            )

    return TranslationPlan(mappings=mappings, iam_bindings=iam_bindings, warnings=parsed.warnings)


def translate_resources_tool(parsed_json: dict[str, Any]) -> dict[str, Any]:
    """ADK tool: convert parsed resources into a GCP mapping plan."""
    return translate_resources(parsed_json).model_dump()


def _emit_header() -> list[str]:
    return [
        "terraform {",
        "  required_version = \">= 1.5.0\"",
        "  required_providers {",
        "    google = {",
        "      source  = \"hashicorp/google\"",
        "      version = \"~> 6.0\"",
        "    }",
        "  }",
        "}",
        "",
        "provider \"google\" {",
        "  project = var.project_id",
        "  region  = var.region",
        "}",
        "",
    ]


def generate_terraform(parsed: ResourceList | dict[str, Any]) -> TerraformBundle:
    """Generate deterministic starter Terraform for supported MVP resources."""
    if isinstance(parsed, dict):
        parsed = ResourceList.model_validate(parsed)

    main: list[str] = _emit_header()
    iam: list[str] = []
    outputs: list[str] = []
    summary: list[str] = [
        "# CloudBridge architecture summary",
        "",
        "This starter bundle was generated from an AWS CloudFormation template.",
        "It maps supported AWS resources to Google Cloud equivalents for review.",
        "",
        "## Resource mapping",
        "",
        "| AWS logical id | AWS type | GCP Terraform target |",
        "| --- | --- | --- |",
    ]

    network_by_logical: dict[str, str] = {}
    subnet_by_logical: dict[str, str] = {}
    service_account_emitted = False
    first_service_account_name = "app_service_account"

    for resource in parsed.resources:
        tf_name = _snake(resource.logical_id)
        props = resource.properties
        gcp = resource.gcp_target or "unsupported"
        summary.append(f"| `{resource.logical_id}` | `{resource.aws_type}` | `{gcp}` |")

        if resource.aws_type == "AWS::EC2::VPC":
            network_by_logical[resource.logical_id] = tf_name
            main.extend(
                [
                    f'resource "google_compute_network" "{tf_name}" {{',
                    f'  name                    = "${{var.name_prefix}}-{tf_name}"',
                    "  auto_create_subnetworks = false",
                    "  routing_mode            = \"REGIONAL\"",
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_network_self_link" {{',
                    f"  value = google_compute_network.{tf_name}.self_link",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::EC2::Subnet":
            subnet_by_logical[resource.logical_id] = tf_name
            vpc_ref = _tf_ref(props.get("VpcId"))
            network_name = network_by_logical.get(vpc_ref or "", "main_vpc")
            cidr = _string(props.get("CidrBlock"), "10.0.0.0/24")
            private_access = "true" if "private" in resource.logical_id.lower() else "false"
            main.extend(
                [
                    f'resource "google_compute_subnetwork" "{tf_name}" {{',
                    f'  name                     = "${{var.name_prefix}}-{tf_name}"',
                    f'  ip_cidr_range            = "{cidr}"',
                    "  region                   = var.region",
                    f"  network                  = google_compute_network.{network_name}.id",
                    f"  private_ip_google_access = {private_access}",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::EC2::SecurityGroup":
            vpc_ref = _tf_ref(props.get("VpcId"))
            network_name = network_by_logical.get(vpc_ref or "", "main_vpc")
            main.extend(
                [
                    f'resource "google_compute_firewall" "{tf_name}_internal" {{',
                    f'  name    = "${{var.name_prefix}}-{tf_name}-internal"',
                    f"  network = google_compute_network.{network_name}.name",
                    "",
                    "  allow {",
                    "    protocol = \"tcp\"",
                    "    ports    = [\"80\", \"443\", \"5432\"]",
                    "  }",
                    "",
                    "  source_ranges = [\"10.0.0.0/8\"]",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type in {"AWS::EC2::Instance", "AWS::EC2::LaunchTemplate"}:
            subnet_ref = _tf_ref(props.get("SubnetId")) or next(iter(subnet_by_logical.keys()), "")
            subnet_name = subnet_by_logical.get(subnet_ref, next(iter(subnet_by_logical.values()), "private_app_subnet"))
            image = "debian-cloud/debian-12"
            instance_type = _string(props.get("InstanceType"), "e2-medium")
            if resource.aws_type == "AWS::EC2::LaunchTemplate":
                launch_data = props.get("LaunchTemplateData", {}) if isinstance(props.get("LaunchTemplateData"), dict) else {}
                instance_type = _string(launch_data.get("InstanceType"), "e2-medium")
                main.extend(
                    [
                        f'resource "google_compute_instance_template" "{tf_name}" {{',
                        f'  name_prefix  = "${{var.name_prefix}}-{tf_name}-"',
                        f'  machine_type = "{instance_type if instance_type.startswith("e2-") else "e2-medium"}"',
                        "",
                        "  disk {",
                        f'    source_image = "{image}"',
                        "    auto_delete  = true",
                        "    boot         = true",
                        "  }",
                        "",
                        "  network_interface {",
                        f"    subnetwork = google_compute_subnetwork.{subnet_name}.id",
                        "  }",
                        "}",
                        "",
                    ]
                )
            else:
                main.extend(
                    [
                        f'resource "google_compute_instance" "{tf_name}" {{',
                        f'  name         = "${{var.name_prefix}}-{tf_name}"',
                        f'  machine_type = "{instance_type if instance_type.startswith("e2-") else "e2-medium"}"',
                        "  zone         = var.zone",
                        "",
                        "  boot_disk {",
                        "    initialize_params {",
                        f'      image = "{image}"',
                        "    }",
                        "  }",
                        "",
                        "  network_interface {",
                        f"    subnetwork = google_compute_subnetwork.{subnet_name}.id",
                        "  }",
                        "}",
                        "",
                    ]
                )

        elif resource.aws_type == "AWS::RDS::DBInstance":
            engine_version = _string(props.get("EngineVersion"), "POSTGRES_15")
            if engine_version and not engine_version.upper().startswith("POSTGRES"):
                engine_version = f"POSTGRES_{engine_version.split('.')[0]}"
            main.extend(
                [
                    f'resource "google_sql_database_instance" "{tf_name}" {{',
                    f'  name             = "${{var.name_prefix}}-{tf_name}"',
                    f'  database_version = "{engine_version or "POSTGRES_15"}"',
                    "  region           = var.region",
                    "",
                    "  settings {",
                    "    tier              = \"db-custom-1-3840\"",
                    "    availability_type = \"REGIONAL\"",
                    "    backup_configuration {",
                    "      enabled                        = true",
                    "      point_in_time_recovery_enabled = true",
                    "    }",
                    "    ip_configuration {",
                    "      ipv4_enabled    = false",
                    f"      private_network = google_compute_network.{next(iter(network_by_logical.values()), 'main_vpc')}.id",
                    "    }",
                    "  }",
                    "",
                    "  deletion_protection = true",
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_connection_name" {{',
                    f"  value = google_sql_database_instance.{tf_name}.connection_name",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::S3::Bucket":
            main.extend(
                [
                    f'resource "google_storage_bucket" "{tf_name}" {{',
                    f'  name                        = "${{var.project_id}}-${{var.name_prefix}}-{tf_name}"',
                    "  location                    = var.region",
                    "  uniform_bucket_level_access = true",
                    "  public_access_prevention    = \"enforced\"",
                    "  force_destroy               = false",
                    "",
                    "  versioning {",
                    "    enabled = true",
                    "  }",
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_bucket_name" {{',
                    f"  value = google_storage_bucket.{tf_name}.name",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::IAM::Role":
            service_account_emitted = True
            first_service_account_name = tf_name
            iam.extend(
                [
                    f'resource "google_service_account" "{tf_name}" {{',
                    f'  account_id   = "${{var.name_prefix}}-{tf_name}"',
                    f'  display_name = "Service account migrated from {resource.logical_id}"',
                    "}",
                    "",
                    f'resource "google_project_iam_member" "{tf_name}_logging" {{',
                    "  project = var.project_id",
                    "  role    = \"roles/logging.logWriter\"",
                    f'  member  = "serviceAccount:${{google_service_account.{tf_name}.email}}"',
                    "}",
                    "",
                ]
            )

        elif resource.aws_type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}:
            role_name = first_service_account_name
            if not service_account_emitted:
                service_account_emitted = True
                role_name = "app_service_account"
                first_service_account_name = role_name
                iam.extend(
                    [
                        'resource "google_service_account" "app_service_account" {',
                        '  account_id   = "${var.name_prefix}-app"',
                        '  display_name = "Application service account"',
                        "}",
                        "",
                    ]
                )
            iam.extend(
                [
                    f'resource "google_project_iam_member" "{tf_name}_storage_viewer" {{',
                    "  project = var.project_id",
                    "  role    = \"roles/storage.objectViewer\"",
                    f'  member  = "serviceAccount:${{google_service_account.{role_name}.email}}"',
                    "}",
                    "",
                ]
            )

    variables_tf = """variable "project_id" {
  description = "Google Cloud project id."
  type        = string
}

variable "region" {
  description = "Google Cloud region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Google Cloud zone for zonal Compute Engine resources."
  type        = string
  default     = "us-central1-a"
}

variable "name_prefix" {
  description = "Short, lowercase prefix for generated resource names."
  type        = string
  default     = "cloudbridge"
}
"""

    if parsed.warnings:
        summary.extend(["", "## Parser warnings", ""])
        summary.extend(f"- {warning}" for warning in parsed.warnings)

    summary.extend(
        [
            "",
            "## Review notes",
            "",
            "- Validate networking, routing, and private service access before applying.",
            "- Replace starter machine tiers with workload-appropriate sizing.",
            "- Review IAM bindings against least-privilege requirements.",
        ]
    )

    return TerraformBundle(
        main_tf="\n".join(main).rstrip() + "\n",
        variables_tf=variables_tf,
        iam_tf="\n".join(iam).rstrip() + ("\n" if iam else ""),
        outputs_tf="\n".join(outputs).rstrip() + ("\n" if outputs else ""),
        architecture_summary_md="\n".join(summary).rstrip() + "\n",
    )


def generate_terraform_tool(parsed_json: dict[str, Any]) -> dict[str, Any]:
    """ADK tool: generate Terraform files from parsed CloudFormation resources."""
    return generate_terraform(parsed_json).model_dump()


def compliance_check(node_input: TerraformBundle | dict[str, Any] | str) -> ComplianceResult:
    """Run the README compliance checks against generated Terraform."""
    if isinstance(node_input, TerraformBundle):
        text = "\n".join([node_input.main_tf, node_input.iam_tf, node_input.variables_tf, node_input.outputs_tf])
    elif isinstance(node_input, dict):
        text = "\n".join(str(v) for v in node_input.values())
    else:
        text = node_input

    findings: list[ComplianceFinding] = []
    lower = text.lower()

    if re.search(r"roles/(owner|editor|iam\.securityadmin)", lower) or ("*" in lower and "iam" in lower):
        findings.append(
            ComplianceFinding(
                rule_id="IAM_NO_WILDCARD",
                severity="HIGH",
                resource="iam.tf",
                issue="Broad IAM role or wildcard-like permission detected.",
                recommended_fix="Use least-privilege predefined roles such as roles/storage.objectViewer or roles/cloudsql.client.",
            )
        )

    if "google_sql_database_instance" in lower and ("ipv4_enabled = true" in lower or "authorized_networks" in lower):
        findings.append(
            ComplianceFinding(
                rule_id="DB_NO_PUBLIC_IP",
                severity="HIGH",
                resource="Cloud SQL",
                issue="Cloud SQL appears to allow public IP or authorized public networks.",
                recommended_fix="Set ipv4_enabled = false and use private IP connectivity.",
            )
        )

    if "google_storage_bucket" in lower and "uniform_bucket_level_access" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="STORAGE_DEFAULT_PROTECTION",
                severity="MEDIUM",
                resource="Cloud Storage",
                issue="Bucket is missing uniform bucket-level access in generated Terraform.",
                recommended_fix="Add uniform_bucket_level_access = true to every google_storage_bucket.",
            )
        )

    if "google_storage_bucket" in lower and "public_access_prevention" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="STORAGE_PUBLIC_ACCESS_PREVENTION",
                severity="MEDIUM",
                resource="Cloud Storage",
                issue="Bucket is missing public access prevention.",
                recommended_fix='Add public_access_prevention = "enforced" to every google_storage_bucket.',
            )
        )

    if "google_sql_database_instance" in lower and "backup_configuration" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="DB_BACKUPS_REQUIRED",
                severity="MEDIUM",
                resource="Cloud SQL",
                issue="Cloud SQL backup settings are not documented or enabled.",
                recommended_fix="Enable backup_configuration and point-in-time recovery for Cloud SQL.",
            )
        )

    return ComplianceResult(status="FAIL" if findings else "PASS", findings=findings)


def compliance_check_tool(terraform_text: str) -> dict[str, Any]:
    """ADK tool: run compliance checks against Terraform text."""
    return compliance_check(terraform_text).model_dump()


def _compliance_report(compliance: ComplianceResult) -> str:
    report = [f"Status: {compliance.status}", "", "Findings:"]
    if compliance.findings:
        for finding in compliance.findings:
            report.append(f"- {finding.rule_id} [{finding.severity}] {finding.resource}: {finding.issue}")
            report.append(f"  Fix: {finding.recommended_fix}")
    else:
        report.append("- None")
    return "\n".join(report) + "\n"


def package_output(bundle: TerraformBundle, parsed: ResourceList | None = None, translation: TranslationPlan | None = None) -> FinalPackage:
    compliance = compliance_check(bundle)
    files = {
        "main.tf": bundle.main_tf,
        "variables.tf": bundle.variables_tf,
        "iam.tf": bundle.iam_tf,
        "outputs.tf": bundle.outputs_tf,
        "architecture_summary.md": bundle.architecture_summary_md,
        "compliance_report.md": _compliance_report(compliance),
    }
    return FinalPackage(files=files, compliance=compliance, parsed=parsed, translation=translation)


def write_output_files(files: dict[str, str], output_dir: str = "output") -> dict[str, str]:
    """ADK tool: write generated files to the local output/ directory."""
    target = (REPO_ROOT / output_dir).resolve()
    repo = REPO_ROOT.resolve()
    if repo not in [target, *target.parents]:
        raise ValueError("output_dir must stay inside the repository")
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, content in files.items():
        safe_name = Path(name).name
        path = target / safe_name
        path.write_text(content)
        written[safe_name] = str(path.relative_to(repo))
    return written


def convert_cloudformation_to_gcp(template: str, write_files: bool = False) -> dict[str, Any]:
    """ADK tool: end-to-end CloudFormation to GCP Terraform conversion.

    Args:
        template: CloudFormation YAML or JSON text.
        write_files: When true, also writes output files under output/ for a
            local demo run. In Agent Engine this may write to ephemeral storage.
    """
    parsed = parse_cfn(template)
    translation = translate_resources(parsed)
    bundle = generate_terraform(parsed)
    final = package_output(bundle, parsed=parsed, translation=translation)
    if write_files:
        final.output_dir = "output"
        write_output_files(final.files, "output")
    return final.model_dump()


def convert_input_file_to_gcp(filename: str = "sample-three-tier.yaml", write_files: bool = True) -> dict[str, Any]:
    """ADK tool: convert a template from input/ and optionally write output/."""
    template = read_input_template(filename)
    return convert_cloudformation_to_gcp(template, write_files=write_files)


translation_agent = Agent(
    name="translation_agent",
    model=Gemini(model=MODEL_NAME, retry_options=types.HttpRetryOptions(attempts=3)),
    description="Maps supported AWS CloudFormation resources to Google Cloud targets.",
    input_schema=ResourceList,
    output_schema=TranslationPlan,
    instruction="""
You map a small supported CloudFormation resource list to Google Cloud.
Use only the MVP mapping catalog. Preserve architecture intent, explain any
assumptions, and return valid TranslationPlan JSON only.
""".strip(),
)

terraform_agent = Agent(
    name="terraform_agent",
    model=Gemini(model=MODEL_NAME, retry_options=types.HttpRetryOptions(attempts=3)),
    description="Generates starter Google Terraform from a CloudBridge TranslationPlan.",
    input_schema=TranslationPlan,
    output_schema=TerraformBundle,
    instruction="""
Generate starter Google Terraform for the TranslationPlan.
Keep files small and readable: main.tf, variables.tf, iam.tf, outputs.tf, and
architecture_summary.md. Prefer private Cloud SQL, uniform bucket-level access,
public access prevention, and least-privilege IAM. Return valid TerraformBundle
JSON only.
""".strip(),
)

fix_agent = Agent(
    name="fix_agent",
    model=Gemini(model=MODEL_NAME, retry_options=types.HttpRetryOptions(attempts=3)),
    description="Applies minimal fixes for CloudBridge compliance findings.",
    output_schema=TerraformBundle,
    instruction="""
Apply only compliance fixes needed for the demo rules:
1. remove public Cloud SQL exposure,
2. replace broad IAM with least-privilege roles,
3. add Cloud Storage uniform bucket-level access and public access prevention,
4. enable or document database backups.
Return the corrected TerraformBundle JSON only.
""".strip(),
)

root_agent = Agent(
    name="cloudbridge",
    model=Gemini(model=MODEL_NAME, retry_options=types.HttpRetryOptions(attempts=3)),
    description="AWS CloudFormation to GCP Terraform and compliance report agent.",
    sub_agents=[translation_agent, terraform_agent, fix_agent],
    tools=[
        read_input_template,
        parse_cloudformation_tool,
        service_mapping_catalog,
        translate_resources_tool,
        generate_terraform_tool,
        compliance_check_tool,
        convert_cloudformation_to_gcp,
        convert_input_file_to_gcp,
        write_output_files,
    ],
    instruction="""
You are CloudBridge, a Google ADK hackathon agent that converts small AWS
CloudFormation templates into a first-pass Google Cloud Terraform bundle and a
plain-English compliance report.

Primary workflow from README.md:
1. Accept pasted CloudFormation YAML/JSON, or read a named file from input/.
2. Parse resources and clearly list unsupported resources as warnings.
3. Map supported AWS resources to GCP equivalents using the MVP catalog.
4. Generate starter Terraform files: main.tf, variables.tf, iam.tf, outputs.tf.
5. Generate architecture_summary.md and compliance_report.md.
6. Run the compliance gate for public databases, broad IAM, and storage/database
   protection. If findings appear, use fix_agent or explain required changes.

For fastest demos, call convert_cloudformation_to_gcp for pasted templates or
convert_input_file_to_gcp for files such as input/sample-three-tier.yaml. Return
the generated files in the response. If the user asks to save files locally, set
write_files=true so files are written under output/.

Stay inside the MVP scope and do not claim this is production-ready Terraform.
""".strip(),
)

app = App(
    root_agent=root_agent,
    name="app",
)
