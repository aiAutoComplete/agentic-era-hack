# CloudBridge Redesign Notes

## User direction

The current `app/agent.py` became too hardcoded and too much like one deterministic router. The desired redesign is a real ADK multi-agent system with 5–6 specialist agents. Each agent should have a clear role and the root agent should route tasks to them. The system should be more intelligent, conversational, architecture-focused, and include human-in-the-loop approval before file changes.

Reference to follow: https://adk.dev/agents/

## Current repo state to know

Repo: `/Users/bhatiar3/ai_projects/agentic-era-hack`
Remote: `git@github.com:aiAutoComplete/agentic-era-hack.git`
Branch: `main`

Recent pushed commits:
- `1c0b5aa` Build CloudBridge AWS to GCP ADK agent
- `ba1a3b8` Load CloudBridge environment before ADK model setup
- `e0d9013` Force Vertex model path for ADK playground
- `1e29b76` Make playground conversion deterministic
- `d6747d9` Add CloudBridge demo flow and insecure sample
- `94a8c84` Make CloudBridge playground conversational

The user dislikes the deterministic conversational/router direction and wants it replaced with a cleaner multi-agent ADK architecture.

## Important constraints / lessons learned

1. `make playground` previously failed with:
   `No API key was provided. Please pass a valid API key...`
2. The deterministic `BaseAgent` avoided that by not invoking Gemini.
3. For the redesign, preserve `make playground` compatibility. If using LLM-backed ADK `Agent`, ensure the environment and model backend work in Cloud Shell. The `.env` and Makefile are already correct according to the user.
4. Do not reintroduce API-key failure. Use the same model setup pattern as the original generated app if needed, or carefully test in local imports. The original generated `app/agent.py` used:
   - `from google.adk.agents import Agent`
   - `from google.adk.apps import App`
   - `from google.adk.models import Gemini`
   - `from google.genai import types`
   - `google.auth.default()` to set project
   - `GOOGLE_CLOUD_LOCATION=global`
   - `GOOGLE_GENAI_USE_VERTEXAI=True`
   - `Gemini(model="gemini-3-flash-preview", retry_options=types.HttpRetryOptions(attempts=3))`
5. The user wants only architecture/project scope, not general chat.
6. The user wants a human-in-the-loop agent that asks permission before writing/changing files.

## Desired architecture

Use ADK multi-agent design:

```text
root_agent: cloudbridge_architect
│
├── project_browser_agent
│   └── show/list/read README, input/, output/
│
├── aws_source_analyst_agent
│   └── parse/read CloudFormation, explain AWS architecture and AWS risks
│
├── conversion_agent
│   └── map AWS services/resources to GCP equivalents
│
├── terraform_generator_agent
│   └── generate Terraform bundle: main.tf, variables.tf, iam.tf, outputs.tf
│
├── compliance_reviewer_agent
│   └── review AWS source + generated GCP output for findings
│
└── human_approval_writer_agent
    └── summarize proposed changes, ask approval, write only if approved
```

Root agent should be a coordinator, not a deterministic router. It should call specialist agents as `AgentTool`s.

## Keep function tools small

Only keep 5–6 function calls/tools total if possible:

1. `list_project_files(scope: str)`
   - `scope` can be `input`, `output`, or `all`.
2. `read_project_file(path: str)`
   - safe path limited to repo and maybe only README/input/output/app if needed.
3. `parse_cloudformation(template_or_path: str)`
   - parse YAML/JSON and return supported/unsupported resources.
4. `build_conversion_bundle(template_or_path: str)`
   - can wrap parser + starter mapping/Terraform generation if needed.
5. `run_compliance_review(template_or_path: str, terraform_text: str | None = None)`
   - find public S3, open SG/NACL, wildcard IAM, public DB, missing backup/encryption etc.
6. `write_project_files_after_approval(files: dict[str, str], approval: str)`
   - writes only when `approval` exactly indicates approve.
   - In ADK, ideally pair with `get_user_choice` / human approval.

