from pathlib import Path

from app.agent import (
    _cloudbridge_response,
    convert_cloudformation_to_gcp,
    parse_cfn,
    read_input_template,
)


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


def test_chat_help_is_architecture_focused_not_repetitive() -> None:
    response = _cloudbridge_response("hello")

    assert "CloudBridge" in response
    assert "show files" in response
    assert "list output files" in response
    assert "AWS-to-GCP architecture" in response or "AWS-to-GCP" in response


def test_chat_can_show_output_file() -> None:
    response = _cloudbridge_response("show output/main.tf")

    assert "Here is `output/main.tf`" in response
    assert "google_compute_network" in response


def test_chat_declines_unrelated_topics() -> None:
    response = _cloudbridge_response("write me a poem about pizza")

    assert "I can only help with this CloudBridge architecture project" in response
