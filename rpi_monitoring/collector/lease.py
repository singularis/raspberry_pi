"""coordination.k8s.io Lease. Outside the cluster this process is the leader."""

import json
import os
import time
from datetime import datetime, timezone

import httpx

NAME = os.environ.get("LEASE_NAME", "lcd-collector")
NS = os.environ.get("POD_NAMESPACE", "lcd-monitor")
IDENT = os.environ.get("POD_NAME", "local")
HOLD = 30


def hold():
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return True
    token = open(token_path).read()
    ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    base = f"https://kubernetes.default.svc/apis/coordination.k8s.io/v1/namespaces/{NS}/leases/{NAME}"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())
    spec = {
        "holderIdentity": IDENT,
        "leaseDurationSeconds": HOLD,
        "renewTime": now,
        "acquireTime": now,
    }
    try:
        cur = httpx.get(base, headers=headers, verify=ca, timeout=4)
    except Exception:
        return False
    if cur.status_code == 404:
        body = {"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": {"name": NAME}, "spec": spec}
        made = httpx.post(base.rsplit("/", 1)[0], headers=headers, verify=ca, content=json.dumps(body), timeout=4)
        if made.status_code in (200, 201):
            return True
        if made.status_code != 409:
            print("lease create", made.status_code)
            return False
        cur = httpx.get(base, headers=headers, verify=ca, timeout=4)
    if cur.status_code != 200:
        return False
    obj = cur.json()
    holder = (obj.get("spec") or {}).get("holderIdentity")
    if holder and holder != IDENT and not _stale((obj.get("spec") or {}).get("renewTime")):
        return False
    obj["spec"] = spec
    put = httpx.put(base, headers=headers, verify=ca, content=json.dumps(obj), timeout=4)
    return put.status_code == 200


def _stale(renew):
    if not renew:
        return True
    try:
        text = renew.replace("Z", "+00:00")
        when = datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() > HOLD
    except ValueError:
        return True


def publish(body):
    obj = _lease()
    if obj is None:
        return
    meta = obj.setdefault("metadata", {})
    ann = meta.setdefault("annotations", {})
    ann["lcd.dev/snapshot"] = json.dumps(body)
    _put(obj)


def load():
    obj = _lease()
    if not obj:
        return None
    raw = ((obj.get("metadata") or {}).get("annotations") or {}).get("lcd.dev/snapshot")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _lease():
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return None
    token = open(token_path).read()
    ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    base = f"https://kubernetes.default.svc/apis/coordination.k8s.io/v1/namespaces/{NS}/leases/{NAME}"
    headers = {"Authorization": "Bearer " + token}
    try:
        cur = httpx.get(base, headers=headers, verify=ca, timeout=4)
    except Exception:
        return None
    if cur.status_code != 200:
        return None
    return cur.json()


def _put(obj):
    token = open("/var/run/secrets/kubernetes.io/serviceaccount/token").read()
    ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    base = f"https://kubernetes.default.svc/apis/coordination.k8s.io/v1/namespaces/{NS}/leases/{NAME}"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    httpx.put(base, headers=headers, verify=ca, content=json.dumps(obj), timeout=4)
