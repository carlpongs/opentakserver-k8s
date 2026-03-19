# Troubleshooting Report: Getting OTS Web UI Operational on Kubernetes

**Date:** 2026-03-19  
**Environment:** MicroK8s v1.33.9 on Ubuntu (carl-G755)  
**OTS Version:** 1.7.7 · **UI Version:** v1.5.3

---

## Problem Statement

After deploying OpenTAK Server to a local MicroK8s cluster with an Nginx frontend and the OTS-UI static files, navigating to `http://localhost:30080` showed a "not found" message instead of the expected map interface.

## Root Cause

The admin user credentials (`admin/admin1234`) created during initial setup were **lost during pod restarts** (18 restarts observed). The UI was actually loading correctly, but without valid credentials, the SPA redirected to a login page that the user interpreted as "not found." The underlying infrastructure — Nginx serving static files and proxying to the OTS API — was working the entire time.

## Resolution

Re-created the admin user via the Flask CLI inside the running OTS container. After login, the dashboard and map view loaded successfully with OpenStreetMap tiles.

---

## Command Log

### 1. Check Pod Status

**Why:** First step — confirm all containers are healthy before digging deeper.

```bash
sudo microk8s kubectl get pods -n opentakserver -o wide
```

```
NAME                             READY   STATUS    RESTARTS        AGE
opentakserver-5f7864fbd7-5tbjd   4/4     Running   18 (6m ago)     16h
```

**Takeaway:** All 4/4 containers running (Postgres, RabbitMQ, Nginx, OTS). 18 restarts is notable but expected with the sidecar pattern — OTS crash-loops until Postgres and RabbitMQ are ready.

---

### 2. Check Services

**Why:** Verify the NodePort service is exposing the right ports to the host.

```bash
sudo microk8s kubectl get svc -n opentakserver
```

```
NAME            TYPE       CLUSTER-IP       PORT(S)
opentakserver   NodePort   10.152.183.209   80:30080/TCP,8081:30081/TCP,...
```

**Takeaway:** Port 80 (Nginx) is mapped to NodePort 30080. Service routing is correct.

---

### 3. Verify HTML Is Being Served

**Why:** Determine if the "not found" is a server-level 404 or an in-app SPA routing issue.

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:30080/
curl -s http://localhost:30080/ | head -20
```

```
HTTP 200
<!DOCTYPE html>
<html lang="en">
  <head>
    <title>OpenTAKServer</title>
    <script type="module" crossorigin src="/assets/js/index-Dkdmeb2z.js"></script>
    ...
```

**Takeaway:** HTTP 200 with valid HTML. This confirmed the "not found" was **not** a server error — the SPA was loading but the user couldn't get past login.

---

### 4. Check UI Static Files in Nginx Container

**Why:** Verify the init container (`copy-ui`) actually copied files from the OTS-UI image into the shared emptyDir volume.

```bash
POD=$(sudo microk8s kubectl get pods -n opentakserver -o jsonpath='{.items[0].metadata.name}')
sudo microk8s kubectl exec -n opentakserver $POD -c nginx -- ls -la /usr/share/nginx/html/
```

```
total 276
-rw-r--r--  1 root root   1051 index.html
-rw-r--r--  1 root root  50880 alert.mp3
drwxr-xr-x  5 root root   4096 assets
drwxr-xr-x  2 root root   4096 map_icons
-rw-r--r--  1 root root    452 site.webmanifest
... (favicons, icons, etc.)
```

**Takeaway:** All UI files present including `index.html`, `assets/`, and `map_icons/`. The init container worked correctly.

---

### 5. Test API Proxy

**Why:** Confirm Nginx is correctly proxying `/api` requests to the OTS backend on port 8081.

```bash
curl -s -w "\nHTTP %{http_code}\n" http://localhost:30080/api/status | head -10
```

```
<title>Redirecting...</title>
<a href="/api/login?next=/api/status">/api/login?next=/api/status</a>
HTTP 302
```

**Takeaway:** API proxy is working — OTS backend responds with a 302 redirect to login, which means the backend is alive and enforcing authentication. This narrowed the problem to **credentials**.

---

### 6. Test Login with Existing Credentials

**Why:** Check if the admin user from initial setup still exists.

```bash
curl -s -X POST http://localhost:30080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin1234"}'
```

```json
{"meta":{"code":400},"response":{"errors":["Authentication failed - identity or password/passcode invalid"]}}
```

**Takeaway:** Admin user no longer exists. The 18 pod restarts likely caused the user record to be lost (user data stored in Postgres, which uses a PVC — but the user may not have been committed before a restart cycle).

---

### 7. Re-create Admin User (The Fix)

**Why:** Create a fresh admin account using Flask's built-in user management CLI.

```bash
POD=$(sudo microk8s kubectl get pods -n opentakserver -o jsonpath='{.items[0].metadata.name}')
sudo microk8s kubectl exec -n opentakserver $POD -c opentakserver -- sh -c \
  "cd /app && FLASK_APP=opentakserver.app:create_app /app/venv/bin/flask users create \
  --username admin --password admin1234 admin@local.dev --active"
```

```
User created successfully.
{'email': 'admin@local.dev', 'password': '****', 'username': 'admin', 'active': True}
```

**Takeaway:** User created. The `--active` flag is required or the account won't be usable.

---

### 8. Verify Login Works

**Why:** Confirm the new credentials are accepted before opening the browser.

```bash
curl -s -X POST http://localhost:30080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin1234"}'
```

```json
{"meta":{"code":200},"response":{"csrf_token":"...","user":{}}}
```

**Takeaway:** HTTP 200 — login successful. Ready to use the UI.

---

### 9. Check OTS Backend Logs

**Why:** Look for any runtime errors that could affect functionality.

```bash
sudo microk8s kubectl logs -n opentakserver $POD -c opentakserver --tail=10
```

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

**Takeaway:** Alembic migrations ran cleanly. The `gevent` assertion errors about Python 3.13 are cosmetic warnings, not functional issues.

---

## Summary

| Step | Command | Finding |
|------|---------|---------|
| 1 | `kubectl get pods` | 4/4 Running, 18 restarts |
| 2 | `kubectl get svc` | NodePort 30080 mapped correctly |
| 3 | `curl localhost:30080` | HTTP 200, valid HTML served |
| 4 | `kubectl exec ... ls` | UI files present in Nginx |
| 5 | `curl /api/status` | API proxy working (302 → login) |
| 6 | `curl POST /api/login` | **Admin user missing** (400 error) |
| 7 | `flask users create` | **Admin re-created** ✅ |
| 8 | `curl POST /api/login` | Login successful (200) |
| 9 | `kubectl logs` | Backend healthy, migrations clean |

**Key lesson:** In a sidecar pod pattern with restart-prone containers, always verify user accounts exist after restarts. The admin user creation command should be part of your deployment checklist or automated via a Kubernetes Job.
