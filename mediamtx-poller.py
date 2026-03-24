#!/usr/bin/env python3
"""
MediaMTX stream poller for OpenTAK Server.

Polls MediaMTX API every 5 seconds to detect new/removed streams,
and calls the OTS webhook to register/unregister them.

This exists because MediaMTX's distroless Docker image has no shell,
so runOnReady hooks that need wget/curl cannot execute.
"""

import json
import time
import urllib.request
import urllib.error
import os
import sys

MEDIAMTX_API = os.environ.get("MEDIAMTX_API", "http://127.0.0.1:9997")
OTS_API = os.environ.get("OTS_API", "http://127.0.0.1:8081")
OTS_TOKEN = os.environ.get("OTS_TOKEN", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))

known_paths = set()


def get_mediamtx_paths():
    """Get all active paths from MediaMTX API."""
    try:
        r = urllib.request.urlopen(f"{MEDIAMTX_API}/v3/paths/list", timeout=5)
        data = json.loads(r.read())
        return data.get("items", [])
    except Exception as e:
        print(f"[poller] Error fetching MediaMTX paths: {e}", flush=True)
        return []


def call_webhook(event, path_name, source_type="", source_id=""):
    """Call OTS mediamtx webhook to register/unregister a stream."""
    params = (
        f"token={OTS_TOKEN}&event={event}&path={path_name}"
        f"&rtsp_port=8554&source_type={source_type}&source_id={source_id}"
    )
    url = f"{OTS_API}/api/mediamtx/webhook?{params}"
    try:
        req = urllib.request.urlopen(url, timeout=10)
        print(f"[poller] Webhook {event} for '{path_name}': {req.status}", flush=True)
    except urllib.error.HTTPError as e:
        print(f"[poller] Webhook {event} for '{path_name}' HTTP error: {e.code} {e.read().decode()}", flush=True)
    except Exception as e:
        print(f"[poller] Webhook {event} for '{path_name}' error: {e}", flush=True)


def main():
    global known_paths

    # Read token from OTS config if not set via env
    token = OTS_TOKEN
    if not token:
        try:
            with open("/app/ots/config.yml") as f:
                for line in f:
                    if "OTS_MEDIAMTX_TOKEN" in line:
                        token = line.split(":")[1].strip()
                        break
        except Exception:
            pass

    if not token:
        print("[poller] ERROR: No OTS_MEDIAMTX_TOKEN found", flush=True)
        sys.exit(1)

    # Override global
    global OTS_TOKEN
    OTS_TOKEN = token
    print(f"[poller] Starting MediaMTX stream poller (interval={POLL_INTERVAL}s)", flush=True)

    while True:
        paths = get_mediamtx_paths()
        current_paths = set()

        for item in paths:
            name = item.get("name", "")
            source = item.get("source")
            ready = item.get("ready", False)

            if not source or not ready:
                continue

            current_paths.add(name)
            source_type = source.get("type", "")
            source_id = source.get("id", "")

            # New stream detected
            if name not in known_paths:
                print(f"[poller] New stream detected: {name} ({source_type})", flush=True)
                call_webhook("ready", name, source_type, source_id)

        # Streams that went away
        for gone in known_paths - current_paths:
            print(f"[poller] Stream gone: {gone}", flush=True)
            call_webhook("notready", gone)

        known_paths = current_paths
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
