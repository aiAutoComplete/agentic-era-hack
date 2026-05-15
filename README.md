# CloudBridge

**AWS CloudFormation → Google Cloud architecture, Terraform, compliance review, and diagrams**  
**Google ADK hackathon MVP**

CloudBridge is a focused Google ADK demo for helping a human understand and migrate AWS CloudFormation architectures to Google Cloud. It is intentionally small, conversational, and demo-friendly: the agent can talk first, inspect files, ask which template to use, run a conversion pipeline on demand, review security posture, and write output files only after human approval.

---

## What CloudBridge does

CloudBridge takes an AWS CloudFormation YAML template and produces:

1. a readable AWS → GCP architecture mapping,
2. starter Google Cloud Terraform,
3. an explainable compliance/security report,
4. optional AWS/GCP/conversion architecture diagrams.

This is **not** a full migration platform or production deployment engine. It is a working ADK workflow that generates a first draft for review.

---

## Current agent design

The live ADK app is implemented in:

```text
app/agent.py
```

The root agent is a conversational coordinator:

```text
cloudbridge_architect  (LlmAgent)
```

It talks with the user, lists/reads project files, asks clarifying questions, and only delegates to the conversion pipeline when the user explicitly asks to convert, migrate, generate Terraform, or create a GCP bundle.

The conversion pipeline is:

```text
conversion_pipeline  (SequentialAgent)
  ├── source_loader          reads the selected CloudFormation template
  ├── translator             maps AWS resources/risks to Google Cloud architecture
  ├── terraform_writer       emits main.tf, variables.tf, iam.tf, outputs.tf
  ├── compliance_reviewer    reports status, severity, remediations, residual review
  └── output_writer          asks approve/cancel, then writes output files
```

### What happens when you say `hi`

```text
User: hi
  ↓
cloudbridge_architect
  ↓
Conversational response only. No Terraform generation yet.
```

The root agent should greet the user, explain CloudBridge capabilities, and ask what the user wants to inspect or convert.

### What happens when you ask for conversion

```text
User: convert input/sample-three-tier-insecure.yaml to a GCP bundle
  ↓
cloudbridge_architect delegates to conversion_pipeline
  ↓
source_loader reads the CloudFormation template
  ↓
translator creates AWS → GCP mapping
  ↓
terraform_writer generates starter Terraform fenced blocks
  ↓
compliance_reviewer explains source risks, remediations, and residual review items
  ↓
output_writer asks approve/cancel
  ↓
if approved, files are written under output/
```

---

## Human-in-the-loop writes

CloudBridge does **not** silently overwrite files. The final `output_writer` uses ADK tool confirmation, so the write tool does not execute until the user approves it.

On approval, it writes:

```text
output/main.tf
output/variables.tf
output/iam.tf
output/outputs.tf
output/architecture_summary.md
output/compliance_report.md
```

It then runs:

```bash
uv run --with diagrams python scripts/generate_diagrams.py --all
```

---

## Compliance output

The compliance report is designed to be more useful than a one-word PASS. It uses these statuses:

- `PASS` — no meaningful source risks and generated Terraform is clean.
- `PASS WITH REMEDIATIONS` — the AWS source had risks, but the generated GCP Terraform mitigates them.
- `NEEDS REVIEW` — generated Terraform is mostly safe, but assumptions require human validation.
- `FAIL` — generated Terraform still contains a high-risk issue.

The report includes:

- top remediations applied, with severity,
- what AWS resources were converted to what GCP targets,
- source risks detected,
- remediations in generated Terraform,
- residual human-review items.

---

## Supported/demo input architectures

Sample CloudFormation inputs live in `input/`:

```text
input/sample-three-tier.yaml
input/sample-three-tier-insecure.yaml
input/static-site-cloudfront-s3.yaml
input/lambda-reverse-proxy.yaml
input/serverless-event-pipeline.yaml
```

These cover:

