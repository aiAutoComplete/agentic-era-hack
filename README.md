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
app/agent.py              # conversational root agent + conversion pipeline
app/cloudbridge_tools.py  # safe file helper + deterministic test helpers
app/parser.py             # CloudFormation parser
app/terraform_gen.py      # starter Terraform generation
app/compliance.py         # explainable compliance checks
```

CloudBridge uses a conversational root agent so it can talk with the human,
list/read files, ask for missing input, and only run the full conversion when the
user asks. The conversion path is a simple ADK `SequentialAgent` pipeline
inspired by the hackathon scaffold: load source, translate architecture, write
Terraform, review compliance.

---

## Agent flow

```text
User request
    │
    ▼
cloudbridge_architect  (conversational LlmAgent)
    │
    ├── talks with user, lists/reads project files, asks clarifying questions
    │
    └── conversion_pipeline  (SequentialAgent; only when conversion is requested)
          │
          ├── source_loader        # reads input/sample*.yaml
          ├── translator           # maps AWS resources to Google Cloud
          ├── terraform_writer     # emits main.tf, variables.tf, iam.tf, outputs.tf
          └── compliance_reviewer  # reports PASS/FAIL findings and fixes
```

Runtime tooling is intentionally tiny:

- `list_project_files(scope)`
- `read_project_file(path)` with safe path checks

The deterministic parser/generator/compliance helpers remain in the repo for
unit tests and fallback scripts, but the playground path is agent-led.

One-line demo narrative:

```text
Open CloudBridge → chat/list/read files as needed → ask to convert input/sample-three-tier.yaml → the pipeline loads, maps, generates Terraform, and reviews compliance in one response.
```

### What happens when you say “hi”

The ADK app starts at `app/agent.py` with this root agent:

```python
root_agent = LlmAgent(name="cloudbridge_architect", ...)
```

When a user types a simple greeting like `hi`, ADK sends the message to
`cloudbridge_architect` first. This is a conversational coordinator, not the
conversion pipeline. Its instructions explicitly say not to run conversion for
every message. So for `hi`, it should just greet the user, explain what
CloudBridge can do, and ask what architecture task or input template the user
wants to work with.

```text
User: hi
  ↓
cloudbridge_architect
  ↓
Conversational response only. No Terraform generation yet.
```

The full conversion flow lives in the same file as:

```python
conversion_pipeline = SequentialAgent(
    sub_agents=[source_loader, translator, terraform_writer, compliance_reviewer]
)
```

That pipeline runs only when the user clearly asks to convert, migrate, generate
Terraform, or create a GCP bundle for a CloudFormation file.

```text
User: convert input/sample-three-tier-insecure.yaml to a GCP bundle
  ↓
cloudbridge_architect delegates to conversion_pipeline
  ↓
source_loader reads the CloudFormation template
  ↓
translator maps AWS resources and risks to Google Cloud architecture
  ↓
terraform_writer generates starter Terraform fenced blocks
  ↓
compliance_reviewer returns the final bundle plus PASS/FAIL findings
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

Run tests:

```bash
make test
```

Run the ADK web UI from the repository root:

```bash
make playground
```

Then open:

```text
http://localhost:8000
```

Select the `app` agent and ask questions like:

```text
hi
list input files
convert input/sample-three-tier.yaml to a GCP bundle
review input/sample-three-tier-insecure.yaml
```

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

The current demo uses Google ADK with a conversational `LlmAgent` root and a
`SequentialAgent` conversion pipeline. The project pins ADK 2 beta in
`pyproject.toml`, and `make playground` forces Vertex AI mode so the app uses the
lab GCP project rather than a Gemini API key.

---

## Definition of done for hackathon

- One sample CloudFormation file works end-to-end.
- Output includes Terraform files and a compliance report.
- Compliance routing demonstrates PASS and one fixable FAIL.
- The app runs locally with ADK and deploys to Cloud Run in the lab project.
