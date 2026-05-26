import json
import tempfile
import unittest
from pathlib import Path

from app.diagram_pipeline import generate_diagram_package
from app.parsers.cloudformation import (
    parse_cloudformation_manifest,
    parse_cloudformation_path,
)
from app.parsers.terraform import parse_terraform_manifest

AWS_TEMPLATE = """
Resources:
  AppVpc:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: 10.0.0.0/16
      Tags:
        - Key: Name
          Value: app-prod-vpc
  PrivateSubnet:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: !Ref AppVpc
      CidrBlock: 10.0.1.0/24
      MapPublicIpOnLaunch: false
  AppDb:
    Type: AWS::RDS::DBInstance
    Properties:
      Engine: postgres
      PubliclyAccessible: false
      StorageEncrypted: true
  AppBucket:
    Type: AWS::S3::Bucket
    Properties:
      VersioningConfiguration:
        Status: Enabled
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
  AppRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument: {}
"""


GCP_TERRAFORM = """
resource "google_compute_network" "app" {
  name                    = "app-prod-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private" {
  name          = "app-private"
  ip_cidr_range = "10.0.1.0/24"
  network       = google_compute_network.app.id
}

resource "google_sql_database_instance" "app" {
  name                = "app-postgres"
  database_version    = "POSTGRES_15"
  deletion_protection = true

  settings {
    ip_configuration {
      ipv4_enabled = false
    }
  }
}

resource "google_storage_bucket" "app" {
  name                        = "app-prod-data"
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

resource "google_service_account" "app" {
  account_id = "app-runtime"
}
"""


class DiagramPipelineTests(unittest.TestCase):
    def test_cloudformation_manifest_extracts_reference_standards(self) -> None:
        manifest = parse_cloudformation_manifest(AWS_TEMPLATE)

        self.assertEqual(manifest.provider, "aws")
        self.assertEqual(manifest.purpose, "reference")
        self.assertGreaterEqual(len(manifest.resources), 5)
        self.assertIn(
            "Private database access", {control.name for control in manifest.controls}
        )
        self.assertIn(
            "Storage protection", {control.name for control in manifest.controls}
        )
        self.assertIn(
            "IAM least privilege boundary",
            {control.name for control in manifest.controls},
        )

    def test_cloudformation_path_accepts_reference_template_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "network.yaml").write_text(AWS_TEMPLATE)
            (root / "storage.yaml").write_text(
                """
Resources:
  AuditBucket:
    Type: AWS::S3::Bucket
    Properties:
      VersioningConfiguration:
        Status: Enabled
"""
            )

            manifest = parse_cloudformation_path(root)

            self.assertEqual(manifest.provider, "aws")
            self.assertEqual(len(manifest.source_files), 2)
            self.assertIn(
                "AuditBucket", {resource.id for resource in manifest.resources}
            )

    def test_terraform_manifest_extracts_gcp_target_controls(self) -> None:
        manifest = parse_terraform_manifest(GCP_TERRAFORM)

        self.assertEqual(manifest.provider, "gcp")
        self.assertEqual(manifest.purpose, "target")
        self.assertIn(
            "google_sql_database_instance.app",
            {resource.id for resource in manifest.resources},
        )
        self.assertIn(
            "Private database access", {control.name for control in manifest.controls}
        )
        self.assertIn(
            "Storage protection", {control.name for control in manifest.controls}
        )

    def test_diagram_package_writes_manifests_markdown_and_image_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aws_path = root / "reference.yaml"
            tf_dir = root / "terraform"
            out_dir = root / "diagrams"
            tf_dir.mkdir()
            aws_path.write_text(AWS_TEMPLATE)
            (tf_dir / "main.tf").write_text(GCP_TERRAFORM)

            package = generate_diagram_package(
                aws_reference=aws_path,
                gcp_terraform=tf_dir,
                output_dir=out_dir,
                render_images=False,
                approval_confirmed=True,
            )

            expected = {
                "aws_reference_manifest.json",
                "gcp_target_manifest.json",
                "standards_mapping_manifest.json",
                "aws_reference_diagram.md",
                "gcp_target_diagram.md",
                "standards_mapping_diagram.md",
            }
            self.assertTrue(
                expected.issubset({path.name for path in package.artifacts})
            )
            for artifact in expected:
                self.assertTrue((out_dir / artifact).is_file(), artifact)

            mapping = json.loads(
                (out_dir / "standards_mapping_manifest.json").read_text()
            )
            self.assertIn("mappings", mapping)
            self.assertGreaterEqual(len(mapping["mappings"]), 3)

    def test_diagram_package_requires_human_approval_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aws_path = root / "reference.yaml"
            tf_dir = root / "terraform"
            tf_dir.mkdir()
            aws_path.write_text(AWS_TEMPLATE)
            (tf_dir / "main.tf").write_text(GCP_TERRAFORM)

            with self.assertRaisesRegex(ValueError, "human approval"):
                generate_diagram_package(
                    aws_reference=aws_path,
                    gcp_terraform=tf_dir,
                    output_dir=root / "diagrams",
                    approval_confirmed=False,
                )


if __name__ == "__main__":
    unittest.main()
