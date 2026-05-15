# CloudBridge

**AWS CloudFormation → GCP Terraform + Compliance Report**  
**Google ADK hackathon MVP | Deployable to GCP Cloud Run**

CloudBridge is a one-day hackathon demo showing how Google ADK agents can turn a small AWS CloudFormation template into a first-pass Google Cloud Terraform bundle with a simple compliance report.

It is intentionally small, understandable, and demo-friendly.

---

## What this project does

Many teams have AWS CloudFormation templates but need to move quickly toward Google Cloud. Manually translating infrastructure is slow and error-prone, especially around IAM, databases, and security posture.

CloudBridge takes a small CloudFormation YAML/JSON file and produces:

1. a GCP architecture mapping,
2. starter Terraform files, and
3. a simple compliance report.

This is **not** a full migration platform. It is a focused ADK workflow demo.

---

## MVP scope

### Supported input resources

| AWS resource | GCP target |
|---|---|
| VPC + subnets | VPC + subnets |
| EC2 instance or launch template | Compute Engine VM / instance template |
| RDS PostgreSQL | Cloud SQL PostgreSQL |
| S3 bucket | Cloud Storage bucket |
| IAM role/policy | Service account + IAM bindings |

### Expected output

```text
output/
  main.tf
  variables.tf
  iam.tf
  outputs.tf
  architecture_summary.md
  compliance_report.md
```

### Non-goals

- No complete CloudFormation coverage.
- No automatic production deployment of generated Terraform.
- No deep ATO automation.
- No broad AWS-to-GCP service catalog.
- No complex UI required; ADK web UI or Cloud Run is enough.

---

## Repository layout

```text
.
├── README.md
├── input/
│   └── sample-three-tier.yaml
├── output/
│   ├── main.tf
│   ├── variables.tf
│   ├── iam.tf
│   ├── outputs.tf
│   ├── architecture_summary.md
│   └── compliance_report.md
└── app/
    ├── __init__.py
    ├── agent.py
    ├── agent_engine_app.py
    └── app_utils/
```

The main implementation is split across:

```text
app/agent.py              # simple ADK 2 graph workflow + CloudBridge architect agent
app/cloudbridge_tools.py  # small safe tools used by the agent
app/parser.py             # CloudFormation parser
app/terraform_gen.py      # starter Terraform generation
app/compliance.py         # explainable compliance checks
```

CloudBridge uses ADK 2 graph workflows, but the graph is intentionally simple:
`cloudbridge_architect` runs one capable `cloudbridge_architect_agent`. The agent
uses tools for safe file access, CloudFormation parsing, conversion bundle
creation, compliance review, and human-approved file writes.

---

## Agent flow

```text
User request
    │
    ▼
cloudbridge_architect  (ADK 2 Workflow graph)
    │
    ▼
cloudbridge_architect_agent
    │
    ├── list/read project files
    ├── parse/explain CloudFormation
    ├── map AWS resources to Google Cloud
    ├── generate starter Terraform bundle
    ├── review compliance/security findings
    └── ask approve / revise / cancel before writes
```

Tooling is intentionally small:

- `list_project_files(scope)`
- `read_project_file(path)` with safe path checks
- `parse_cloudformation(template_or_path)`
- `build_conversion_bundle(template_or_path)`
- `run_compliance_review(template_or_path, terraform_text=None)`
- `write_project_files_after_approval(files, approval)`

One-line demo narrative:

```text
Open CloudBridge → ask to convert input/sample-three-tier.yaml → the agent analyzes,
maps, generates Terraform, reviews compliance → asks for approval → output/ files are written only after approval.
```

---

## Compliance rules

The compliance gate is deliberately small and explainable:

1. **No public database**  
   Cloud SQL should not expose a public IP in the generated plan.

2. **No wildcard or owner-style IAM**  
   Generated IAM should avoid `roles/owner`, wildcard-like permissions, and broad admin roles.

3. **Storage/database protection**  
   Cloud Storage and Cloud SQL should include protection settings or document managed defaults.

The report format is simple:

```text
Status: PASS or FAIL
Findings:
- rule_id
- severity
- resource
- issue
- recommended_fix
```

---

## Quick start locally

From the repo root:

```bash
cd /Users/bhatiar3/ai_projects/agentic-era-hack
uv sync
```

Run a local deterministic smoke conversion using the sample input template:

```bash
uv run python - <<'PY'
from app.agent import convert_input_file_to_gcp
result = convert_input_file_to_gcp("sample-three-tier.yaml", write_files=True)
print(result["compliance"]["status"])
print(sorted(result["files"]))
PY
```

Run the ADK web UI from the repository root:

```bash
uv run adk web --port 8000
```

Then open:

```text
http://localhost:8000
```

Select the `app` / `cloudbridge` agent and paste a small CloudFormation template, or ask it to convert `input/sample-three-tier.yaml`.

---

## Deploy to GCP Cloud Run

Use the ADK Cloud Run deploy path for the hackathon lab:

```bash
export GOOGLE_CLOUD_PROJECT="<lab-project-id>"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI=True

adk deploy cloud_run \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region="$GOOGLE_CLOUD_LOCATION" \
  --service_name="cloudbridge" \
  --with_ui \
  ./app
```

Notes:

- `app/agent.py` defines `root_agent`, which ADK expects.
- `app/agent.py` also exports `app = App(...)` for Agent Engine.
- `pyproject.toml` contains runtime dependencies.

---

## Demo script

1. Open the ADK web UI or deployed Cloud Run URL.
2. Paste a small CloudFormation YAML/JSON template.
3. Show parsed resources and unsupported-resource warnings if any.
4. Show the AWS → GCP mapping.
5. Show generated Terraform files.
6. Show compliance report.
7. Include one bad IAM or public database example to show `FAIL → fix_agent → output`.

---

## Important ADK note

The design follows the ADK docs for:

- graph-based workflows: `https://adk.dev/workflows/`
- collaborative agents: `https://adk.dev/workflows/collaboration/`

The local virtual environment tested during scaffolding had `google-adk==1.33.0`, where ADK 2 `Workflow` / `Event` APIs were not exposed. The scaffold therefore supports both paths:

- **ADK 2 available:** use the graph workflow.
- **ADK 1.x only:** fall back to a coordinator agent with the same tools and specialist agents.

---

## Definition of done for hackathon

- One sample CloudFormation file works end-to-end.
- Output includes Terraform files and a compliance report.
- Compliance routing demonstrates PASS and one fixable FAIL.
- The app runs locally with ADK and deploys to Cloud Run in the lab project.
