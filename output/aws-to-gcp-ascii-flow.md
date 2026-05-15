# AWS to GCP Conversion Flow

```text
┌──────────────────────────────────────── AWS CloudFormation ────────────────────────────────────────┐
│                                                                                                     │
│  ┌──────────────┐     ┌────────────────────┐     ┌────────────────────┐     ┌───────────────────┐ │
│  │ AWS::EC2::VPC│────▶│ AWS::EC2::Subnet   │────▶│ AWS::EC2::Instance │────▶│ AWS::RDS::DBInst. │ │
│  │ MainVpc      │     │ Public/Private     │     │ AppServer          │     │ AppDatabase       │ │
│  └──────────────┘     └────────────────────┘     └────────────────────┘     └───────────────────┘ │
│          │                       │                         │                         │              │
│          ▼                       ▼                         ▼                         ▼              │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  │
│  │ Security Groups    │  │ Launch Template    │  │ IAM Role/Policy    │  │ S3 Content Bucket  │  │
│  │ web/app/database   │  │ WebLaunchTemplate  │  │ AppInstanceRole    │  │ ContentBucket      │  │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  │
│                                                                                                     │
└───────────────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                                │
                                                │ CloudBridge parse → map → generate → check
                                                ▼
┌────────────────────────────────────────── GCP Terraform ────────────────────────────────────────────┐
│                                                                                                     │
│  ┌─────────────────────────┐   ┌─────────────────────────────┐   ┌───────────────────────────────┐ │
│  │ google_compute_network  │──▶│ google_compute_subnetwork   │──▶│ google_compute_instance /      │ │
│  │ main_vpc                │   │ public/private subnets      │   │ instance_template              │ │
│  └─────────────────────────┘   └─────────────────────────────┘   └───────────────────────────────┘ │
│              │                                │                                   │                 │
│              ▼                                ▼                                   ▼                 │
│  ┌─────────────────────────┐   ┌─────────────────────────────┐   ┌───────────────────────────────┐ │
│  │ google_compute_firewall │   │ google_service_account +    │   │ google_sql_database_instance  │ │
│  │ web/app/db firewall     │   │ google_project_iam_member   │   │ private Cloud SQL PostgreSQL  │ │
│  └─────────────────────────┘   └─────────────────────────────┘   └───────────────────────────────┘ │
│              │                                                                    │                 │
│              ▼                                                                    ▼                 │
│  ┌─────────────────────────┐                                      ┌───────────────────────────────┐ │
│  │ google_storage_bucket   │                                      │ compliance_report.md          │ │
│  │ protected Cloud Storage │                                      │ PASS/FAIL + findings          │ │
│  └─────────────────────────┘                                      └───────────────────────────────┘ │
│                                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Side-by-side mapping

| AWS source | GCP target | Notes |
| --- | --- | --- |
| `AWS::EC2::VPC` | `google_compute_network` | Custom-mode VPC; no auto-created subnets. |
| `AWS::EC2::Subnet` | `google_compute_subnetwork` | Public/private intent preserved with regional subnets. |
| `AWS::EC2::SecurityGroup` | `google_compute_firewall` | Security group intent becomes VPC firewall rules. |
| `AWS::EC2::LaunchTemplate` | `google_compute_instance_template` | Starter template for managed compute patterns. |
| `AWS::EC2::Instance` | `google_compute_instance` | Zonal Compute Engine VM. |
| `AWS::RDS::DBInstance` | `google_sql_database_instance` | PostgreSQL on Cloud SQL, private IP, backups, deletion protection. |
| `AWS::S3::Bucket` | `google_storage_bucket` | Uniform bucket-level access and public access prevention. |
| `AWS::IAM::Role` / policy | `google_service_account` + `google_project_iam_member` | Least-privilege IAM bindings for service identity. |
