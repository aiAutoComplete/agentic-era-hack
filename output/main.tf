terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_compute_network" "main_vpc" {
  name                    = "${var.name_prefix}-main_vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "public_web_subnet" {
  name                     = "${var.name_prefix}-public_web_subnet"
  ip_cidr_range            = "10.20.1.0/24"
  region                   = var.region
  network                  = google_compute_network.main_vpc.id
  private_ip_google_access = false
}

resource "google_compute_subnetwork" "private_app_subnet" {
  name                     = "${var.name_prefix}-private_app_subnet"
  ip_cidr_range            = "10.20.11.0/24"
  region                   = var.region
  network                  = google_compute_network.main_vpc.id
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "private_db_subnet" {
  name                     = "${var.name_prefix}-private_db_subnet"
  ip_cidr_range            = "10.20.21.0/24"
  region                   = var.region
  network                  = google_compute_network.main_vpc.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "web_security_group_internal" {
  name    = "${var.name_prefix}-web_security_group-internal"
  network = google_compute_network.main_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "5432"]
  }

  source_ranges = ["10.0.0.0/8"]
}

resource "google_compute_firewall" "app_security_group_internal" {
  name    = "${var.name_prefix}-app_security_group-internal"
  network = google_compute_network.main_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "5432"]
  }

  source_ranges = ["10.0.0.0/8"]
}

resource "google_compute_firewall" "database_security_group_internal" {
  name    = "${var.name_prefix}-database_security_group-internal"
  network = google_compute_network.main_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "5432"]
  }

  source_ranges = ["10.0.0.0/8"]
}

resource "google_compute_instance_template" "web_launch_template" {
  name_prefix  = "${var.name_prefix}-web_launch_template-"
  machine_type = "e2-medium"

  disk {
    source_image = "debian-cloud/debian-12"
    auto_delete  = true
    boot         = true
  }

  network_interface {
    subnetwork = google_compute_subnetwork.public_web_subnet.id
  }
}

resource "google_compute_instance" "app_server" {
  name         = "${var.name_prefix}-app_server"
  machine_type = "e2-medium"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.private_app_subnet.id
  }
}

resource "google_storage_bucket" "content_bucket" {
  name                        = "${var.project_id}-${var.name_prefix}-content_bucket"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
}

resource "google_sql_database_instance" "app_database" {
  name             = "${var.name_prefix}-app_database"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = "db-custom-1-3840"
    availability_type = "REGIONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main_vpc.id
    }
  }

  deletion_protection = true
}
