terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # Weekend toy: local state. Switch to a GCS backend if this becomes long-lived.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
