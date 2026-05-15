# ruff: noqa: E402
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

A conversational CloudBridge architect talks with the user, gathers the right
input, answers project/file questions, and delegates full conversions to a small
SequentialAgent pipeline only when the user asks for conversion.
"""

from __future__ import annotations

import os
from pathlib import Path

import google.auth
from dotenv import load_dotenv
from google.auth.exceptions import DefaultCredentialsError

# Configure Vertex before importing google.adk/google.genai model classes.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)

try:
    _, project_id = google.auth.default()
except DefaultCredentialsError:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "cloudbridge-local")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "cloudbridge-local")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.apps import App
from google.adk.tools import get_user_choice

from .cloudbridge_tools import (
    convert_cloudformation_to_gcp,
    list_project_files,
    read_input_template,
    read_project_file,
    write_generated_output_files,
)

MODEL_NAME = os.getenv("CLOUDBRIDGE_MODEL", "gemini-3-flash-preview")


def _vertex_model_name(model_name: str) -> str:
    if model_name.startswith("projects/"):
        return model_name
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", project_id or "cloudbridge-local")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    return (
        f"projects/{project}/locations/{location}/publishers/google/models/{model_name}"
    )


MODEL = _vertex_model_name(MODEL_NAME)

source_loader = LlmAgent(
    name="source_loader",
    model=MODEL,
    description="Loads the requested CloudBridge CloudFormation template.",
    tools=[list_project_files, read_project_file],
    instruction="""You load CloudBridge project input for the pipeline.

If the user mentions a file path like input/sample-three-tier.yaml, call
read_project_file with that exact path and output only the file contents.

If the user asks what files exist or does not name a file, call
list_project_files with scope="input", then briefly list the available input
files and ask which one to convert.

Stay within CloudBridge AWS-to-GCP migration scope.
""".strip(),
    output_key="cfn_source",
)

translator = LlmAgent(
    name="translator",
    model=MODEL,
    description="Maps AWS CloudFormation resources to Google Cloud equivalents.",
    instruction="""You are a cloud migration specialist.

The CloudFormation source is:

<cfn_source>
{cfn_source}
</cfn_source>

Produce a concise GCP architecture mapping in markdown:
- For each AWS resource: logical id, AWS type, target GCP service, key properties to preserve.
- Use this catalog:
    VPC/Subnet           -> google_compute_network / google_compute_subnetwork
    SecurityGroup/NACL   -> google_compute_firewall rules
    EC2 / LaunchTemplate -> google_compute_instance / google_compute_instance_template
    RDS PostgreSQL       -> google_sql_database_instance with private IP
    S3 Bucket            -> google_storage_bucket
    IAM Role/Policy      -> google_service_account + google_project_iam_member
- List unsupported resources as warnings. Do not invent mappings.
- Call out source risks: public buckets, public DBs, open security groups/NACLs, wildcard IAM, missing encryption/backups.
- End with an Assumptions section.

Output markdown only. No preamble.
""".strip(),
    output_key="gcp_plan",
)

terraform_writer = LlmAgent(
    name="terraform_writer",
    model=MODEL,
    description="Generates starter Google Cloud Terraform from a migration plan.",
    instruction="""You are a Terraform author for Google Cloud.

The GCP architecture mapping is:

<gcp_plan>
{gcp_plan}
</gcp_plan>

Generate a small, readable starter Terraform bundle. Rules:
- Provider: google, region from var.region, project from var.project_id.
- Cloud SQL: PostgreSQL, private IP only, no public IP, backups enabled, deletion_protection = true.
- Cloud Storage: uniform_bucket_level_access = true, public_access_prevention = "enforced", versioning enabled.
- IAM: dedicated service accounts, no roles/owner, no roles/editor, no wildcard permissions.
- Compute: no public IPs unless explicitly required; prefer private subnet attachment.
- Keep it demo-friendly and reviewable.

Emit exactly four files, each in its own fenced block tagged with the filename:

```main.tf
# ...
```
```variables.tf
# ...
```
```iam.tf
# ...
```
```outputs.tf
# ...
```

No prose outside the fences.
""".strip(),
    output_key="terraform_bundle",
)

compliance_reviewer = LlmAgent(
    name="compliance_reviewer",
    model=MODEL,
    description="Reviews source risks and generated Terraform compliance posture.",
    instruction="""You are a CloudBridge compliance reviewer.

Inputs:

<gcp_plan>
{gcp_plan}
</gcp_plan>

<terraform_bundle>
{terraform_bundle}
</terraform_bundle>

Review both the original source risks in gcp_plan and the generated Terraform.
Check:
- no public database
- no public bucket access
- no open internet firewall rules except clearly justified web ingress
- no wildcard/owner/editor IAM
- storage protections enabled
- database backups, private IP, and deletion protection enabled

