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

This follows the simpler CloudBridge pattern from the hackathon scaffold:
small LLM agents in a SequentialAgent pipeline. The only tool is safe project
file reading for loading CloudFormation templates by path.
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

from .cloudbridge_tools import (
    convert_cloudformation_to_gcp,
    list_project_files,
    read_input_template,
    read_project_file,
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

Produce a final demo-ready answer with:
1. One-sentence architecture summary.
2. The Terraform bundle fenced blocks from terraform_bundle.
3. A compliance report section with Status: PASS or FAIL, findings, severities, and fixes.
4. A note that files are not written automatically; user should review before copying to output/.

Stay concise.
""".strip(),
    output_key="compliance_report",
)

root_agent = SequentialAgent(
    name="cloudbridge_architect",
    description=(
        "Loads an AWS CloudFormation template, maps it to Google Cloud, "
        "generates starter Terraform, and reviews compliance."
    ),
    sub_agents=[source_loader, translator, terraform_writer, compliance_reviewer],
)

app = App(root_agent=root_agent, name="app")

cloudbridge_architect = root_agent
specialist_agents = [source_loader, translator, terraform_writer, compliance_reviewer]

__all__ = [
    "app",
    "cloudbridge_architect",
    "compliance_reviewer",
    "convert_cloudformation_to_gcp",
    "read_input_template",
    "root_agent",
    "source_loader",
    "specialist_agents",
    "terraform_writer",
    "translator",
]
