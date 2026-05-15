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
"""CloudBridge ADK 2 graph workflow app.

The root is a graph-based workflow. Specialist ADK agents do the architecture
work; small Python tools only provide safe file access, parsing, deterministic
starter Terraform, compliance scanning, and approved writes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import get_user_choice
from google.adk.workflow import START, Workflow, node
from google.auth.exceptions import DefaultCredentialsError
from google.genai import types

from .cloudbridge_tools import (
    build_conversion_bundle,
    convert_cloudformation_to_gcp,
    list_project_files,
    parse_cloudformation,
    read_input_template,
    read_project_file,
    run_compliance_review,
    write_project_files_after_approval,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env", override=True)

try:
    _, project_id = google.auth.default()
except DefaultCredentialsError:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "cloudbridge-local")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "cloudbridge-local")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

MODEL_NAME = os.getenv("CLOUDBRIDGE_MODEL", "gemini-3-flash-preview")


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"true", "1"}


def _model_name_for_backend(model_name: str) -> str:
    if model_name.startswith("projects/") or not _env_enabled(
        "GOOGLE_GENAI_USE_VERTEXAI"
    ):
        return model_name
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", project_id or "cloudbridge-local")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    return (
        f"projects/{project}/locations/{location}/publishers/google/models/{model_name}"
    )


def _gemini_model() -> Gemini:
    return Gemini(
        model=_model_name_for_backend(MODEL_NAME),
        retry_options=types.HttpRetryOptions(attempts=3),
    )


MODEL = _gemini_model()

SCOPE_INSTRUCTION = """
Stay strictly inside CloudBridge scope:
- AWS CloudFormation inputs and AWS architecture/security posture
- AWS-to-GCP service/resource mapping
- GCP Terraform outputs
- compliance findings and recommended remediation
- generated migration documentation and diagrams
If the user asks for anything unrelated, politely refuse and restate the CloudBridge tasks you can help with.
""".strip()

project_browser_agent = Agent(
    name="project_browser_agent",
    model=MODEL,
    description="Lists and reads CloudBridge project files.",
    tools=[list_project_files, read_project_file],
    instruction=f"""
{SCOPE_INSTRUCTION}

You inspect CloudBridge files only. Use list_project_files and read_project_file.
Answer file, README, input, output, diagram, greeting, and help requests.
Do not analyze pasted templates deeply, generate Terraform, run compliance, or write files.
""".strip(),
)

aws_source_analyst_agent = Agent(
    name="aws_source_analyst_agent",
    model=MODEL,
    description="Analyzes CloudFormation source architecture and AWS security posture.",
    tools=[read_project_file, parse_cloudformation],
    instruction=f"""
{SCOPE_INSTRUCTION}

Analyze CloudFormation YAML/JSON. If given a path, read it. If given template text, parse it.
Explain AWS resources, architecture tiers, dependencies, data flows, and AWS risks.
Call out public S3, open security groups, open NACLs, public databases, wildcard IAM, missing encryption, and missing backups.
Do not generate Terraform and do not write files.
""".strip(),
)

conversion_agent = Agent(
    name="conversion_agent",
    model=MODEL,
    description="Maps AWS CloudFormation resources to GCP architecture equivalents.",
    tools=[parse_cloudformation],
    instruction=f"""
{SCOPE_INSTRUCTION}

Create the AWS-to-GCP architecture mapping. Use parse_cloudformation for source facts.
Map the supported MVP resources:
- VPC -> google_compute_network
- Subnet -> google_compute_subnetwork
- SecurityGroup/NACL intent -> google_compute_firewall
- EC2/LaunchTemplate -> Compute Engine instance/template/MIG recommendation
- RDS PostgreSQL -> Cloud SQL PostgreSQL
- S3 -> Cloud Storage
- IAM Role/Policy -> Service Account + IAM bindings
Return assumptions, unresolved migration choices, and risks. Do not write files.
""".strip(),
)

terraform_generator_agent = Agent(
    name="terraform_generator_agent",
    model=MODEL,
    description="Generates starter GCP Terraform bundles from CloudFormation.",
    tools=[build_conversion_bundle],
    instruction=f"""
{SCOPE_INSTRUCTION}

Generate starter Terraform by calling build_conversion_bundle with the input template path or pasted template.
Return concise proposed file names plus important excerpts; do not dump every file unless the user asks.
Prefer private Cloud SQL, protected Cloud Storage, least-privilege IAM, and readable small files.
Do not write files.
""".strip(),
)

compliance_reviewer_agent = Agent(
    name="compliance_reviewer_agent",
    model=MODEL,
    description="Reviews AWS source and GCP Terraform for security/compliance findings.",
    tools=[run_compliance_review, build_conversion_bundle],
    instruction=f"""
{SCOPE_INSTRUCTION}

