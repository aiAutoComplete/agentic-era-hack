resource "google_service_account" "app_instance_role" {
  account_id   = "${var.name_prefix}-app_instance_role"
  display_name = "Service account migrated from AppInstanceRole"
}

resource "google_project_iam_member" "app_instance_role_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.app_instance_role.email}"
}