| Input | Architecture |
|---|---|
| `sample-three-tier.yaml` | VPC, subnets, EC2/LaunchTemplate, RDS PostgreSQL, S3, IAM |
| `sample-three-tier-insecure.yaml` | Same pattern with intentional public DB/S3/IAM/network risks |
| `static-site-cloudfront-s3.yaml` | CloudFront + private S3 static website |
| `lambda-reverse-proxy.yaml` | API Gateway HTTP API + Lambda reverse proxy |
| `serverless-event-pipeline.yaml` | S3 → SQS/DLQ → Lambda → DynamoDB event pipeline |

The LLM agents can reason about broader AWS/GCP architecture. The deterministic helper parser/generator is intentionally smaller and exists mainly for tests and fallback utilities.

---

## Repository layout

```text
.
├── README.md
├── Team4_CloudBridge_OnePager.docx
├── input/
├── output/
│   ├── *.tf
│   ├── architecture_summary.md
│   ├── compliance_report.md
│   ├── aws-to-gcp-ascii-flow.md
│   └── diagrams/
├── scripts/
│   └── generate_diagrams.py
├── app/
│   ├── agent.py
│   ├── cloudbridge_tools.py
│   ├── parser.py
│   ├── terraform_gen.py
│   ├── compliance.py
│   └── agent_engine_app.py
└── tests/
```

Important files:

```text
app/agent.py              ADK conversational root + conversion pipeline
app/cloudbridge_tools.py  safe file tools, approved writer, deterministic helpers
app/parser.py             CloudFormation parser used by tests/fallbacks
app/terraform_gen.py      deterministic starter Terraform helper
app/compliance.py         deterministic compliance helper
scripts/generate_diagrams.py optional diagram generator, not part of ADK runtime
```

---

## Optional architecture diagrams

CloudBridge includes a separate manual diagram generator so the working ADK playground flow stays untouched. It uses Graphviz and the Python `diagrams` package to create AWS source, GCP target, and AWS→GCP conversion diagrams.

Generate diagrams for every sample input:

```bash
uv run --with diagrams python scripts/generate_diagrams.py --all
```

Generate diagrams for one input:

```bash
uv run --with diagrams python scripts/generate_diagrams.py input/lambda-reverse-proxy.yaml
```

Outputs are written to:

```text
output/diagrams/
  aws-*.png / aws-*.svg
  gcp-*.png / gcp-*.svg
  conversion-*.png / conversion-*.svg
```

This script is intentionally not part of the live ADK agent path.

---

## Quick start in Cloud Shell / local

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
make test
```

Run lint/checks:

```bash
make lint
```

Start the ADK playground:

```bash
make playground
```

`make playground` sets Vertex AI mode for the current GCP project:

```text
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION=global
```

In ADK Web, select the `app` folder and try:

```text
hi
list input files
convert input/sample-three-tier-insecure.yaml to a GCP bundle
generate a compliance review for input/static-site-cloudfront-s3.yaml
```

---

## GCP deploy note

The project keeps the Agent Starter Pack shape:

- `app/agent.py` exports `root_agent`, which ADK expects.
- `app/agent.py` exports `app = App(...)` for Agent Engine compatibility.
- `app/agent_engine_app.py` provides the Agent Engine wrapper.

Use the provided Makefile target when ready:

```bash
make deploy
```

---

## Demo script

1. Open ADK Web with `make playground`.
2. Say `hi` to show the conversational coordinator does not run conversion immediately.
3. Ask `list input files`.
4. Run `convert input/sample-three-tier-insecure.yaml to a GCP bundle`.
5. Show AWS → GCP mapping, generated Terraform, and compliance report.
6. Approve the output writer when prompted.
7. Show files under `output/`.
8. Optionally show pre-generated diagrams under `output/diagrams/`.

---

## Definition of done for the hackathon demo

- Conversational root agent works in ADK Web.
- Conversion pipeline runs only on explicit conversion requests.
- Human approval is required before writing files.
- Output includes Terraform, architecture summary, compliance report, and optional diagrams.
- `make lint` and `make test` pass.