Review AWS source and generated GCP Terraform. If Terraform is not supplied, call build_conversion_bundle first, then review.
Use run_compliance_review and return status PASS/FAIL, severity, affected resource, issue, and recommended fix.
Focus on public buckets, open network rules, public databases, wildcard IAM, missing backups, encryption, and deletion protection.
Do not write files.
""".strip(),
)

human_approval_writer_agent = Agent(
    name="human_approval_writer_agent",
    model=MODEL,
    description="Requests human approval and writes CloudBridge output files only after approval.",
    tools=[
        get_user_choice,
        build_conversion_bundle,
        write_project_files_after_approval,
    ],
    instruction=f"""
{SCOPE_INSTRUCTION}

You handle file changes. Never write, overwrite, delete, or modify files without explicit human approval.
For a conversion write request:
1. Call build_conversion_bundle to get proposed output files.
2. Summarize files to be written under output/ and the compliance status.
3. Ask the human to choose approve, revise, or cancel using get_user_choice.
4. Only call write_project_files_after_approval when the approval choice is approve/approved.
If the user wants revisions, explain what you need changed and do not write.
""".strip(),
)

specialist_agents = [
    project_browser_agent,
    aws_source_analyst_agent,
    conversion_agent,
    terraform_generator_agent,
    compliance_reviewer_agent,
    human_approval_writer_agent,
]

# The same specialist can appear in multiple graph branches. Branch-specific
# node names keep browsing/analyze/compliance requests from falling through into
# the full conversion-and-write path.
aws_source_analyst_for_conversion = node(
    aws_source_analyst_agent,
    name="aws_source_analyst_for_conversion",
)
compliance_reviewer_for_conversion = node(
    compliance_reviewer_agent,
    name="compliance_reviewer_for_conversion",
)


@node(name="request_router")
def request_router(node_input: str) -> Any:
    """Tiny graph router; specialist agents perform the actual work."""
    text = str(node_input or "")
    lowered = text.lower()
    payload = {
        "request": text,
        "default_template": "input/sample-three-tier.yaml",
        "insecure_template": "input/sample-three-tier-insecure.yaml",
        "scope": "CloudBridge AWS CloudFormation to Google Cloud Terraform architecture migration",
    }

    browse_words = (
        "list",
        "show",
        "read",
        "file",
        "files",
        "readme",
        "input",
        "output",
        "diagram",
        "help",
        "hello",
        "hi",
    )
    analyze_words = (
        "explain",
        "analyze",
        "analyse",
        "architecture",
        "aws template",
        "cloudformation",
    )
    compliance_words = (
        "compliance",
        "security",
        "risk",
        "ato",
        "finding",
        "findings",
        "insecure",
        "review",
    )
    convert_words = (
        "convert",
        "terraform",
        "gcp",
        "google cloud",
        "migrate",
        "migration",
        "generate",
        "write",
    )
    unrelated_words = ("sky", "weather", "joke", "recipe", "sports", "stock", "movie")

    from google.adk.events import Event

    if any(word in lowered for word in unrelated_words):
        yield Event(output=payload, route="browse")
    elif any(word in lowered for word in browse_words) and not any(
        word in lowered for word in convert_words
    ):
        yield Event(output=payload, route="browse")
    elif any(word in lowered for word in convert_words):
        yield Event(output=payload, route="convert")
    elif any(word in lowered for word in compliance_words):
        yield Event(output=payload, route="compliance")
    elif any(word in lowered for word in analyze_words):
        yield Event(output=payload, route="analyze")
    elif any(word in lowered for word in browse_words) or len(lowered.strip()) < 20:
        yield Event(output=payload, route="browse")
    else:
        yield Event(output=payload, route="analyze")


root_agent = Workflow(
    name="cloudbridge_architect",
    description="Graph-based CloudBridge multi-agent AWS-to-GCP migration workflow.",
    edges=[
        (START, request_router),
        (
            request_router,
            {
                "browse": project_browser_agent,
                "analyze": aws_source_analyst_agent,
                "compliance": compliance_reviewer_agent,
                "convert": aws_source_analyst_for_conversion,
            },
        ),
        (aws_source_analyst_for_conversion, conversion_agent),
        (conversion_agent, terraform_generator_agent),
        (terraform_generator_agent, compliance_reviewer_for_conversion),
        (compliance_reviewer_for_conversion, human_approval_writer_agent),
    ],
)

cloudbridge_architect = root_agent

app = App(root_agent=root_agent, name="app")

__all__ = [
    "app",
    "aws_source_analyst_agent",
    "cloudbridge_architect",
    "compliance_reviewer_agent",
    "conversion_agent",
    "convert_cloudformation_to_gcp",
    "human_approval_writer_agent",
    "project_browser_agent",
    "read_input_template",
    "root_agent",
    "specialist_agents",
    "terraform_generator_agent",
]
