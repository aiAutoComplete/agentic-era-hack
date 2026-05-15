output "main_vpc_network_self_link" {
  value = google_compute_network.main_vpc.self_link
}

output "content_bucket_bucket_name" {
  value = google_storage_bucket.content_bucket.name
}

output "app_database_connection_name" {
  value = google_sql_database_instance.app_database.connection_name
}
