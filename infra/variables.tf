variable "project_id" {
  description = "GCP project id"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "europe-west4"
}

variable "zone" {
  description = "GCP zone (empty = region minus a)"
  type        = string
  default     = ""
}

variable "machine_type" {
  description = "Machine type. e2-highmem-4 = 4 vCPU / 16GB, the minimum comfortable spot option for the MaleCNS kernel."
  type        = string
  default     = "e2-highmem-4"
}

variable "boot_disk_gb" {
  description = "Boot disk size in GB (MaleCNS dataset is several GB; 25 leaves room for checkpoints)"
  type        = number
  default     = 25
}

variable "repo_url" {
  description = "flywalker git repo URL. The VM clones this on boot - push the repo before applying."
  type        = string
  default     = "https://github.com/franBec/flywalker.git"
}

variable "repo_ref" {
  description = "Git ref the VM checks out (branch or commit sha). Pin a sha for reproducible runs."
  type        = string
  default     = "main"
}

variable "mapillary_token" {
  description = "Mapillary v4 access token. Passed to the VM via custom metadata and written to .env on disk; never committed."
  type        = string
  sensitive   = true
}

variable "fly_brain" {
  description = "Brain implementation on the VM: real (MaleCNS dataset) or mock"
  type        = string
  default     = "real"
}

variable "create_backup_bucket" {
  description = "Create a GCS bucket for run-log backups (costs cents/month, keeps JSONL safe if the VM dies)"
  type        = bool
  default     = false
}
