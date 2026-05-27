"""Small, safe tools for the CloudBridge ADK agents."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .compliance import compliance_check, compliance_report
from .models import SUPPORTED_TYPES, FinalPackage, ResourceList, TerraformBundle
from .parser import parse_cfn, translate_resources
from .terraform_gen import generate_terraform

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"
OUTPUT_DIR = REPO_ROOT / "output"
PENDING_OUTPUT_PATH = REPO_ROOT / ".cloudbridge_pending_outputs.json"
SELECTED_INPUT_PATH = REPO_ROOT / ".cloudbridge_selected_input.json"
EXPECTED_OUTPUT_FILES = (
    "main.tf",
    "variables.tf",
    "iam.tf",
    "outputs.tf",
    "architecture_summary.md",
    "compliance_report.md",
)
_ALLOWED_ROOTS = {
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLOUDBRIDGE_REDESIGN_NOTES.md",
    REPO_ROOT / "input",
    REPO_ROOT / "output",
    REPO_ROOT / "app",
}
_BLOCKED_PARTS = {".git", ".venv", "__pycache__", ".adk"}


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_project_path(path: str) -> Path:
    requested = (
        (REPO_ROOT / path).resolve()
        if not Path(path).is_absolute()
        else Path(path).resolve()
    )
    if not _is_inside(requested, REPO_ROOT):
        raise ValueError("Path must stay inside the CloudBridge repository.")
    if any(part in _BLOCKED_PARTS for part in requested.parts):
        raise ValueError("Path is blocked for safety.")
    if not any(
        requested == root.resolve() or _is_inside(requested, root)
        for root in _ALLOWED_ROOTS
    ):
        raise ValueError("Path is outside the allowed CloudBridge project areas.")
    return requested


def _read_template_or_path(template_or_path: str) -> str:
    candidate = template_or_path.strip()
    if "\n" not in candidate and not candidate.lstrip().startswith(("{", "Resources:")):
        path = _safe_project_path(candidate)
        if path.exists() and path.is_file():
            return path.read_text()
    return template_or_path


def _relative_repo_path(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _normalize_input_template_path(source_template: str | None) -> str | None:
    if not source_template:
        return None
    candidate = source_template.strip()
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_absolute() and len(path.parts) == 1:
        path = INPUT_DIR / path
    safe_path = _safe_project_path(str(path))
    if not safe_path.is_file() or not _is_inside(safe_path, INPUT_DIR):
        raise ValueError("source_template must be a readable file under input/.")
    if safe_path.suffix.lower() not in {".yaml", ".yml", ".json"}:
        raise ValueError("source_template must be a YAML or JSON template.")
    return _relative_repo_path(safe_path)


def _record_selected_input(path: Path) -> None:
    if path.is_file() and _is_inside(path, INPUT_DIR):
        SELECTED_INPUT_PATH.write_text(
            json.dumps({"source_template": _relative_repo_path(path)}, indent=2)
        )


def _last_selected_input_template() -> str | None:
    if not SELECTED_INPUT_PATH.exists():
        return None
    try:
        payload = json.loads(SELECTED_INPUT_PATH.read_text())
    except json.JSONDecodeError:
        return None
    return _normalize_input_template_path(payload.get("source_template"))


def _clear_generated_diagram_dir(diagram_dir: Path) -> None:
    if not diagram_dir.exists():
        return
    for path in diagram_dir.iterdir():
        if not path.is_file():
            continue
        is_generated_diagram = (
            path.suffix.lower() in {".png", ".svg"}
            and path.name.startswith(("aws-", "gcp-", "conversion-"))
        )
        if is_generated_diagram or path.name == "README.md":
            path.unlink()


def _package_output(
    bundle: TerraformBundle, parsed: ResourceList | None = None
) -> FinalPackage:
    result = compliance_check(bundle)
    files = {
        "main.tf": bundle.main_tf,
        "variables.tf": bundle.variables_tf,
        "iam.tf": bundle.iam_tf,
        "outputs.tf": bundle.outputs_tf,
        "architecture_summary.md": bundle.architecture_summary_md,
        "compliance_report.md": compliance_report(result),
    }
    return FinalPackage(files=files, compliance=result, parsed=parsed)


def list_project_files(scope: str = "all") -> list[str]:
    """List CloudBridge files for a safe scope: input, output, app, or all."""
    scope = scope.lower().strip()
    roots: list[Path]
    if scope == "input":
        roots = [INPUT_DIR]
    elif scope == "output":
        roots = [OUTPUT_DIR]
    elif scope == "app":
        roots = [REPO_ROOT / "app"]
    elif scope == "all":
        roots = [REPO_ROOT / "README.md", INPUT_DIR, OUTPUT_DIR, REPO_ROOT / "app"]
    else:
        raise ValueError("scope must be one of: input, output, app, all")

    files: list[str] = []
    for root in roots:
        if root.is_file():
            files.append(str(root.relative_to(REPO_ROOT)))
            continue
        if root.exists():
            for item in sorted(root.rglob("*")):
                if item.is_file() and not any(
                    part in _BLOCKED_PARTS for part in item.parts
                ):
                    files.append(str(item.relative_to(REPO_ROOT)))
    return files


def read_project_file(path: str) -> str:
    """Read an allowed CloudBridge project file safely."""
    safe_path = _safe_project_path(path)
    if not safe_path.exists() or not safe_path.is_file():
        raise FileNotFoundError(f"No readable CloudBridge file at {path!r}.")
    _record_selected_input(safe_path)
    return safe_path.read_text()


def parse_cloudformation(template_or_path: str) -> dict[str, Any]:
    """Parse CloudFormation YAML/JSON text or an allowed local path."""
    template = _read_template_or_path(template_or_path)
    parsed = parse_cfn(template)
    translation = translate_resources(parsed)
    return {
        "supported_count": len(parsed.resources),
        "unsupported_count": len(parsed.unsupported),
        "resources": [resource.model_dump() for resource in parsed.resources],
        "unsupported": [resource.model_dump() for resource in parsed.unsupported],
        "mappings": [mapping.model_dump() for mapping in translation.mappings],
        "warnings": parsed.warnings,
        "supported_types": SUPPORTED_TYPES,
    }


def build_conversion_bundle(template_or_path: str) -> dict[str, Any]:
    """Build a GCP Terraform conversion bundle without writing files."""
    template = _read_template_or_path(template_or_path)
    parsed = parse_cfn(template)
    translation = translate_resources(parsed)
    bundle = generate_terraform(parsed)
    final = _package_output(bundle, parsed=parsed)
    final.translation = translation
    return final.model_dump()


def _aws_source_findings(template_text: str) -> list[dict[str, str]]:
    parsed = parse_cfn(template_text)
    resources = [*parsed.resources, *parsed.unsupported]
    findings: list[dict[str, str]] = []
    for resource in resources:
        props = resource.properties
        body = json.dumps(props).lower()
        logical_id = resource.logical_id

        if (
            resource.aws_type == "AWS::EC2::Subnet"
            and props.get("MapPublicIpOnLaunch") is True
        ):
            findings.append(
                {
                    "rule_id": "AWS_SUBNET_PUBLIC_IP_AUTO_ASSIGN",
                    "severity": "MEDIUM",
                    "resource": logical_id,
                    "issue": "Subnet auto-assigns public IPv4 addresses.",
                    "recommended_fix": "Use private subnets for app/data tiers and explicit public ingress only at the edge.",
                }
            )
        if resource.aws_type == "AWS::EC2::SecurityGroup" and "0.0.0.0/0" in body:
            findings.append(
                {
                    "rule_id": "AWS_SG_OPEN_TO_INTERNET",
                    "severity": "HIGH",
                    "resource": logical_id,
                    "issue": "Security group allows internet-sourced traffic.",
                    "recommended_fix": "Restrict source ranges and ports to required trusted networks.",
                }
            )
        if (
            resource.aws_type == "AWS::EC2::NetworkAclEntry"
            and "0.0.0.0/0" in body
            and "allow" in body
        ):
            findings.append(
                {
                    "rule_id": "AWS_NACL_ALLOW_ALL",
                    "severity": "HIGH",
                    "resource": logical_id,
                    "issue": "Network ACL entry allows broad internet traffic.",
                    "recommended_fix": "Replace broad allow rules with least-privilege subnet ACLs.",
                }
            )
        if resource.aws_type == "AWS::S3::Bucket" and (
            "publicread" in body or ("blockpublic" in body and "false" in body)
        ):
            findings.append(
                {
                    "rule_id": "AWS_S3_PUBLIC_ACCESS",
                    "severity": "HIGH",
                    "resource": logical_id,
                    "issue": "S3 bucket appears publicly readable or lacks public access blocks.",
                    "recommended_fix": "Enable S3 Block Public Access and avoid public ACLs/policies.",
                }
            )
        if (
            resource.aws_type == "AWS::S3::BucketPolicy"
            and "principal" in body
            and "*" in body
        ):
            findings.append(
                {
                    "rule_id": "AWS_S3_POLICY_PUBLIC_PRINCIPAL",
                    "severity": "HIGH",
                    "resource": logical_id,
                    "issue": "Bucket policy grants access to a public principal.",
                    "recommended_fix": "Limit principals to named identities and required actions only.",
                }
            )
        if (
            resource.aws_type == "AWS::IAM::Role"
            and '"action": "*"' in body
            and '"resource": "*"' in body
        ):
            findings.append(
                {
                    "rule_id": "AWS_IAM_WILDCARD_ADMIN",
                    "severity": "HIGH",
                    "resource": logical_id,
                    "issue": "IAM role contains wildcard administrative permissions.",
                    "recommended_fix": "Replace wildcard permissions with least-privilege managed or custom policies.",
                }
            )
        if resource.aws_type == "AWS::RDS::DBInstance":
            if props.get("PubliclyAccessible") is True:
                findings.append(
                    {
                        "rule_id": "AWS_RDS_PUBLIC",
                        "severity": "HIGH",
                        "resource": logical_id,
                        "issue": "RDS instance is publicly accessible.",
                        "recommended_fix": "Place database in private subnets and disable public accessibility.",
                    }
                )
            if props.get("StorageEncrypted") is False:
                findings.append(
                    {
                        "rule_id": "AWS_RDS_UNENCRYPTED",
                        "severity": "HIGH",
                        "resource": logical_id,
                        "issue": "RDS storage encryption is disabled.",
                        "recommended_fix": "Enable storage encryption with a managed KMS key.",
                    }
                )
            if props.get("BackupRetentionPeriod") == 0:
                findings.append(
                    {
                        "rule_id": "AWS_RDS_BACKUPS_DISABLED",
                        "severity": "MEDIUM",
                        "resource": logical_id,
                        "issue": "RDS backups are disabled.",
                        "recommended_fix": "Set a positive backup retention period and test restore procedures.",
                    }
                )
    return findings


def run_compliance_review(
    template_or_path: str, terraform_text: str | None = None
) -> dict[str, Any]:
    """Review AWS source and optional generated Terraform for security/compliance findings."""
    template = _read_template_or_path(template_or_path)
    aws_findings = _aws_source_findings(template)
    terraform_result = (
        compliance_check(terraform_text or "") if terraform_text else None
    )
    terraform_findings = (
        [finding.model_dump() for finding in terraform_result.findings]
        if terraform_result
        else []
    )
    all_findings = [*aws_findings, *terraform_findings]
    return {
        "status": "FAIL" if all_findings else "PASS",
        "aws_findings": aws_findings,
        "terraform_findings": terraform_findings,
        "findings": all_findings,
    }


def write_project_files_after_approval(
    files: dict[str, str], approval: str
) -> dict[str, Any]:
    """Write output files only when approval is explicit."""
    if approval.strip().lower() not in {"yes", "approve", "approved", "yes approve"}:
        return {"status": "not_written", "reason": "Human approval was not explicit."}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, content in files.items():
        safe_name = Path(name).name
        if safe_name != name:
            raise ValueError("Output file names must not include directories.")
        path = OUTPUT_DIR / safe_name
        path.write_text(content)
        try:
            written[safe_name] = str(path.relative_to(REPO_ROOT))
        except ValueError:
            written[safe_name] = str(path)
    return {"status": "written", "files": written}


def _extract_fenced_files(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in re.finditer(r"```([^`\n]+)\n(.*?)\n```", text, flags=re.DOTALL):
        label = match.group(1).strip().split()[0]
        if label in {"main.tf", "variables.tf", "iam.tf", "outputs.tf"}:
            files[label] = match.group(2).strip() + "\n"
    return files


def _prepare_generated_output_files(
    terraform_bundle: str,
    compliance_report: str,
    gcp_plan: str = "",
) -> dict[str, str] | dict[str, Any]:
    files = _extract_fenced_files(terraform_bundle)
    missing = [
        name
        for name in ("main.tf", "variables.tf", "iam.tf", "outputs.tf")
        if name not in files
    ]
    if missing:
        return {"status": "not_prepared", "reason": f"Missing fenced files: {missing}"}

    files["architecture_summary.md"] = (
        gcp_plan.strip() or "# Architecture Summary\n\nNo GCP plan was provided."
    ) + "\n"
    files["compliance_report.md"] = compliance_report.strip() + "\n"
    return files


def verify_output_files(written_files: dict[str, str]) -> dict[str, Any]:
    """Verify expected output files exist and are non-empty."""
    missing = []
    verified = []
    for name in EXPECTED_OUTPUT_FILES:
        rel = written_files.get(name, f"output/{name}")
        path = (REPO_ROOT / rel).resolve()
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            verified.append(rel)
        else:
            missing.append(rel)
    if missing:
        return {"status": "failed", "missing_or_empty": missing, "files": verified}
    return {"status": "verified", "files": verified}


def write_generated_output_files(
    terraform_bundle: str,
    compliance_report: str,
    approval: str,
    gcp_plan: str = "",
) -> dict[str, Any]:
    """Write generated Terraform/report files to output/ after human approval."""
    files = _prepare_generated_output_files(
        terraform_bundle, compliance_report, gcp_plan
    )
    if files.get("status") == "not_prepared":
        return {"status": "not_written", "reason": files["reason"]}
    return write_project_files_after_approval(files, approval)  # type: ignore[arg-type]


def stage_output_package(
    terraform_bundle: str,
    compliance_report: str,
    gcp_plan: str = "",
    source_template: str | None = None,
) -> dict[str, Any]:
    """Stage generated outputs and ask the user to type exactly 'yes'."""
    files = _prepare_generated_output_files(
        terraform_bundle, compliance_report, gcp_plan
    )
    if files.get("status") == "not_prepared":
        return files
    selected_source = _normalize_input_template_path(
        source_template
    ) or _last_selected_input_template()
    pending_payload: dict[str, Any] = {"files": files}
    if selected_source:
        pending_payload["source_template"] = selected_source
    PENDING_OUTPUT_PATH.write_text(json.dumps(pending_payload, indent=2))
    return {
        "status": "pending_approval",
        "approval_required": "yes",
        "expected_output_files": [f"output/{name}" for name in EXPECTED_OUTPUT_FILES],
        "source_template": selected_source,
        "message": "Reply exactly 'yes' to write files, generate diagrams, verify artifacts, and complete the run.",
    }


def generate_architecture_diagrams(
    source_template: str | None = None,
) -> dict[str, Any]:
    """Generate AWS, GCP, and conversion diagrams for a requested template."""
    script = REPO_ROOT / "scripts" / "generate_diagrams.py"
    if not script.exists():
        return {
            "status": "not_generated",
            "reason": "scripts/generate_diagrams.py not found",
        }

    selected_source = _normalize_input_template_path(source_template)
    diagram_args = ["--all"] if selected_source is None else ["--clean", selected_source]
    if selected_source is not None:
        _clear_generated_diagram_dir(OUTPUT_DIR / "diagrams")

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--with",
                "diagrams",
                "python",
                str(script.relative_to(REPO_ROOT)),
                *diagram_args,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return {"status": "not_generated", "reason": f"{type(exc).__name__}: {exc}"}

    if result.returncode != 0:
        return {
            "status": "not_generated",
            "reason": (result.stderr or result.stdout)[-1200:],
        }

    verification = verify_diagram_files(selected_source)
    if verification["status"] != "verified":
        return {
            "status": "not_generated",
            "reason": "Diagram files were not verified after generation.",
            "verification": verification,
        }
    return {**verification, "status": "generated"}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def verify_diagram_files(source_template: str | None = None) -> dict[str, Any]:
    """Verify generated diagram artifacts exist and are non-empty."""
    diagram_dir = OUTPUT_DIR / "diagrams"
    paths = sorted(
        path
        for path in diagram_dir.glob("*")
        if path.is_file() and path.stat().st_size > 0
    )
    files = [_display_path(path) for path in paths]
    selected_source = _normalize_input_template_path(source_template)
    if selected_source is not None:
        stem = Path(selected_source).stem
        expected = [
            diagram_dir / f"{prefix}-{stem}{suffix}"
            for prefix in ("aws", "gcp", "conversion")
            for suffix in (".png", ".svg")
        ]
        expected.append(diagram_dir / "README.md")
        missing = [
            _display_path(path)
            for path in expected
            if not path.is_file() or path.stat().st_size <= 0
        ]
        if missing:
            return {
                "status": "failed",
                "reason": f"Expected diagram artifacts for {selected_source}.",
                "missing": missing,
                "files": files,
            }
        return {"status": "verified", "count": len(files), "files": files}

    has_png = any(path.suffix == ".png" for path in paths)
    has_svg = any(path.suffix == ".svg" for path in paths)
    has_readme = any(path.name == "README.md" for path in paths)
    if not (has_png and has_svg and has_readme):
        return {
            "status": "failed",
            "reason": "Expected non-empty PNG, SVG, and README diagram artifacts.",
            "files": files,
        }
    return {"status": "verified", "count": len(files), "files": files}


def commit_staged_output_package(approval: str) -> dict[str, Any]:
    """When approval is exactly 'yes', write staged outputs, diagrams, and verify all artifacts."""
    if approval.strip().lower() != "yes":
        return {"status": "not_written", "reason": "Approval must be exactly 'yes'."}
    if not PENDING_OUTPUT_PATH.exists():
        return {
            "status": "not_written",
            "reason": "No staged CloudBridge output package found.",
        }

    payload = json.loads(PENDING_OUTPUT_PATH.read_text())
    write_result = write_project_files_after_approval(payload["files"], "yes")
    output_check = verify_output_files(write_result.get("files", {}))
    if write_result.get("status") != "written" or output_check["status"] != "verified":
        return {
            "status": "failed",
            "write": write_result,
            "output_verification": output_check,
            "diagrams": {"status": "skipped"},
        }

    diagram_result = generate_architecture_diagrams(payload.get("source_template"))
    if diagram_result.get("status") != "generated":
        return {
            "status": "failed",
            "write": write_result,
            "output_verification": output_check,
            "diagrams": diagram_result,
        }

    PENDING_OUTPUT_PATH.unlink(missing_ok=True)
    return {
        "status": "complete",
        "write": write_result,
        "output_verification": output_check,
        "diagrams": diagram_result,
        "message": "CloudBridge agent run complete. Output files and diagrams were written and verified.",
    }


def write_outputs_and_generate_diagrams(
    terraform_bundle: str,
    compliance_report: str,
    gcp_plan: str = "",
) -> dict[str, Any]:
    """Backward-compatible immediate write path for tests/imports."""
    stage = stage_output_package(terraform_bundle, compliance_report, gcp_plan)
    if stage.get("status") != "pending_approval":
        return {"write": stage, "diagrams": {"status": "skipped"}}
    return commit_staged_output_package("yes")


# Backward-compatible helpers used by existing tests/imports.
def read_input_template(filename: str = "sample-three-tier.yaml") -> str:
    """Read a CloudFormation template from input/."""
    return read_project_file(f"input/{Path(filename).name}")


def convert_cloudformation_to_gcp(
    template: str, write_files: bool = False
) -> dict[str, Any]:
    """Convert CloudFormation to GCP Terraform, optionally writing output/."""
    result = build_conversion_bundle(template)
    if write_files:
        write_project_files_after_approval(result["files"], "approve")
        result["output_dir"] = "output"
    return result
