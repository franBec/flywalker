output "instance_ip" {
  description = "Public IP of the flywalker VM (SSH only; no services are exposed)"
  value       = google_compute_instance.flywalker.network_interface[0].access_config[0].nat_ip
}

output "ssh_command" {
  description = "SSH into the VM"
  value       = "gcloud compute ssh flywalker --zone=${local.zone}"
}

output "pull_artifacts_command" {
  description = "Pull run artifacts to the local machine (artifacts then go to the VPS from here)"
  value       = "gcloud compute scp --recurse flywalker:/data/runs ./local-runs --zone=${local.zone}"
}

output "backup_bucket" {
  description = "Optional GCS bucket for run backups"
  value       = var.create_backup_bucket ? google_storage_bucket.runs_backup[0].name : null
}
