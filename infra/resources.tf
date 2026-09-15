locals {
  zone = var.zone != "" ? var.zone : "${var.region}-a"
}

# Spot VM with STOP-on-preemption:
#   - automatic_restart brings it back when capacity returns
#   - instance_termination_action = STOP keeps the boot disk (dataset, brain
#     checkpoints, run logs survive preemption)
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
    provisioning_model           = "SPOT"
    preemptible                  = true
    automatic_restart            = false
    instance_termination_action  = "STOP"
    on_host_maintenance          = "TERMINATE"
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
