"""Compliance checks for CloudBridge generated Terraform."""

from __future__ import annotations

import re
from typing import Any

from .models import ComplianceFinding, ComplianceResult, TerraformBundle


def compliance_check(
    node_input: TerraformBundle | dict[str, Any] | str,
) -> ComplianceResult:
    """Run the README compliance checks against generated Terraform."""
    if isinstance(node_input, TerraformBundle):
        text = "\n".join(
            [
                node_input.main_tf,
                node_input.iam_tf,
                node_input.variables_tf,
                node_input.outputs_tf,
            ]
        )
    elif isinstance(node_input, dict):
        text = "\n".join(str(v) for v in node_input.values())
    else:
        text = node_input

    findings: list[ComplianceFinding] = []
    lower = text.lower()

    if re.search(r"roles/(owner|editor|iam\.securityadmin)", lower) or (
        "*" in lower and "iam" in lower
    ):
        findings.append(
            ComplianceFinding(
                rule_id="IAM_NO_WILDCARD",
                severity="HIGH",
                resource="iam.tf",
                issue="Broad IAM role or wildcard-like permission detected.",
                recommended_fix="Use least-privilege predefined roles such as roles/storage.objectViewer or roles/cloudsql.client.",
            )
        )

    if "google_sql_database_instance" in lower and (
        "ipv4_enabled = true" in lower or "authorized_networks" in lower
    ):
        findings.append(
            ComplianceFinding(
                rule_id="DB_NO_PUBLIC_IP",
                severity="HIGH",
                resource="Cloud SQL",
                issue="Cloud SQL appears to allow public IP or authorized public networks.",
                recommended_fix="Set ipv4_enabled = false and use private IP connectivity.",
            )
        )

    if "google_storage_bucket" in lower and "uniform_bucket_level_access" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="STORAGE_DEFAULT_PROTECTION",
                severity="MEDIUM",
                resource="Cloud Storage",
                issue="Bucket is missing uniform bucket-level access in generated Terraform.",
                recommended_fix="Add uniform_bucket_level_access = true to every google_storage_bucket.",
            )
        )

    if "google_storage_bucket" in lower and "public_access_prevention" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="STORAGE_PUBLIC_ACCESS_PREVENTION",
                severity="MEDIUM",
                resource="Cloud Storage",
                issue="Bucket is missing public access prevention.",
                recommended_fix='Add public_access_prevention = "enforced" to every google_storage_bucket.',
            )
        )

    if "google_sql_database_instance" in lower and "backup_configuration" not in lower:
        findings.append(
            ComplianceFinding(
                rule_id="DB_BACKUPS_REQUIRED",
                severity="MEDIUM",
                resource="Cloud SQL",
                issue="Cloud SQL backup settings are not documented or enabled.",
                recommended_fix="Enable backup_configuration and point-in-time recovery for Cloud SQL.",
            )
        )

    return ComplianceResult(status="FAIL" if findings else "PASS", findings=findings)


def compliance_report(compliance: ComplianceResult) -> str:
    """Format a compliance result as a human-readable markdown report."""
    report = [f"Status: {compliance.status}", "", "Findings:"]
    if compliance.findings:
        for finding in compliance.findings:
            report.append(
                f"- {finding.rule_id} [{finding.severity}] {finding.resource}: {finding.issue}"
            )
            report.append(f"  Fix: {finding.recommended_fix}")
    else:
        report.append("- None")
    return "\n".join(report) + "\n"
