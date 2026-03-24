# OpenTAK Server on Kubernetes (MicroK8s)

Deploy [OpenTAK Server](https://opentakserver.io/) on a local Kubernetes cluster using MicroK8s. Runs entirely on your own hardware — no cloud, no fees.

Supports multiple simultaneous iTAK/ATAK/WinTAK device connections with GPS tracking on a web map.

---

## Quick Start

```bash
# 1. Install MicroK8s
sudo snap install microk8s --classic
sudo usermod -a -G microk8s $USER && newgrp microk8s

# 2. Enable required add-ons
microk8s enable dns hostpath-storage

# 3. Clone and deploy
git clone https://github.com/carlpongs/opentakserver-k8s.git
cd opentakserver-k8s
sudo microk8s kubectl apply -f namespace.yaml
sudo microk8s kubectl apply -f persistent-volume.yaml
sudo microk8s kubectl apply -f nginx-config.yaml
sudo microk8s kubectl apply -f deployment.yaml
sudo microk8s kubectl apply -f service.yaml

# 4. Wait for pod (expect 2-3 restarts while Postgres initializes)
sudo microk8s kubectl get pods -n opentakserver -w
# Wait until 5/5 Running
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                      Kubernetes Pod                            │
│                (all containers share localhost)                 │
│                                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ Postgres │ │ RabbitMQ │ │  Nginx   │ │   OpenTAK Server │  │
│  │  :5432   │ │  :5672   │ │   :80    │ │   1.7.7          │  │
│  │          │ │          │ │ Web UI + │ │                   │  │
│  │          │ │          │ │ API proxy│ │ :8081 (API)       │  │
│  │          │ │          │ │          │ │ :8088 (TCP CoT)   │  │
│  │          │ │          │ │          │ │ :8089 (SSL CoT)   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │
│  PVC: pg-data              emptyDir     PVC: ots-data         │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                NodePort Service
                       │
          ┌────────────┼────────────┐
          │            │            │
        :30080       :30088      :30089
       (Web UI)    (TCP CoT)   (SSL CoT)
```

All containers run in one pod sharing `localhost`. OTS connects to Postgres and RabbitMQ without any network hop.

---

## Access

| Service | URL |
|---|---|
| **Web UI** | `http://<YOUR_IP>:30080` |
| **TCP CoT** | `<YOUR_IP>:30088` |
| **SSL CoT** | `<YOUR_IP>:30089` |

Default admin: `admin` / `admin1234`

---

## Connecting iTAK Devices

### Generate a data package

1. Log into the web UI → **Data Packages** → generate a `.zip` for your user
2. The generated package will have internal ports — you must patch it:

```bash
# Extract, fix port, re-zip
mkdir /tmp/itak_fix && cd /tmp/itak_fix
unzip ~/admin_CONFIG_iTAK.zip
sed -i 's|:8089:ssl|:30089:ssl|g' config.pref
zip ~/admin_CONFIG_iTAK_FIXED.zip *

# Serve for phone download
cd ~ && python3 -m http.server 9999
# On phone: http://<YOUR_IP>:9999/admin_CONFIG_iTAK_FIXED.zip
```

3. Open the downloaded ZIP in iTAK to import certs and connection config

### Multiple devices

Each device needs its own user + certificate. Create additional users via the web UI, generate their data packages, and patch the port as above.

> **Tip**: Each device must have a unique callsign in iTAK settings, otherwise they appear as the same dot on the map.

---

## Manifests

| File | Purpose |
|---|---|
| `namespace.yaml` | Creates `opentakserver` namespace |
| `persistent-volume.yaml` | PVCs for Postgres and OTS data |
| `nginx-config.yaml` | Nginx config: static UI files, API proxy, WebSocket/socket.io |
| `deployment.yaml` | Pod with all containers + init containers |
| `service.yaml` | NodePort service exposing ports 30080, 30088, 30089 |

---

## Useful Commands

```bash
# Pod status
sudo microk8s kubectl get pods -n opentakserver

# Restart deployment
sudo microk8s kubectl rollout restart deployment/opentakserver -n opentakserver

# OTS logs
sudo microk8s kubectl logs -n opentakserver deployment/opentakserver -c opentakserver --tail=30

# Shell into OTS container
sudo microk8s kubectl exec -it -n opentakserver deployment/opentakserver -c opentakserver -- sh

# View OTS config
sudo microk8s kubectl exec -n opentakserver deployment/opentakserver -c opentakserver -- cat /app/ots/config.yml
```

---

## Key Findings

- OTS main process serves API on `:8081`; CoT streaming is a **separate binary** (`eud_handler`) + `cot_parser` for GPS storage
- OTS data packages hardcode internal ports — must be patched for NodePort access
- The `cot_parser` process is required for GPS points to appear on the map
- Nginx handles: static file serving, API proxy, cookie forwarding, WebSocket/socket.io upgrades, CORS header overrides
- iTAK `.p12` cert password is always `atakatak`
- Expect 2-3 crash-loop restarts on fresh deploy (Postgres/RabbitMQ startup race)

---

## Cleanup

```bash
# Remove deployment only
sudo microk8s kubectl delete namespace opentakserver

# Remove MicroK8s entirely
sudo snap remove microk8s
```

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for issues encountered during deployment and their solutions.
