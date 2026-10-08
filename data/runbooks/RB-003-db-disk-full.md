# RB-003 · Database host disk full
Services: orders-db
Severity hint: SEV1 (writes fail)
Owner: Database Reliability

## Symptoms
- PostgreSQL logs show `could not extend file` or `No space left on device`.
- Inserts and updates fail while reads still work.
- The disk usage alert fires above 90 percent on the data volume.

## Diagnosis
1. [low] Check free space on the data volume: `df -h /var/lib/postgresql`
2. [low] Find the largest directories: `sudo du -xh /var/lib/postgresql --max-depth=2 | sort -h | tail -20`
3. [low] Check whether WAL is piling up because of an inactive replication slot: `psql -c "SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots;"`
4. [low] Check whether old log files are filling the volume: `ls -lh /var/log/postgresql`

## Remediation
1. [medium] Compress or remove rotated PostgreSQL logs older than 7 days: `sudo find /var/log/postgresql -name '*.log.*' -mtime +7 -delete`
2. [high] Drop an inactive replication slot that is holding WAL, after confirming the replica is gone: `psql -c "SELECT pg_drop_replication_slot('<slot_name>');"`
3. [high] Expand the data volume and grow the filesystem: `sudo resize2fs /dev/<volume>`

## Rollback
- A dropped replication slot cannot be restored. Rebuild the replica from a fresh base backup if it is still needed.

## Escalation
Database Reliability on-call immediately for SEV1. Inform the incident commander before dropping any slot.
