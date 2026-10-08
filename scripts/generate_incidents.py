"""Generate the synthetic past-incident dataset (data/incidents.csv).

The data is synthetic and seeded, so every run produces the same file.
Run: python scripts/generate_incidents.py
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
N_INCIDENTS = 160
START = datetime(2025, 9, 1)
END = datetime(2026, 9, 14)

# (runbook_id, service choices, severity weights SEV1..SEV4, mttr range in minutes, variants)
# Each variant: (title, symptoms, root_cause, resolution)
TEMPLATES = [
    ("RB-001", ["payments-api", "checkout-web", "k8s-platform"], [1, 5, 3, 1], (20, 90), [
        ("Pods OOMKilled after traffic spike", "pods restarting, exit code 137, 503 from ingress",
         "memory limit too low for peak traffic", "raised memory limit from 512Mi to 1Gi"),
        ("CrashLoopBackOff after ConfigMap change", "CrashLoopBackOff, missing env var in logs",
         "ConfigMap key renamed without updating deployment", "fixed ConfigMap and restarted deployment"),
        ("Memory leak in image resize worker", "gradual memory growth, OOMKilled every 6 hours",
         "unbounded in-memory cache in new release", "rolled back release, fix shipped next day"),
    ]),
    ("RB-002", ["orders-db", "payments-api"], [2, 5, 2, 0], (25, 120), [
        ("Too many clients on orders database", "FATAL too many clients already, API timeouts",
         "new batch job opened connections without a pool", "terminated idle sessions and moved job to PgBouncer"),
        ("Idle in transaction sessions exhausted pool", "connection waits, idle in transaction sessions",
         "missing commit in error path of payments service", "terminated sessions and patched error handling"),
        ("Pool size doubled by deploy", "cl_waiting rising in PgBouncer",
         "DB_POOL_SIZE raised from 20 to 80 across 12 pods", "reverted DB_POOL_SIZE"),
    ]),
    ("RB-003", ["orders-db"], [6, 2, 0, 0], (45, 180), [
        ("Orders DB writes failing, disk full", "No space left on device, inserts failing",
         "inactive replication slot retained WAL after replica decommission", "dropped stale replication slot and expanded volume"),
        ("Data volume at 97 percent", "disk usage alert above 90 percent",
         "PostgreSQL logs not rotated after logging change", "deleted rotated logs and fixed logrotate"),
    ]),
    ("RB-004", ["checkout-web", "auth-service", "vpn-gateway"], [2, 2, 4, 2], (15, 240), [
        ("Checkout certificate expired", "ERR_CERT_DATE_INVALID for customers",
         "cert-manager ACME challenge failing after DNS change", "fixed DNS record and renewed certificate"),
        ("Auth certificate expires in 9 days", "certificate monitor warning",
         "manually managed certificate not tracked", "renewed and moved to cert-manager"),
        ("VPN gateway certificate expired", "branch VPN authentication failures",
         "gateway certificate expired over the weekend", "uploaded renewed certificate and restarted tunnel"),
    ]),
    ("RB-005", ["kafka-events"], [0, 3, 5, 2], (30, 200), [
        ("Order events delayed 40 minutes", "consumer lag rising on orders topic",
         "consumer replicas scaled down during cost review", "scaled consumer to 12 replicas"),
        ("Rebalance storm on payments consumers", "frequent rebalances, offset commit failed",
         "slow downstream call exceeded max.poll.interval.ms", "raised max.poll.interval.ms and added timeout"),
        ("Poison message blocking partition 7", "lag on one partition only",
         "malformed event from legacy producer", "skipped offset with owner approval and added validation"),
    ]),
    ("RB-006", ["auth-service"], [2, 4, 2, 0], (20, 150), [
        ("Users logged out after key rotation", "401 invalid signature, kid not found",
         "JWKS cache not refreshed after signing-key rotation", "restarted auth pods to refresh JWKS"),
        ("Token used before issued errors on two nodes", "intermittent 401 on specific nodes",
         "clock drift of 90 seconds on two auth nodes", "resynced chrony and added drift alert"),
    ]),
    ("RB-007", ["payments-api"], [3, 5, 2, 0], (20, 110), [
        ("Payments p95 latency above 4 seconds", "upstream request timeout to gateway",
         "primary payment gateway degraded", "failed over to secondary gateway"),
        ("Circuit breaker open on payments", "payment success rate 91 percent",
         "gateway rate limit hit after retry storm", "scaled payments-api and reduced retries"),
    ]),
    ("RB-008", ["payments-api", "checkout-web", "auth-service"], [1, 6, 2, 0], (10, 60), [
        ("Error rate up after release", "5xx after deploy, readiness probe failing",
         "new release missing database migration", "rolled back to previous revision"),
        ("Rollout stuck at 3 of 10 pods", "rollout status not completing",
         "readiness probe path changed in new version", "paused rollout and fixed probe"),
    ]),
    ("RB-009", ["k8s-platform"], [1, 4, 3, 0], (20, 120), [
        ("Intermittent DNS timeouts across services", "EAI_AGAIN and i/o timeout on internal names",
         "CoreDNS under-provisioned after cluster growth", "scaled CoreDNS and enabled autoscaler"),
        ("Services cannot resolve external APIs", "no such host for external domains",
         "bad forward block in CoreDNS ConfigMap", "reverted CoreDNS ConfigMap"),
    ]),
    ("RB-010", ["vpn-gateway"], [1, 4, 3, 0], (30, 240), [
        ("Pune branch VPN tunnel down", "IKE_SA_INIT timeout, branch cannot reach ERP",
         "ISP outage at branch", "failed over to backup internet VPN"),
        ("Partner tunnel phase 2 failing", "NO_PROPOSAL_CHOSEN",
         "partner changed encryption proposal", "aligned proposals and reloaded"),
    ]),
    ("RB-011", ["email-service"], [0, 3, 5, 2], (30, 300), [
        ("OTP emails not delivered", "deferred queue growing, 421 too many connections",
         "provider throttling our sending IP", "throttled sending and switched to backup relay"),
        ("Bounce spike on marketing domain", "550 5.7.1 rejected, SPF fail",
         "SPF record missing new relay IP", "updated SPF record"),
    ]),
    ("RB-012", ["checkout-web", "auth-service"], [0, 3, 5, 1], (15, 90), [
        ("Sessions lost during sale", "users logged out, evicted_keys rising",
         "cart keys written without TTL", "deleted runaway prefix and added TTLs"),
        ("Redis OOM command not allowed", "OOM command not allowed errors",
         "maxmemory left at default after node resize", "raised maxmemory"),
    ]),
    ("RB-013", ["checkout-web", "payments-api"], [1, 6, 3, 0], (5, 45), [
        ("500s for new checkout flow cohort", "500 errors only for flag cohort",
         "feature flag enabled new flow with missing config key", "turned flag off"),
        ("503 after config push", "missing required config in logs",
         "config key typo in YAML", "reverted config and restarted"),
    ]),
    ("RB-014", ["orders-db"], [0, 3, 5, 1], (20, 160), [
        ("Stale order status on tracking page", "replica lag above 5 minutes",
         "long analytics query on replica blocked replay", "cancelled query and moved analytics to warehouse"),
        ("Replica lag after bulk update", "replay_lag rising",
         "bulk backfill generated heavy WAL", "routed reads to primary until caught up"),
    ]),
    ("RB-015", ["k8s-platform"], [0, 2, 6, 2], (20, 120), [
        ("Node NotReady with DiskPressure", "pods evicted, DiskPressure condition",
         "container images filled root disk", "drained node and pruned images"),
        ("PLEG not healthy on worker node", "node flapping NotReady",
         "containerd hung after kernel update", "restarted kubelet and containerd, replaced node"),
    ]),
]

SEVERITIES = ["SEV1", "SEV2", "SEV3", "SEV4"]

# Some variants only make sense at certain severities (a warning is never SEV1).
VARIANT_SEVERITY = {
    "Orders DB writes failing, disk full": [1, 0, 0, 0],
    "Data volume at 97 percent": [0, 2, 3, 0],
    "Auth certificate expires in 9 days": [0, 0, 2, 3],
    "Checkout certificate expired": [3, 1, 0, 0],
    "Pool size doubled by deploy": [0, 2, 3, 0],
    "Bounce spike on marketing domain": [0, 0, 2, 3],
    "Node NotReady with DiskPressure": [0, 1, 4, 1],
}

# Variants whose title names a specific service.
VARIANT_SERVICE = {
    "Checkout certificate expired": "checkout-web",
    "Auth certificate expires in 9 days": "auth-service",
    "VPN gateway certificate expired": "vpn-gateway",
    "Too many clients on orders database": "orders-db",
    "Idle in transaction sessions exhausted pool": "payments-api",
    "500s for new checkout flow cohort": "checkout-web",
    "Sessions lost during sale": "checkout-web",
}


def generate() -> list[dict]:
    rng = random.Random(SEED)
    span = (END - START).total_seconds()
    rows = []
    # Every variant appears at least once, then the rest are drawn at random.
    picks = [(t, v) for t in TEMPLATES for v in t[4]]
    while len(picks) < N_INCIDENTS:
        t = rng.choice(TEMPLATES)
        picks.append((t, rng.choice(t[4])))
    for (rb, services, weights, (lo, hi), _), (title, symptoms, root_cause, resolution) in picks:
        service = VARIANT_SERVICE.get(title) or rng.choice(services)
        severity = rng.choices(SEVERITIES, weights=VARIANT_SEVERITY.get(title, weights))[0]
        opened = START + timedelta(seconds=rng.random() * span)
        mttr = rng.randint(lo, hi)
        rows.append({
            "opened_at": opened.replace(microsecond=0).isoformat(),
            "service": service,
            "severity": severity,
            "title": title,
            "symptoms": symptoms,
            "root_cause": root_cause,
            "resolution": resolution,
            "runbook_id": rb,
            "mttr_minutes": mttr,
            "status": "resolved",
        })
    rows.sort(key=lambda r: r["opened_at"])
    for n, r in enumerate(rows):
        r["incident_id"] = f"INC-{1001 + n}"
    return rows


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "incidents.csv"
    rows = generate()
    fields = ["incident_id", "opened_at", "service", "severity", "title", "symptoms",
              "root_cause", "resolution", "runbook_id", "mttr_minutes", "status"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} incidents to {out}")


if __name__ == "__main__":
    main()
