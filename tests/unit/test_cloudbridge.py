from pathlib import Path

from app.agent import convert_cloudformation_to_gcp, parse_cfn, read_input_template


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
