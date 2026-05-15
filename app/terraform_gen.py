"""Deterministic Terraform generation for CloudBridge."""

from __future__ import annotations

from typing import Any

from .models import ResourceList, TerraformBundle
from .parser import _snake, _string, _tf_ref


def _emit_header() -> list[str]:
    return [
        "terraform {",
        '  required_version = ">= 1.5.0"',
        "  required_providers {",
        "    google = {",
        '      source  = "hashicorp/google"',
        '      version = "~> 6.0"',
        "    }",
        "  }",
        "}",
        "",
        'provider "google" {',
        "  project = var.project_id",
        "  region  = var.region",
        "}",
        "",
    ]


VARIABLES_TF = """variable "project_id" {
  description = "Google Cloud project id."
  type        = string
}

variable "region" {
  description = "Google Cloud region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Google Cloud zone for zonal Compute Engine resources."
  type        = string
  default     = "us-central1-a"
}

variable "name_prefix" {
  description = "Short, lowercase prefix for generated resource names."
  type        = string
  default     = "cloudbridge"
}
"""


def generate_terraform(parsed: ResourceList | dict[str, Any]) -> TerraformBundle:
    """Generate deterministic starter Terraform for supported MVP resources."""
    if isinstance(parsed, dict):
        parsed = ResourceList.model_validate(parsed)

    main: list[str] = _emit_header()
    iam: list[str] = []
    outputs: list[str] = []
    summary: list[str] = [
        "# CloudBridge architecture summary",
        "",
        "This starter bundle was generated from an AWS CloudFormation template.",
        "It maps supported AWS resources to Google Cloud equivalents for review.",
        "",
        "## Resource mapping",
        "",
        "| AWS logical id | AWS type | GCP Terraform target |",
        "| --- | --- | --- |",
    ]

    network_by_logical: dict[str, str] = {}
    subnet_by_logical: dict[str, str] = {}
    service_account_emitted = False
    first_service_account_name = "app_service_account"

    for resource in parsed.resources:
        tf_name = _snake(resource.logical_id)
        props = resource.properties
        gcp = resource.gcp_target or "unsupported"
        summary.append(f"| `{resource.logical_id}` | `{resource.aws_type}` | `{gcp}` |")

        if resource.aws_type == "AWS::EC2::VPC":
            network_by_logical[resource.logical_id] = tf_name
            main.extend(
                [
                    f'resource "google_compute_network" "{tf_name}" {{',
                    f'  name                    = "${{var.name_prefix}}-{tf_name}"',
                    "  auto_create_subnetworks = false",
                    '  routing_mode            = "REGIONAL"',
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_network_self_link" {{',
                    f"  value = google_compute_network.{tf_name}.self_link",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::EC2::Subnet":
            subnet_by_logical[resource.logical_id] = tf_name
            vpc_ref = _tf_ref(props.get("VpcId"))
            network_name = network_by_logical.get(vpc_ref or "", "main_vpc")
            cidr = _string(props.get("CidrBlock"), "10.0.0.0/24")
            private_access = (
                "true" if "private" in resource.logical_id.lower() else "false"
            )
            main.extend(
                [
                    f'resource "google_compute_subnetwork" "{tf_name}" {{',
                    f'  name                     = "${{var.name_prefix}}-{tf_name}"',
                    f'  ip_cidr_range            = "{cidr}"',
                    "  region                   = var.region",
                    f"  network                  = google_compute_network.{network_name}.id",
                    f"  private_ip_google_access = {private_access}",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::EC2::SecurityGroup":
            vpc_ref = _tf_ref(props.get("VpcId"))
            network_name = network_by_logical.get(vpc_ref or "", "main_vpc")
            main.extend(
                [
                    f'resource "google_compute_firewall" "{tf_name}_internal" {{',
                    f'  name    = "${{var.name_prefix}}-{tf_name}-internal"',
                    f"  network = google_compute_network.{network_name}.name",
                    "",
                    "  allow {",
                    '    protocol = "tcp"',
                    '    ports    = ["80", "443", "5432"]',
                    "  }",
                    "",
                    '  source_ranges = ["10.0.0.0/8"]',
                    "}",
                    "",
                ]
            )

        elif resource.aws_type in {"AWS::EC2::Instance", "AWS::EC2::LaunchTemplate"}:
            subnet_ref = _tf_ref(props.get("SubnetId")) or next(
                iter(subnet_by_logical.keys()), ""
            )
            subnet_name = subnet_by_logical.get(
                subnet_ref, next(iter(subnet_by_logical.values()), "private_app_subnet")
            )
            image = "debian-cloud/debian-12"
            instance_type = _string(props.get("InstanceType"), "e2-medium")
            if resource.aws_type == "AWS::EC2::LaunchTemplate":
                launch_data = (
                    props.get("LaunchTemplateData", {})
                    if isinstance(props.get("LaunchTemplateData"), dict)
                    else {}
                )
                instance_type = _string(launch_data.get("InstanceType"), "e2-medium")
                main.extend(
                    [
                        f'resource "google_compute_instance_template" "{tf_name}" {{',
                        f'  name_prefix  = "${{var.name_prefix}}-{tf_name}-"',
                        f'  machine_type = "{instance_type if instance_type.startswith("e2-") else "e2-medium"}"',
                        "",
                        "  disk {",
                        f'    source_image = "{image}"',
                        "    auto_delete  = true",
                        "    boot         = true",
                        "  }",
                        "",
                        "  network_interface {",
                        f"    subnetwork = google_compute_subnetwork.{subnet_name}.id",
                        "  }",
                        "}",
                        "",
                    ]
                )
            else:
                main.extend(
                    [
                        f'resource "google_compute_instance" "{tf_name}" {{',
                        f'  name         = "${{var.name_prefix}}-{tf_name}"',
                        f'  machine_type = "{instance_type if instance_type.startswith("e2-") else "e2-medium"}"',
                        "  zone         = var.zone",
                        "",
                        "  boot_disk {",
                        "    initialize_params {",
                        f'      image = "{image}"',
                        "    }",
                        "  }",
                        "",
                        "  network_interface {",
                        f"    subnetwork = google_compute_subnetwork.{subnet_name}.id",
                        "  }",
                        "}",
                        "",
                    ]
                )

        elif resource.aws_type == "AWS::RDS::DBInstance":
            engine_version = _string(props.get("EngineVersion"), "POSTGRES_15")
            if engine_version and not engine_version.upper().startswith("POSTGRES"):
                engine_version = f"POSTGRES_{engine_version.split('.')[0]}"
            main.extend(
                [
                    f'resource "google_sql_database_instance" "{tf_name}" {{',
                    f'  name             = "${{var.name_prefix}}-{tf_name}"',
                    f'  database_version = "{engine_version or "POSTGRES_15"}"',
                    "  region           = var.region",
                    "",
                    "  settings {",
                    '    tier              = "db-custom-1-3840"',
                    '    availability_type = "REGIONAL"',
                    "    backup_configuration {",
                    "      enabled                        = true",
                    "      point_in_time_recovery_enabled = true",
                    "    }",
                    "    ip_configuration {",
                    "      ipv4_enabled    = false",
                    f"      private_network = google_compute_network.{next(iter(network_by_logical.values()), 'main_vpc')}.id",
                    "    }",
                    "  }",
                    "",
                    "  deletion_protection = true",
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_connection_name" {{',
                    f"  value = google_sql_database_instance.{tf_name}.connection_name",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::S3::Bucket":
            main.extend(
                [
                    f'resource "google_storage_bucket" "{tf_name}" {{',
                    f'  name                        = "${{var.project_id}}-${{var.name_prefix}}-{tf_name}"',
                    "  location                    = var.region",
                    "  uniform_bucket_level_access = true",
                    '  public_access_prevention    = "enforced"',
                    "  force_destroy               = false",
                    "",
                    "  versioning {",
                    "    enabled = true",
                    "  }",
                    "}",
                    "",
                ]
            )
            outputs.extend(
                [
                    f'output "{tf_name}_bucket_name" {{',
                    f"  value = google_storage_bucket.{tf_name}.name",
                    "}",
                    "",
                ]
            )

        elif resource.aws_type == "AWS::IAM::Role":
            service_account_emitted = True
            first_service_account_name = tf_name
            iam.extend(
                [
                    f'resource "google_service_account" "{tf_name}" {{',
                    f'  account_id   = "${{var.name_prefix}}-{tf_name}"',
                    f'  display_name = "Service account migrated from {resource.logical_id}"',
                    "}",
                    "",
                    f'resource "google_project_iam_member" "{tf_name}_logging" {{',
                    "  project = var.project_id",
                    '  role    = "roles/logging.logWriter"',
                    f'  member  = "serviceAccount:${{google_service_account.{tf_name}.email}}"',
                    "}",
                    "",
                ]
            )

        elif resource.aws_type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}:
            role_name = first_service_account_name
            if not service_account_emitted:
                service_account_emitted = True
                role_name = "app_service_account"
                first_service_account_name = role_name
                iam.extend(
                    [
                        'resource "google_service_account" "app_service_account" {',
                        '  account_id   = "${var.name_prefix}-app"',
                        '  display_name = "Application service account"',
                        "}",
                        "",
                    ]
                )
            iam.extend(
                [
                    f'resource "google_project_iam_member" "{tf_name}_storage_viewer" {{',
                    "  project = var.project_id",
                    '  role    = "roles/storage.objectViewer"',
                    f'  member  = "serviceAccount:${{google_service_account.{role_name}.email}}"',
                    "}",
                    "",
                ]
            )

    if parsed.warnings:
        summary.extend(["", "## Parser warnings", ""])
        summary.extend(f"- {warning}" for warning in parsed.warnings)

    summary.extend(
        [
            "",
            "## Review notes",
            "",
            "- Validate networking, routing, and private service access before applying.",
            "- Replace starter machine tiers with workload-appropriate sizing.",
            "- Review IAM bindings against least-privilege requirements.",
        ]
    )

    return TerraformBundle(
        main_tf="\n".join(main).rstrip() + "\n",
        variables_tf=VARIABLES_TF,
        iam_tf="\n".join(iam).rstrip() + ("\n" if iam else ""),
        outputs_tf="\n".join(outputs).rstrip() + ("\n" if outputs else ""),
        architecture_summary_md="\n".join(summary).rstrip() + "\n",
    )
