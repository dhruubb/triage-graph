# RB-014 · PostgreSQL replication lag
Services: orders-db
Severity hint: SEV3, SEV2 if read replicas serve stale order status
Owner: Database Reliability

## Symptoms
- Replica lag rises above 60 seconds.
- Customers see stale order status on pages that read from replicas.
- Logs show `canceling statement due to conflict with recovery`.

## Diagnosis
1. [low] Measure lag on the primary: `psql -c "SELECT client_addr, state, replay_lag FROM pg_stat_replication;"`
2. [low] Check for long-running queries on the replica that block replay.
3. [low] Check replica disk I/O and CPU saturation.

## Remediation
1. [low] Route read traffic back to the primary temporarily: `flagctl set orders.read_from_replica off`
2. [medium] Cancel long-running replica queries: `psql -h <replica> -c "SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE now() - query_start > interval '5 minutes';"`
3. [high] Rebuild the replica from a fresh base backup if it cannot catch up.

## Rollback
- Turn replica reads back on once lag is under 5 seconds: `flagctl set orders.read_from_replica on`

## Escalation
Database Reliability on-call.
