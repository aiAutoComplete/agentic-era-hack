# Using DSPy to Transfer Infrastructure Standards from AWS to GCP

## Summary

CloudBridge should not be framed as a CloudFormation-to-Terraform converter. The stronger use case is standards transfer: use existing, approved AWS CloudFormation templates as examples of internal infrastructure standards, then generate new GCP-native Terraform for applications that will only run on Google Cloud.

In this model, AWS templates are not literal source material to convert. They are exemplars that reveal organizational patterns: network boundaries, IAM posture, naming, encryption, database protections, logging, backup behavior, and compliance expectations.

DSPy can help if it is used as an evaluation and optimization layer around those standards. ADK should remain the orchestration and deployment layer.

## Target Architecture

```text
Approved AWS CloudFormation templates
        |
        v
Extract standards and reusable patterns
        |
        v
DSPy signatures, examples, metrics, and optimizers
        |
        v
ADK agent generates GCP-native Terraform
        |
        v
Deterministic policy and compliance checks
```

## Why DSPy Could Help

The current ADK agent is prompt-driven. It asks one LLM agent to map CloudFormation intent, another to generate Terraform, and another to review compliance. That is simple, but quality depends heavily on prompt wording.

DSPy is useful when we can define:

- inputs,
- expected outputs or scoring rules,
- metrics for quality,
- examples that represent good behavior.

This project can provide those ingredients if the organization supplies approved AWS templates plus the standards they represent. DSPy can then help optimize the instructions and examples used by the GCP generator instead of relying on hand-tuned prompts.

## What the AWS Templates Should Be Used For

Use existing AWS templates as standards examples, not as conversion targets.

Each template should be annotated with:

- what application pattern it represents,
- which standards are intentional and must carry forward,
- which AWS-specific details should not carry forward,
- what the GCP-native equivalent should achieve,
- what compliance controls are mandatory.

Useful standards to extract include:

- naming conventions,
- environment separation,
- network segmentation,
- private database access,
- encryption defaults,
- backup and deletion protection,
- IAM least privilege,
- logging and monitoring,
- storage access posture,
- public exposure rules,
- required labels or tags,
- approved service patterns.

## How the ADK Agent Should Change

The agent should eventually move away from:

```text
Convert this CloudFormation template to GCP Terraform.
```

and toward:

```text
Given a new application description and our internal infrastructure standards,
generate GCP-native Terraform that follows those standards.
```

The likely ADK workflow would be:

1. classify the application pattern,
2. retrieve relevant internal standards/examples,
3. draft a GCP architecture plan,
4. generate GCP Terraform,
5. run deterministic compliance checks,
6. produce a clear report with assumptions, files, and findings.

ADK remains useful for workflow orchestration, Cloud Run deployment, sessions, traces, and the web UI.

## Where DSPy Fits

DSPy should start outside the production runtime.

Recommended first use:

```text
experiments/dspy/
  standards_dataset.jsonl
  signatures.py
  metrics.py
  optimize.py
```

The DSPy harness would test and improve the core generation behavior using examples like:

```text
Input:
New app needs an API service, Postgres, object storage, and private networking.

Reference standard:
Approved AWS template showing internal VPC, subnet, RDS, S3, IAM, and logging patterns.

Expected behavior:
Generate GCP-native Terraform using private Cloud SQL, GCS with safe defaults,
least-privilege service accounts, labels, logging, and no public database access.
```

Once DSPy produces better instructions or few-shot examples, those can be copied back into the ADK agents. Later, if useful, optimized DSPy modules could be wrapped directly inside ADK tools or agents.

## Metrics to Define

DSPy needs measurable quality signals. Good initial metrics would be:

- generated Terraform has the expected file structure,
- required GCP services are present,
- Cloud SQL has no public IP,
- storage buckets use uniform bucket-level access and versioning,
- IAM avoids owner, editor, and wildcard permissions,
- labels are present,
- unsupported or ambiguous requirements are surfaced as assumptions,
- output follows the required format,
- generated architecture matches the intended application pattern.

Some checks should be deterministic Python policy checks rather than LLM review. The LLM can explain findings, but hard compliance gates should be code where possible.

## What We Need Next

To make DSPy useful, collect a small but high-quality standards dataset:

1. 5-10 approved AWS CloudFormation templates.
2. A short annotation for each template describing the standard it represents.
3. A desired GCP-native architecture pattern for each.
4. Mandatory compliance rules.
5. A few new-app prompts that should produce GCP-only infrastructure.

The AWS templates alone are helpful, but templates plus annotations and expected GCP patterns are much more valuable.

## Recommendation

Use DSPy, but use it deliberately.

Do not add DSPy just as another runtime dependency around the current agent. Start with a DSPy evaluation and optimization harness that learns from internal standards examples. Keep ADK as the deployed agent framework. Add deterministic validators for non-negotiable compliance controls.

This gives CloudBridge a stronger direction: not migration-by-conversion, but GCP infrastructure generation guided by proven internal standards.