The idea: tools are simple, specialist agents reason and compose them.

## Human-in-the-loop

Use ADK's human choice/long-running tool if possible:

```python
from google.adk.tools import get_user_choice
```

`get_user_choice` is a `LongRunningFunctionTool` that asks user to choose from options. It is imported from `google.adk.tools`.

Before writing files, the writer agent/root agent should:

1. Summarize proposed changes.
2. Ask user to approve:
   - `approve`
   - `revise`
   - `cancel`
3. Only call file-write tool if approval is explicit.

## Desired root agent behavior

- If user greets it, respond conversationally and ask what CloudBridge architecture task they want.
- If user asks to show/list input/output files, call project browser agent.
- If user asks to explain AWS template, call AWS source analyst agent.
- If user asks to convert, call conversion agent, terraform generator, compliance reviewer, then ask approval before writing outputs.
- If user asks compliance/security, call compliance reviewer.
- If user asks unrelated questions, politely refuse and say it only helps with CloudBridge AWS-to-GCP architecture.

## Example root agent code shape

```python
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import AgentTool, get_user_choice
from google.genai import types

from app.agents.project_browser import project_browser_agent
from app.agents.aws_source_analyst import aws_source_analyst_agent
from app.agents.conversion import conversion_agent
from app.agents.terraform_generator import terraform_generator_agent
from app.agents.compliance_reviewer import compliance_reviewer_agent
from app.agents.human_approval_writer import human_approval_writer_agent

MODEL = Gemini(
    model="gemini-3-flash-preview",
    retry_options=types.HttpRetryOptions(attempts=3),
)

root_agent = Agent(
    name="cloudbridge_architect",
    model=MODEL,
    description="Architecture-focused AWS CloudFormation to Google Cloud Terraform migration assistant with human approval.",
    sub_agents=[
        project_browser_agent,
        aws_source_analyst_agent,
        conversion_agent,
        terraform_generator_agent,
        compliance_reviewer_agent,
        human_approval_writer_agent,
    ],
    tools=[
        AgentTool(project_browser_agent),
        AgentTool(aws_source_analyst_agent),
        AgentTool(conversion_agent),
        AgentTool(terraform_generator_agent),
        AgentTool(compliance_reviewer_agent),
        AgentTool(human_approval_writer_agent),
        get_user_choice,
    ],
    instruction="""
You are CloudBridge Architect.

Only discuss this project:
- AWS CloudFormation inputs
- AWS architecture and security posture
- GCP Terraform outputs
- AWS-to-GCP mapping
- compliance findings
- generated documentation and diagrams

Route work to specialist agents. Do not do everything yourself.

Use:
- project_browser_agent for reading/listing files
- aws_source_analyst_agent for explaining CloudFormation
- conversion_agent for AWS-to-GCP mapping
- terraform_generator_agent for Terraform generation
- compliance_reviewer_agent for security/compliance review
- human_approval_writer_agent for any write/change request

Before writing, overwriting, deleting, or changing files, ask the human for approval using get_user_choice. Never write files without explicit approval.

If the user asks unrelated questions, politely say you can only help with the CloudBridge architecture project.
""".strip(),
)

app = App(root_agent=root_agent, name="app")
```

## Example specialist agent instructions

### Project Browser Agent

```python
project_browser_agent = Agent(
    name="project_browser_agent",
    model=MODEL,
    description="Lists and reads CloudBridge project files.",
    tools=[list_project_files, read_project_file],
    instruction="""
You only inspect CloudBridge project files. Use list_project_files and read_project_file.
Answer questions about README.md, input templates, output Terraform, compliance reports, and architecture diagrams.
Do not write files.
""".strip(),
)
```

### AWS Source Analyst Agent

