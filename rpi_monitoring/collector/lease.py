"""coordination.k8s.io Lease. Outside the cluster this process is the leader."""

import json
import os
import time

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
    if holder and holder != IDENT:
        renew = (obj.get("spec") or {}).get("renewTime") or ""
        # stale if we cannot parse; try to take only when holder is us or missing
        if renew:
            return False
    obj["spec"] = spec
    put = httpx.put(base, headers=headers, verify=ca, content=json.dumps(obj), timeout=4)
    return put.status_code == 200
