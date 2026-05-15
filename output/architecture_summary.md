# CloudBridge architecture summary

This starter bundle was generated from an AWS CloudFormation template.
It maps supported AWS resources to Google Cloud equivalents for review.

## Resource mapping

| AWS logical id | AWS type | GCP Terraform target |
| --- | --- | --- |
| `MainVpc` | `AWS::EC2::VPC` | `google_compute_network` |
| `PublicWebSubnet` | `AWS::EC2::Subnet` | `google_compute_subnetwork` |
| `PrivateAppSubnet` | `AWS::EC2::Subnet` | `google_compute_subnetwork` |
| `PrivateDbSubnet` | `AWS::EC2::Subnet` | `google_compute_subnetwork` |
| `WebSecurityGroup` | `AWS::EC2::SecurityGroup` | `google_compute_firewall` |
| `AppSecurityGroup` | `AWS::EC2::SecurityGroup` | `google_compute_firewall` |
| `DatabaseSecurityGroup` | `AWS::EC2::SecurityGroup` | `google_compute_firewall` |
| `AppInstanceRole` | `AWS::IAM::Role` | `google_service_account` |
| `WebLaunchTemplate` | `AWS::EC2::LaunchTemplate` | `google_compute_instance_template` |
| `AppServer` | `AWS::EC2::Instance` | `google_compute_instance` |
| `ContentBucket` | `AWS::S3::Bucket` | `google_storage_bucket` |
| `AppDatabase` | `AWS::RDS::DBInstance` | `google_sql_database_instance` |

## Parser warnings

- Unsupported for MVP: AppDbSubnetGroup (AWS::RDS::DBSubnetGroup)

## AWS to GCP visual flow

See `aws-to-gcp-ascii-flow.md` for the ASCII side-by-side conversion diagram showing what existed in AWS and the corresponding GCP Terraform resources.

## Review notes

- Validate networking, routing, and private service access before applying.
- Replace starter machine tiers with workload-appropriate sizing.
- Review IAM bindings against least-privilege requirements.
