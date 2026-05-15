# Expected compliance findings for `input/sample-three-tier-insecure.yaml`

Status: FAIL

This report is a source-template compliance companion for the intentionally insecure sample input. It documents the problems the demo should surface when reviewing AWS CloudFormation security posture before or during AWS-to-GCP conversion.

## Findings

- `AWS_S3_PUBLIC_BUCKET` [HIGH] `PublicContentBucket`
  - Issue: S3 bucket uses `AccessControl: PublicRead` and disables all public access block settings.
  - Recommended fix: Keep S3 buckets private, enable all public access block settings, and migrate to Cloud Storage with `uniform_bucket_level_access = true` and `public_access_prevention = "enforced"`.

- `AWS_S3_PUBLIC_BUCKET_POLICY` [HIGH] `PublicContentBucketPolicy`
  - Issue: Bucket policy grants anonymous principals (`Principal: '*'`) object read, write, and delete access.
  - Recommended fix: Remove anonymous access. Use authenticated service identities and least-privilege object roles.

- `AWS_SECURITY_GROUP_ALLOW_ALL` [HIGH] `OpenWebSecurityGroup`
  - Issue: Security group allows all protocols from `0.0.0.0/0`.
  - Recommended fix: Restrict ingress to required ports and trusted source ranges only.

- `AWS_DATABASE_OPEN_TO_INTERNET` [HIGH] `OpenDatabaseSecurityGroup`
  - Issue: PostgreSQL port `5432` is open to `0.0.0.0/0`.
  - Recommended fix: Permit database access only from the application tier. In GCP, use private Cloud SQL connectivity and avoid authorized public networks.

- `AWS_NACL_ALLOW_ALL` [MEDIUM] `AllowAllInboundNaclEntry` / `AllowAllOutboundNaclEntry`
  - Issue: Network ACL allows all protocols to and from `0.0.0.0/0`.
  - Recommended fix: Replace broad NACL rules with explicit least-privilege ingress/egress rules.

- `AWS_IAM_ADMIN_WILDCARD` [HIGH] `OverPermissiveRole`
  - Issue: Inline IAM policy grants `Action: '*'` and `Resource: '*'`.
  - Recommended fix: Replace administrator-like access with least-privilege managed roles or narrowly scoped custom roles.

- `AWS_RDS_PUBLIC_NO_BACKUPS` [HIGH] `PublicDatabase`
  - Issue: RDS is publicly accessible, storage encryption is disabled, and backup retention is set to `0`.
  - Recommended fix: Disable public access, enable encryption, retain backups, and migrate to private Cloud SQL with backups and deletion protection.

## Demo note

The current generated GCP starter Terraform should still prefer secure defaults: private Cloud SQL, protected Cloud Storage, and least-privilege IAM. This file exists so the insecure source template has an explicit expected FAIL report in `output/` without changing the working agent code.
