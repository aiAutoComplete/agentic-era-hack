# CloudBridge Diagram Pipeline

CloudBridge diagrams are generated after Terraform has been reviewed and approved by a human. The diagram step is intentionally separate from the core ADK agent so the agent can keep generating and reviewing Terraform without also owning visual rendering.

The diagram pipeline treats approved AWS CloudFormation templates as standards references. It treats approved GCP Terraform as the target implementation. The AWS side is not deployed by this workflow; it explains the internal standard the GCP architecture should preserve.

## Outputs

The pipeline writes a diagram package containing:

- `aws_reference_manifest.json`
- `gcp_target_manifest.json`
- `standards_mapping_manifest.json`
- `aws_reference_diagram.md`
- `gcp_target_diagram.md`
- `standards_mapping_diagram.md`
- `diagram_package.md`
- `aws_reference_diagram.png`
- `aws_reference_diagram.svg`
- `gcp_target_diagram.png`
- `gcp_target_diagram.svg`
- `standards_mapping_diagram.png`
- `standards_mapping_diagram.svg`

The Markdown diagrams use Mermaid so they remain easy to review in source control. The PNG/SVG diagrams are rendered with `diagrams` and Graphviz for presentation or review packets.

## Pipeline

```text
Approved AWS CloudFormation reference file or directory
        |
        v
AWS architecture manifest

Approved GCP Terraform
        |
        v
GCP architecture manifest

AWS + GCP manifests
        |
        v
Standards mapping manifest
        |
        v
Markdown + PNG + SVG diagram artifacts
```

## Usage

Install runtime dependencies:

```bash
uv sync
```

Graphviz must also be installed on the machine because `diagrams` uses Graphviz to render PNG/SVG files.

Run the pipeline after Terraform approval:

```bash
uv run --with diagrams python -m app.diagram_pipeline \
  --aws-reference path/to/approved-reference.yaml \
  --gcp-terraform path/to/approved/terraform \
  --out output/diagrams \
  --approved
```

`--aws-reference` can point to one CloudFormation file or to a directory of approved reference templates.

Use `--no-images` when you only want JSON and Markdown artifacts:

```bash
uv run python -m app.diagram_pipeline \
  --aws-reference path/to/approved-reference.yaml \
  --gcp-terraform path/to/approved/terraform \
  --out output/diagrams \
  --approved \
  --no-images
```

The `--approved` flag is required so this remains a post-approval step. The diagrams should be generated from reviewed Terraform, not from an unapproved draft.

## Manifest Model

Each provider manifest contains:

- provider and purpose,
- source files,
- resources,
- relationships,
- compliance controls,
- notes.

The standards mapping manifest connects AWS reference controls to GCP target controls. For example:

- AWS RDS private posture maps to Cloud SQL private IP.
- S3 versioning/public-access controls map to GCS versioning and uniform bucket-level access.
- AWS VPC/subnet standards map to GCP VPC/subnetwork boundaries.
- AWS IAM roles and policies map to service accounts and scoped IAM bindings.

## DSPy Role

DSPy is not used in the initial renderer. The renderer is deterministic Python.

DSPy can be added later to improve:

- extracting richer architecture manifests from large templates,
- classifying resources into clearer review groups,
- generating better diagram labels,
- evaluating whether diagrams include required controls,
- optimizing prompts or examples for architecture-plan generation.

DSPy should not render the final diagrams directly. Rendering should stay deterministic so review artifacts remain stable and reproducible.

## Design Notes

- The current Terraform parser is conservative. It extracts common `resource` blocks and references from approved Terraform files without evaluating every HCL feature.
- The first version focuses on useful review artifacts, not perfect Terraform semantic analysis.
- The diagram pipeline does not replace the live ADK agent in `app/agent.py`.
