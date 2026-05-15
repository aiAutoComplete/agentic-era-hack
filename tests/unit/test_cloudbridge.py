from pathlib import Path

import pytest

from app.agent import convert_cloudformation_to_gcp, read_input_template
from app.cloudbridge_tools import (
    generate_architecture_diagrams,
    read_project_file,
    run_compliance_review,
    write_generated_output_files,
)
from app.compliance import compliance_check
from app.parser import parse_cfn


def test_parse_sample_three_tier_template() -> None:
    template = read_input_template("sample-three-tier.yaml")
    parsed = parse_cfn(template)

    aws_types = {resource.aws_type for resource in parsed.resources}
    assert "AWS::EC2::VPC" in aws_types
    assert "AWS::EC2::Subnet" in aws_types
    assert "AWS::RDS::DBInstance" in aws_types
    assert "AWS::S3::Bucket" in aws_types
    assert "AWS::IAM::Role" in aws_types


def test_convert_sample_template_returns_expected_files() -> None:
    template = Path("input/sample-three-tier.yaml").read_text()
    result = convert_cloudformation_to_gcp(template, write_files=False)

    assert result["compliance"]["status"] == "PASS"
    assert set(result["files"]) == {
        "main.tf",
        "variables.tf",
        "iam.tf",
        "outputs.tf",
        "architecture_summary.md",
        "compliance_report.md",
    }
    assert "google_compute_network" in result["files"]["main.tf"]
    assert "google_sql_database_instance" in result["files"]["main.tf"]
    assert "Status: PASS" in result["files"]["compliance_report.md"]


def test_compliance_detects_public_sql() -> None:
    bad_tf = 'resource "google_sql_database_instance" "db" {\n  ipv4_enabled = true\n}'
    result = compliance_check(bad_tf)
    assert result.status == "FAIL"
    assert any(f.rule_id == "DB_NO_PUBLIC_IP" for f in result.findings)


def test_compliance_passes_secure_tf() -> None:
    good_tf = 'resource "google_compute_network" "vpc" {\n  name = "test"\n}'
    result = compliance_check(good_tf)
    assert result.status == "PASS"


def test_safe_project_file_rejects_path_escape() -> None:
    with pytest.raises(ValueError):
        read_project_file("../pyproject.toml")


def test_insecure_template_compliance_findings() -> None:
    result = run_compliance_review("input/sample-three-tier-insecure.yaml")
    assert result["status"] == "FAIL"
    rule_ids = {finding["rule_id"] for finding in result["findings"]}
    assert "AWS_SG_OPEN_TO_INTERNET" in rule_ids
    assert "AWS_RDS_PUBLIC" in rule_ids
    assert "AWS_IAM_WILDCARD_ADMIN" in rule_ids


def test_generate_architecture_diagrams_runs_requested_uv_command(
    tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr("app.cloudbridge_tools.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("app.cloudbridge_tools.subprocess.run", fake_run)

    result = generate_architecture_diagrams()

    assert result["status"] == "generated"
    assert calls[0][0] == [
        "uv",
        "run",
        "--with",
        "diagrams",
        "python",
        "scripts/generate_diagrams.py",
        "--all",
    ]


def test_write_generated_output_files_requires_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.cloudbridge_tools.OUTPUT_DIR", tmp_path)
    terraform_bundle = """```main.tf
resource "google_compute_network" "main" {}
```
```variables.tf
variable "project_id" { type = string }
```
```iam.tf
# iam
```
```outputs.tf
output "network" { value = "main" }
```"""

    not_written = write_generated_output_files(
        terraform_bundle=terraform_bundle,
        compliance_report="# Compliance\n",
        gcp_plan="# Plan\n",
        approval="cancel",
    )
    assert not_written["status"] == "not_written"
    assert not (tmp_path / "main.tf").exists()

    written = write_generated_output_files(
        terraform_bundle=terraform_bundle,
        compliance_report="# Compliance\n",
        gcp_plan="# Plan\n",
        approval="approve",
    )
    assert written["status"] == "written"
    assert (tmp_path / "main.tf").exists()
    assert (tmp_path / "compliance_report.md").exists()
    assert (tmp_path / "architecture_summary.md").exists()
