locals {
  zone = var.zone != "" ? var.zone : "${var.region}-a"
}

# On-demand VM: no preemptions, walk completes in one uninterrupted run.
# ~2-3x more expensive than spot but negligible for a weekend toy (~$2-3 total).
resource "google_compute_instance" "flywalker" {
  name         = "flywalker"
  machine_type = var.machine_type
  zone         = local.zone

  tags = ["flywalker"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = var.boot_disk_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    # No access_config needed for outbound-only workloads, but SSH debugging
    # needs a public IP. There is no other inbound exposure (no 80/443).
    access_config {}
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }

  metadata = {
    flywalker-repo-url = var.repo_url
    flywalker-repo-ref = var.repo_ref
    flywalker-fly-brain = var.fly_brain
    mapillary-token    = var.mapillary_token # sensitive; readable only as root on the VM
  }

  metadata_startup_script = file("${path.module}/startup.sh")

  service_account {
    # Default SA with minimal scope; no cloud API access needed by the stack.
    email  = "${data.google_compute_default_service_account.default.email}"
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  # No firewall rules added. The default network's implicit rules and
  # default-allow-ssh apply. Everything the stack does is outbound
  # (Mapillary fetch, GCS upload).
}

data "google_compute_default_service_account" "default" {}

resource "google_storage_bucket" "runs_backup" {
  count = var.create_backup_bucket ? 1 : 0

  name          = "${var.project_id}-flywalker-runs"
  location      = var.region
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}
