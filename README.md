# OpenTAK Server on Kubernetes (MicroK8s) — Complete Guide

A step-by-step guide to deploying [OpenTAK Server](https://opentakserver.io/) on a local Kubernetes cluster using MicroK8s. This deployment runs entirely on your own hardware — no cloud, no fees.

By the end of this guide you will have a fully functional TAK server running in a Kubernetes pod that ATAK, iTAK, and WinTAK clients can connect to.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Install MicroK8s](#step-1--install-microk8s)
- [Step 2 — Configure MicroK8s](#step-2--configure-microk8s)
- [Step 3 — Enable Add-ons](#step-3--enable-add-ons)
- [Step 4 — Deploy OpenTAK Server](#step-4--deploy-opentak-server)
- [Step 5 — Verify the Deployment](#step-5--verify-the-deployment)
- [Step 6 — Access OpenTAK Server](#step-6--access-opentak-server)
- [Architecture Overview](#architecture-overview)
- [Useful Commands](#useful-commands)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **OS**: Ubuntu/Debian Linux (tested on Ubuntu)
- **RAM**: 4 GB minimum, 8 GB+ recommended
- **CPU**: Any modern multi-core processor
- **Disk**: ~5 GB free for container images + data
- **snap**: Must be installed (comes pre-installed on Ubuntu)

Check your system:

```bash
free -h          # Check RAM
nproc            # Check CPU cores
df -h /          # Check disk space
snap --version   # Verify snap is installed
```

---

## Step 1 — Install MicroK8s

MicroK8s is a lightweight, production-grade Kubernetes distribution from Canonical that runs as a snap package.

```bash
sudo snap install microk8s --classic
```

This installs Kubernetes on your machine. No VMs, no Docker Desktop — just a native K8s cluster.

> **Note**: If MicroK8s is already installed, this command will tell you. You can check with `snap list microk8s`.

---

## Step 2 — Configure MicroK8s

### 2.1 Create the kubectl config directory

```bash
mkdir -p ~/.kube
```

### 2.2 Add your user to the `microk8s` group

This lets you run `microk8s` commands without `sudo` (after reloading the group):

```bash
sudo usermod -a -G microk8s $USER
sudo chown -R $USER ~/.kube
newgrp microk8s
```

### 2.3 (Optional) Allow passwordless sudo for microk8s

If you're running commands from scripts or tools that can't interactively enter a password:

```bash
sudo bash -c 'echo "'$USER' ALL=(ALL) NOPASSWD: /snap/bin/microk8s" >> /etc/sudoers.d/microk8s'
```

> **Security note**: This only grants passwordless sudo for the `microk8s` binary, not all commands.

### 2.4 Verify MicroK8s is running

```bash
microk8s status --wait-ready
```

You should see `microk8s is running` with a list of enabled/disabled add-ons.

### 2.5 Export the kubeconfig

```bash
microk8s config > ~/.kube/config
```

---

## Step 3 — Enable Add-ons

Enable the add-ons one at a time (chaining multiple add-ons in one command is deprecated):

```bash
microk8s enable dns
microk8s enable hostpath-storage
microk8s enable dashboard
```

**What these do:**
- **dns**: Internal DNS for pod-to-pod communication
- **hostpath-storage**: Provides a default StorageClass for persistent volumes
- **dashboard**: Web-based Kubernetes management UI

### Verify add-ons and cluster

```bash
microk8s kubectl get nodes
```

Expected output:
```
NAME          STATUS   ROLES    AGE   VERSION
your-host     Ready    <none>   Xm    v1.33.x
```

If you see `Ready`, your cluster is live.

---

## Step 4 — Deploy OpenTAK Server

### 4.1 Clone this repository

```bash
git clone <THIS_REPO_URL>
cd opentakserver-k8s
```

Or if you're building from scratch, create the directory:

```bash
mkdir -p opentakserver-k8s
cd opentakserver-k8s
```

### 4.2 Apply the manifests

Apply them in order — namespace first, then storage, then the deployment, then the service:

```bash
sudo microk8s kubectl apply -f namespace.yaml
sudo microk8s kubectl apply -f persistent-volume.yaml
sudo microk8s kubectl apply -f deployment.yaml
sudo microk8s kubectl apply -f service.yaml
```

### 4.3 Wait for startup

The pod contains 3 containers. OpenTAK Server will crash-loop 1–2 times while it waits for PostgreSQL and RabbitMQ to initialize — **this is normal**. Kubernetes automatically restarts it.

Watch the pod come up:

```bash
sudo microk8s kubectl get pods -n opentakserver -w
```

Wait until you see `3/3 Running`:

```
NAME                             READY   STATUS    RESTARTS      AGE
opentakserver-xxxxx-xxxxx        3/3     Running   2 (30s ago)   2m
```

> **Expect 1–3 restarts.** This is because all 3 containers start simultaneously, but OTS needs Postgres and RabbitMQ to be ready first. K8s handles the retry automatically.

---

## Step 5 — Verify the Deployment

### 5.1 Check pod status

```bash
sudo microk8s kubectl get pods -n opentakserver
```

All 3 containers should show `3/3 Running`.

### 5.2 Check the health endpoint

```bash
curl -s http://localhost:30081/api/health
```

Expected response:
```json
{"status":"healthy"}
```

### 5.3 Check the login page

```bash
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:30081/api/login
```

Expected: `HTTP 200`

### 5.4 View logs (if needed)

```bash
# OpenTAK Server logs
sudo microk8s kubectl logs -n opentakserver -l app=opentakserver -c opentakserver --tail=50

# PostgreSQL logs
sudo microk8s kubectl logs -n opentakserver -l app=opentakserver -c postgres --tail=20

# RabbitMQ logs
sudo microk8s kubectl logs -n opentakserver -l app=opentakserver -c rabbitmq --tail=20
```

---

## Step 6 — Access OpenTAK Server

### Web UI

Open in your browser:

```
http://localhost:30081/api/login
```

Create your first admin account and start configuring the server.

### TAK Client Connections

| Protocol | Port | Use |
|---|---|---|
| **HTTP API** | `30081` | Web UI, REST API |
| **TCP CoT** | `30088` | Unencrypted cursor-on-target |
| **SSL CoT** | `30089` | Encrypted cursor-on-target |
| **HTTPS** | `30443` | Secure API (requires Nginx proxy — see notes) |
| **Cert Enrollment** | `30446` | Client certificate provisioning |

> **Note on HTTPS (port 30443)**: The OTS Docker image does not include Nginx. For production HTTPS, you would add an Nginx sidecar or use a Kubernetes Ingress. For local practice/development, the HTTP API on port 30081 works fine.

### Connecting ATAK/iTAK

In your TAK client, add a server connection:
- **Address**: Your machine's IP address (e.g., `192.168.1.x`)
- **TCP Port**: `30088` (unencrypted) or `30089` (SSL)
- **Protocol**: TCP or SSL

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                 Kubernetes Pod                   │
│           (all containers share localhost)        │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Postgres │  │ RabbitMQ │  │  OpenTAK      │  │
│  │    16    │  │    3     │  │  Server 1.7.7 │  │
│  │          │  │          │  │               │  │
│  │ :5432    │  │ :5672    │  │ :8081 (API)   │  │
│  │          │  │          │  │ :8088 (TCP)   │  │
│  │          │  │          │  │ :8089 (SSL)   │  │
│  │          │  │          │  │ :8443 (HTTPS) │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│                                                  │
│  PVC: pg-data    (no PVC)     PVC: ots-data     │
└──────────────────┬───────────────────────────────┘
                   │
            NodePort Service
                   │
    ┌──────────────┼──────────────────┐
    │              │                  │
  :30081         :30088             :30089
  (API)        (TCP CoT)          (SSL CoT)
```

**Why sidecars?** All 3 containers run in the same pod, sharing `localhost`. This means:
- OTS connects to Postgres at `127.0.0.1:5432` — no network hop
- OTS connects to RabbitMQ at `127.0.0.1:5672` — no network hop
- All containers start/stop together as a unit

---

## Useful Commands

### Pod Management

```bash
# Status
sudo microk8s kubectl get pods -n opentakserver

# Restart the deployment (e.g., after config changes)
sudo microk8s kubectl rollout restart deployment/opentakserver -n opentakserver

# Shell into the OTS container
sudo microk8s kubectl exec -it -n opentakserver \
  $(sudo microk8s kubectl get pods -n opentakserver -o jsonpath='{.items[0].metadata.name}') \
  -c opentakserver -- sh

# View OTS config
sudo microk8s kubectl exec -n opentakserver \
  $(sudo microk8s kubectl get pods -n opentakserver -o jsonpath='{.items[0].metadata.name}') \
  -c opentakserver -- cat /app/ots/config.yml
```

### Cluster Management

```bash
# All resources in the namespace
sudo microk8s kubectl get all -n opentakserver

# Describe pod (detailed events and status)
sudo microk8s kubectl describe pod -n opentakserver

# MicroK8s dashboard
sudo microk8s dashboard-proxy
```

---

## Cleanup

### Remove the OpenTAK Server deployment only

```bash
sudo microk8s kubectl delete namespace opentakserver
```

This removes all pods, services, PVCs, and data.

### Remove MicroK8s entirely

```bash
sudo snap remove microk8s
```

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for a detailed guide on every issue encountered during this deployment and how it was resolved.