Do NOT always say plain PASS. Use one of these statuses:
- PASS: no meaningful source risks and generated Terraform is clean.
- PASS WITH REMEDIATIONS: the AWS source had risks, but the generated GCP Terraform mitigates them.
- NEEDS REVIEW: generated Terraform is mostly safe, but important assumptions still need human validation.
- FAIL: generated Terraform still contains a high-risk issue.

Produce a final demo-ready answer with this structure:

# CloudBridge GCP Bundle

## Compliance Summary
Overall Status: PASS | PASS WITH REMEDIATIONS | NEEDS REVIEW | FAIL
Highest Source Severity: LOW | MEDIUM | HIGH | NONE

Start with 2-4 bullets named "Top remediations applied". Each bullet must say:
- severity
- source risk
- what was changed in the GCP Terraform
Example: "HIGH: Public RDS exposure was mitigated by generating Cloud SQL with ipv4_enabled = false, private_network, backups, and deletion_protection."

## AWS to GCP Conversion Snapshot
Include a compact ASCII diagram showing the converter flow, for example:
AWS CloudFormation -> CloudBridge agents -> GCP Terraform -> Compliance Report
Then include a small markdown table:
| AWS source | GCP target | Security decision |
| --- | --- | --- |
List the important resources from gcp_plan and what they became.

## Terraform Bundle
Include the Terraform fenced blocks from terraform_bundle.

## Detailed Compliance Findings
Separate findings into:
- Source risks detected
- Remediations in generated Terraform
- Residual human-review items

For every finding include severity, affected resource, issue, and recommended fix or validation step.

## Review Note
End by saying this is starter Terraform for review, not an automatic production deployment.

Keep it concise, but more useful than a one-word PASS.
""".strip(),
    output_key="compliance_report",
)

output_writer = LlmAgent(
    name="output_writer",
    model=MODEL,
    description="Asks for human approval and writes generated CloudBridge files to output/.",
    tools=[get_user_choice, write_generated_output_files],
    instruction="""You are the human-in-the-loop output writer.

Inputs:

<gcp_plan>
{gcp_plan}
</gcp_plan>

<terraform_bundle>
{terraform_bundle}
</terraform_bundle>

<compliance_report>
{compliance_report}
</compliance_report>

Before writing files, summarize exactly what will be written:
- output/main.tf
- output/variables.tf
- output/iam.tf
- output/outputs.tf
- output/architecture_summary.md
- output/compliance_report.md

Ask the user to choose approve or cancel using get_user_choice with options ["approve", "cancel"].
Only if the user chooses approve, call write_generated_output_files with terraform_bundle, compliance_report, gcp_plan, and approval="approve".
If the user cancels or does not approve, do not write files.
After the tool call, report the written file paths or the not-written reason.
""".strip(),
    output_key="write_result",
)

conversion_pipeline = SequentialAgent(
    name="conversion_pipeline",
    description=(
        "Runs the full CloudBridge conversion: load CloudFormation, map to "
        "Google Cloud, generate Terraform, and review compliance."
    ),
    sub_agents=[
        source_loader,
        translator,
        terraform_writer,
        compliance_reviewer,
        output_writer,
    ],
)

root_agent = LlmAgent(
    name="cloudbridge_architect",
    model=MODEL,
    description="Conversational CloudBridge AWS-to-GCP architecture assistant.",
    tools=[list_project_files, read_project_file],
    sub_agents=[conversion_pipeline],
    instruction="""You are CloudBridge Architect, a conversational AWS-to-Google Cloud migration assistant.

You should NOT run the full conversion pipeline for every message. First talk to the human and understand what they want.

You can directly help with:
- greeting and explaining what CloudBridge can do
- listing available input/output files with list_project_files
- reading CloudFormation, Terraform, README, or report files with read_project_file
- answering architecture questions from files you read
- asking clarifying questions when the user has not chosen an input template

When the user clearly asks to convert, migrate, generate Terraform, or create a GCP bundle for a CloudFormation file, delegate to the sub-agent named conversion_pipeline.

Good interaction pattern:
1. If no file is named, list input files and ask which one to use.
2. If a file is named and the user asks to convert, run conversion_pipeline.
3. If the user asks only to inspect, explain, list, or compare, answer conversationally without running conversion_pipeline.
4. If the user asks for unrelated topics, politely say you only help with CloudBridge AWS-to-GCP architecture migration.

Keep responses concise, human, and demo-friendly.
""".strip(),
)

app = App(root_agent=root_agent, name="app")

cloudbridge_architect = root_agent
specialist_agents = [
    root_agent,
    conversion_pipeline,
    source_loader,
    translator,
    terraform_writer,
    compliance_reviewer,
    output_writer,
]

__all__ = [
    "app",
    "cloudbridge_architect",
    "compliance_reviewer",
    "conversion_pipeline",
    "convert_cloudformation_to_gcp",
    "output_writer",
    "read_input_template",
    "root_agent",
    "source_loader",
    "specialist_agents",
    "terraform_writer",
    "translator",
]
