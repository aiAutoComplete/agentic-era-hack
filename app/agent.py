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
"""CloudBridge ADK 2 app.

Simple graph workflow: one capable CloudBridge architect agent does the work,
with a few safe tools for file access, conversion, compliance, and approved
writes. Keep the workflow small so the ADK playground is easy to demo.
"""

from __future__ import annotations

import os
from pathlib import Path

import google.auth
from dotenv import load_dotenv
from google.auth.exceptions import DefaultCredentialsError

# IMPORTANT: configure Vertex before importing google.adk/google.genai classes.
# Otherwise ADK can initialize the Gemini Developer API path and ask for an API key.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)

try:
    _, project_id = google.auth.default()
except DefaultCredentialsError:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "cloudbridge-local")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "cloudbridge-local")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import get_user_choice
from google.adk.workflow import START, Workflow
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

MODEL_NAME = os.getenv("CLOUDBRIDGE_MODEL", "gemini-3-flash-preview")


def _model_name_for_backend(model_name: str) -> str:
    if model_name.startswith("projects/"):
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


cloudbridge_architect_agent = Agent(
    name="cloudbridge_architect_agent",
    model=_gemini_model(),
    description="CloudBridge AWS CloudFormation to Google Cloud Terraform architecture assistant.",
    tools=[
        list_project_files,
        read_project_file,
        parse_cloudformation,
        build_conversion_bundle,
        run_compliance_review,
        get_user_choice,
        write_project_files_after_approval,
    ],
    instruction="""
You are CloudBridge Architect.

Scope:
- AWS CloudFormation input templates
- AWS architecture and security posture
- AWS-to-Google Cloud resource mapping
- GCP Terraform output
- compliance findings and remediation
- CloudBridge project README/input/output files

Do all CloudBridge tasks directly with your tools:
- For file questions, use list_project_files and read_project_file.
- For AWS template explanation, use parse_cloudformation, then explain resources, tiers, dependencies, and risks.
- For conversion, use build_conversion_bundle, summarize the GCP architecture, Terraform files, assumptions, and compliance status.
- For compliance/security review, use run_compliance_review.
- For writes, first summarize proposed output files, ask the user to choose approve/revise/cancel with get_user_choice, then call write_project_files_after_approval only if the user approves.

Never write files without explicit approval.
If the user asks about unrelated topics, politely say you only help with CloudBridge AWS-to-GCP architecture migration.
Keep responses concise and demo-friendly.
""".strip(),
)

# Keep ADK 2 graph workflow, but make it intentionally simple.
root_agent = Workflow(
    name="cloudbridge_architect",
    description="Simple ADK 2 graph workflow for CloudBridge.",
    edges=[(START, cloudbridge_architect_agent)],
)

app = App(root_agent=root_agent, name="app")

# Backwards/test-friendly names.
cloudbridge_architect = root_agent
specialist_agents = [cloudbridge_architect_agent]

__all__ = [
    "app",
    "cloudbridge_architect",
    "cloudbridge_architect_agent",
    "convert_cloudformation_to_gcp",
    "read_input_template",
    "root_agent",
    "specialist_agents",
]
