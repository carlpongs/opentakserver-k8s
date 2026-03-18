# Troubleshooting — OpenTAK Server on MicroK8s

This document covers every issue encountered during the deployment and how each was resolved. If you're following the [README](README.md) and hit a problem, check here first.

---

## Table of Contents

- [1. MicroK8s Permission Denied](#1-microk8s-permission-denied)
- [2. Pod Stuck in Pending](#2-pod-stuck-in-pending)
- [3. OTS Crashes — "Connection refused" on port 5432](#3-ots-crashes--connection-refused-on-port-5432)
- [4. OTS Crashes — "role 'ots' does not exist"](#4-ots-crashes--role-ots-does-not-exist)
- [5. OTS Crashes — "AMQPConnectionError"](#5-ots-crashes--amqpconnectionerror)
- [6. OTS Crashes — "constraint does not exist" (Migration Bug)](#6-ots-crashes--constraint-does-not-exist-migration-bug)
- [7. Init Container Stuck at Init:0/1](#7-init-container-stuck-at-init01)
- [8. Curl Returns HTTP 000](#8-curl-returns-http-000)
- [9. Port 8080 Returns Nothing But Pod is Running](#9-port-8080-returns-nothing-but-pod-is-running)
- [10. "No callback tokens file" Warning](#10-no-callback-tokens-file-warning)
- [11. Gevent AssertionError on Python 3.13](#11-gevent-assertionerror-on-python-313)
- [12. OTS Container Restarts 1–3 Times on Startup](#12-ots-container-restarts-13-times-on-startup)

---

## 1. MicroK8s Permission Denied

### Symptom

```
Insufficient permissions to access MicroK8s.
You can either try again with sudo or add the user carl to the 'microk8s' group
```

### Cause

Your user is not in the `microk8s` group, or you haven't reloaded the group membership.

### Solution

```bash
sudo usermod -a -G microk8s $USER
sudo chown -R $USER ~/.kube
newgrp microk8s
```

**If it still doesn't work** (common when running from scripts or tools), use `sudo` before microk8s commands:

```bash
sudo microk8s kubectl get nodes
```

Or set up passwordless sudo for microk8s only:

```bash
sudo bash -c 'echo "'$USER' ALL=(ALL) NOPASSWD: /snap/bin/microk8s" >> /etc/sudoers.d/microk8s'
```

---

## 2. Pod Stuck in Pending

### Symptom

```
NAME                             READY   STATUS    RESTARTS   AGE
opentakserver-xxxxx-xxxxx        0/3     Pending   0          2m
```

### Cause

Usually means the PersistentVolumeClaim can't be fulfilled — either the `hostpath-storage` add-on isn't enabled, or there's insufficient disk space.

### Solution

```bash
# Enable the storage add-on
microk8s enable hostpath-storage

# Check PVC status
sudo microk8s kubectl get pvc -n opentakserver
```

If PVCs show `Pending`, describe them for details:

```bash
sudo microk8s kubectl describe pvc -n opentakserver
```

---

## 3. OTS Crashes — "Connection refused" on port 5432

### Symptom

```
psycopg.OperationalError: connection failed: connection to server at "127.0.0.1",
port 5432 failed: Connection refused
```

### Cause

OpenTAK Server (v1.7.x+) requires PostgreSQL as its database. Earlier versions used SQLite, but current versions need a running Postgres instance.

### Solution

Add a PostgreSQL sidecar container to the same pod. By running in the same pod, Postgres is accessible at `127.0.0.1:5432` — no extra networking needed.

The deployment manifest in this repo already includes PostgreSQL. If you're building your own, add this container to your pod spec:

```yaml
- name: postgres
  image: postgres:16-alpine
  env:
    - name: POSTGRES_DB
      value: ots
    - name: POSTGRES_USER
      value: ots
    - name: POSTGRES_PASSWORD
      value: ots
  ports:
    - containerPort: 5432
```

> **Critical**: The database name, user, and password must all be `ots`. This is the default OTS expects.

---

## 4. OTS Crashes — "role 'ots' does not exist"

### Symptom

```
FATAL: role "ots" does not exist
```

### Cause

PostgreSQL was configured with a different username (e.g., `opentakserver`) but OTS hardcodes its connection string to use the role `ots`.

From the OTS config:
```yaml
SQLALCHEMY_DATABASE_URI: postgresql+psycopg://ots:POSTGRESQL_PASSWORD@127.0.0.1/ots
```

### Solution

Set the Postgres environment variables to match what OTS expects:

```yaml
env:
  - name: POSTGRES_DB
    value: ots         # NOT "opentakserver"
  - name: POSTGRES_USER
    value: ots         # NOT "opentakserver"
  - name: POSTGRES_PASSWORD
    value: ots
```

If you already created the database with the wrong credentials, you must **delete the PVC** and redeploy to start fresh:

```bash
sudo microk8s kubectl delete deployment opentakserver -n opentakserver
sudo microk8s kubectl delete pvc pg-data -n opentakserver
# Re-apply manifests
sudo microk8s kubectl apply -f persistent-volume.yaml
sudo microk8s kubectl apply -f deployment.yaml
```

---

## 5. OTS Crashes — "AMQPConnectionError"

### Symptom

```
pika.exceptions.AMQPConnectionError
```

### Cause

OpenTAK Server uses RabbitMQ as a message broker for internal communication. The OTS config shows:

```yaml
OTS_RABBITMQ_SERVER_ADDRESS: 127.0.0.1
OTS_RABBITMQ_USERNAME: guest
OTS_RABBITMQ_PASSWORD: guest
```

### Solution

Add a RabbitMQ sidecar container to the same pod:

```yaml
- name: rabbitmq
  image: rabbitmq:3-alpine
  ports:
    - containerPort: 5672
```

RabbitMQ's default credentials are `guest/guest`, which matches what OTS expects. No extra configuration needed.

---

## 6. OTS Crashes — "constraint does not exist" (Migration Bug)

### Symptom

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedObject)
constraint "device_profiles_eud_uid_fkey" of relation "device_profiles" does not exist
[SQL: ALTER TABLE device_profiles DROP CONSTRAINT device_profiles_eud_uid_fkey]
```

### Cause

This is a **bug in OpenTAK Server `latest` (v1.7.8)** at the time of writing. The Alembic database migration tries to drop a foreign key constraint that was never created on a fresh database. This happens only when running migrations against a brand-new Postgres instance.

### Solution

Pin to version **1.7.7** instead of `latest`:

```yaml
image: ghcr.io/brian7704/opentakserver:1.7.7   # NOT :latest
```

If you accidentally ran with `latest` and corrupted the migration state, delete both PVCs and start fresh:

```bash
sudo microk8s kubectl delete deployment opentakserver -n opentakserver
sudo microk8s kubectl delete pvc ots-data pg-data -n opentakserver
# Re-apply all manifests
```

> **Check for updates**: This bug may be fixed in future OTS releases. Check the [OpenTAK Server releases](https://github.com/brian7704/OpenTAKServer/releases) before pinning.

---

## 7. Init Container Stuck at Init:0/1

### Symptom

```
NAME                            READY   STATUS     RESTARTS   AGE
opentakserver-xxxxx-xxxxx       0/2     Init:0/1   0          5m
```

### Cause

If you add an init container to wait for Postgres, it will never succeed because **init containers run before all other containers in the pod**. Since Postgres is a sidecar (not an external service), it hasn't started yet when the init container runs.

### Solution

**Don't use init containers for sidecar readiness checks.** Instead, let Kubernetes' default `restartPolicy: Always` handle it — OTS will crash-loop 1–2 times and then stabilize once Postgres and RabbitMQ are ready.

This is the standard pattern for sidecar containers in Kubernetes.

---

## 8. Curl Returns HTTP 000

### Symptom

```bash
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:30443
# Returns: HTTP 000
```

### Cause

HTTP 000 means curl couldn't connect at all. Common causes:
- The pod is still starting up
- You're hitting the wrong port
- The container is bound to localhost only

### Solution

1. **Check if the pod is actually running**: `sudo microk8s kubectl get pods -n opentakserver`
2. **Use the correct port**: OTS API is on port `8081` (NodePort `30081`), not `8080`
3. **Check listener address** (see issue #9 below)

---

## 9. Port 8080 Returns Nothing But Pod is Running

### Symptom

The pod shows `3/3 Running` but no HTTP response on port 8080/8443.

### Cause

The OTS Docker image does **not** include Nginx. In the official Docker-Compose setup, Nginx is a separate container that proxies ports 8080 (HTTP) and 8443 (HTTPS) to OTS on port 8081.

Additionally, OTS defaults to binding on `127.0.0.1` (loopback only), which means the Kubernetes service can't route external traffic to it.

The OTS config shows:
```yaml
OTS_LISTENER_ADDRESS: 127.0.0.1
OTS_LISTENER_PORT: 8081
```

### Solution

1. **Set the listener to bind to all interfaces** with an environment variable:

```yaml
env:
  - name: OTS_LISTENER_ADDRESS
    value: "0.0.0.0"
```

2. **Expose port 8081** in your service (not 8080):

```yaml
ports:
  - name: api
    port: 8081
    targetPort: 8081
    nodePort: 30081
```

3. **Access via**: `http://localhost:30081/api/login`

---

## 10. "No callback tokens file" Warning

### Symptom

```
No callback tokens file.
```

This appears when enabling the `dashboard` add-on.

### Cause

This is a benign message indicating no external authentication callback is configured.

### Solution

**Ignore it.** This has no effect on functionality for local development.

---

## 11. Gevent AssertionError on Python 3.13

### Symptom

```
AssertionError:
Exception ignored in: <bound method _ForkHooks.after_fork_in_child>
  assert sys.version_info[:2] < (3, 13)
AssertionError
```

### Cause

The gevent library used by OTS has a compatibility check for Python 3.13 that raises an assertion. The OTS Docker image uses Python 3.13 but the bundled gevent version hasn't been updated.

### Solution

**Ignore it.** This is a non-fatal warning. OTS continues to function normally despite these assertion messages in the logs.

---

## 12. OTS Container Restarts 1–3 Times on Startup

### Symptom

```
NAME                             READY   STATUS    RESTARTS      AGE
opentakserver-xxxxx-xxxxx        3/3     Running   2 (30s ago)   2m
```

### Cause

This is **expected behavior**. All 3 containers (Postgres, RabbitMQ, OTS) start simultaneously. OTS needs both Postgres and RabbitMQ to be accepting connections before it can initialize, but they take a few seconds to boot. OTS crashes, K8s restarts it, and on the 2nd or 3rd attempt everything is ready.

### Solution

**This is normal.** No action needed. The pod will stabilize at `3/3 Running` within ~2 minutes.

If restarts exceed 5+ or the pod enters `CrashLoopBackOff` for more than 5 minutes, check the OTS logs:

```bash
sudo microk8s kubectl logs -n opentakserver -l app=opentakserver -c opentakserver --tail=50
```

---

## Diagnostic Commands

When reporting issues, gather this information:

```bash
# Full pod description (events, conditions, container statuses)
sudo microk8s kubectl describe pod -n opentakserver

# All resource statuses
sudo microk8s kubectl get all -n opentakserver

# PVC statuses
sudo microk8s kubectl get pvc -n opentakserver

# Container logs (all 3)
for c in opentakserver postgres rabbitmq; do
  echo "=== $c ==="
  sudo microk8s kubectl logs -n opentakserver -l app=opentakserver -c $c --tail=30
done

# MicroK8s status
microk8s status
```

---

## Nuclear Option — Complete Reset

If everything is broken and you want to start completely fresh:

```bash
# Delete the entire namespace (removes all resources)
sudo microk8s kubectl delete namespace opentakserver

# Re-apply everything from scratch
sudo microk8s kubectl apply -f namespace.yaml
sudo microk8s kubectl apply -f persistent-volume.yaml
sudo microk8s kubectl apply -f deployment.yaml
sudo microk8s kubectl apply -f service.yaml
```