```python
aws_source_analyst_agent = Agent(
    name="aws_source_analyst_agent",
    model=MODEL,
    description="Analyzes CloudFormation source architecture and AWS security posture.",
    tools=[read_project_file, parse_cloudformation],
    instruction="""
Analyze CloudFormation YAML/JSON. Explain AWS resources, architecture tiers, dependencies, and risks.
Call out public S3, open security groups, open NACLs, public databases, wildcard IAM, missing encryption/backups.
Do not generate Terraform and do not write files.
""".strip(),
)
```

### Conversion Agent

```python
conversion_agent = Agent(
    name="conversion_agent",
    model=MODEL,
    description="Maps AWS CloudFormation resources to GCP architecture equivalents.",
    tools=[parse_cloudformation],
    instruction="""
Map AWS resources to GCP equivalents:
- VPC -> google_compute_network
- Subnet -> google_compute_subnetwork
- SecurityGroup/NACL intent -> google_compute_firewall
- EC2/LaunchTemplate -> Compute Engine instance/template/MIG suggestion
- RDS PostgreSQL -> Cloud SQL PostgreSQL
- S3 -> Cloud Storage
- IAM Role/Policy -> Service Account + IAM bindings
Return assumptions and unresolved decisions. Do not write files.
""".strip(),
)
```

### Terraform Generator Agent

```python
terraform_generator_agent = Agent(
    name="terraform_generator_agent",
    model=MODEL,
    description="Generates starter GCP Terraform from a conversion plan.",
    tools=[build_conversion_bundle],
    instruction="""
Generate starter Terraform files: main.tf, variables.tf, iam.tf, outputs.tf.
Prefer private Cloud SQL, protected Cloud Storage, least privilege IAM, and readable small files.
Return proposed file contents. Do not write files.
""".strip(),
)
```

### Compliance Reviewer Agent

```python
compliance_reviewer_agent = Agent(
    name="compliance_reviewer_agent",
    model=MODEL,
    description="Reviews AWS source and GCP Terraform for compliance/security findings.",
    tools=[run_compliance_review],
    instruction="""
Review for:
- public S3 / public Cloud Storage
- open security groups / firewall rules
- open NACLs
- public databases
- wildcard/owner/editor/admin IAM
- missing backups, encryption, deletion protection
Return status PASS/FAIL, findings, severity, affected resource, and recommended fix.
Do not write files.
""".strip(),
)
```

### Human Approval Writer Agent

```python
human_approval_writer_agent = Agent(
    name="human_approval_writer_agent",
    model=MODEL,
    description="Asks for human approval and writes project files only after approval.",
    tools=[get_user_choice, write_project_files_after_approval],
    instruction="""
You handle file changes.
Before writing, summarize proposed changes and ask the user to choose approve, revise, or cancel.
Only call write_project_files_after_approval after explicit approval.
Never write files without approval.
""".strip(),
)
```

## Existing input/output samples

Input files:
- `input/sample-three-tier.yaml`
- `input/sample-three-tier-insecure.yaml`

Output files:
- `output/main.tf`
- `output/variables.tf`
- `output/iam.tf`
- `output/outputs.tf`
- `output/architecture_summary.md`
- `output/compliance_report.md`
- `output/aws-to-gcp-ascii-flow.md`
- `output/insecure-sample-expected-compliance-report.md`

## Tests to preserve/add

Existing tests pass with:

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration/test_agent.py -q
uv run --extra lint ruff check app/agent.py tests/unit/test_cloudbridge.py
```

For redesign, update tests to verify:
- `app.agent.root_agent` imports successfully.
- `root_agent.name == "cloudbridge_architect"` or expected name.
- specialist agents exist and are in `root_agent.sub_agents`.
- safe path functions reject paths outside repo.
- parse CloudFormation works for both sample templates.
- compliance flags insecure template findings.

## Important note

The user asked to write this temp markdown because context will be compacted/restarted. After restart, read this file first and then implement the multi-agent redesign. Do not continue hardcoding more deterministic routing logic.
