variable "project_id" {
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
