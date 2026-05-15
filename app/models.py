"""Pydantic schemas and constants for CloudBridge."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SUPPORTED_TYPES: dict[str, str] = {
    "AWS::EC2::VPC": "google_compute_network",
    "AWS::EC2::Subnet": "google_compute_subnetwork",
    "AWS::EC2::SecurityGroup": "google_compute_firewall",
    "AWS::EC2::Instance": "google_compute_instance",
    "AWS::EC2::LaunchTemplate": "google_compute_instance_template",
    "AWS::RDS::DBInstance": "google_sql_database_instance",
    "AWS::S3::Bucket": "google_storage_bucket",
    "AWS::IAM::Role": "google_service_account",
    "AWS::IAM::Policy": "google_project_iam_member",
    "AWS::IAM::ManagedPolicy": "google_project_iam_member",
}


class ParsedResource(BaseModel):
    logical_id: str
    aws_type: str
    gcp_target: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ResourceList(BaseModel):
    resources: list[ParsedResource]
    unsupported: list[ParsedResource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MappingItem(BaseModel):
    aws_logical_id: str
    aws_type: str
    gcp_resource_type: str
    gcp_name: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)


class TranslationPlan(BaseModel):
    mappings: list[MappingItem]
    iam_bindings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TerraformBundle(BaseModel):
    main_tf: str
    variables_tf: str = ""
    iam_tf: str = ""
    outputs_tf: str = ""
    architecture_summary_md: str = ""


class ComplianceFinding(BaseModel):
    rule_id: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    resource: str
    issue: str
    recommended_fix: str


class ComplianceResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    findings: list[ComplianceFinding] = Field(default_factory=list)


class FinalPackage(BaseModel):
    files: dict[str, str]
    compliance: ComplianceResult
    parsed: ResourceList | None = None
    translation: TranslationPlan | None = None
    output_dir: str | None = None
