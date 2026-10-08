# RB-002 · PostgreSQL connection pool exhaustion
Services: orders-db, payments-api
Severity hint: SEV2 (SEV1 if checkout or payments fail)
Owner: Database Reliability

## Symptoms
- Application logs show `FATAL: sorry, too many clients already` or `remaining connection slots are reserved`.
- API requests time out while waiting for a database connection.
- PgBouncer shows a growing `cl_waiting` count.

## Diagnosis
1. [low] Count connections by state: `psql -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"`
2. [low] Find long idle-in-transaction sessions: `psql -c "SELECT pid, now() - xact_start AS age, query FROM pg_stat_activity WHERE state = 'idle in transaction' ORDER BY age DESC LIMIT 20;"`
3. [low] Check PgBouncer pools: `psql -p 6432 pgbouncer -c "SHOW POOLS;"`
4. [low] Check whether a recent deploy raised the application pool size.

## Remediation
1. [medium] Terminate sessions idle in a transaction for more than 10 minutes: `psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - xact_start > interval '10 minutes';"`
2. [medium] Lower the application pool size and redeploy the service: `kubectl set env deployment/<deploy> DB_POOL_SIZE=<size>`
3. [high] Raise max_connections and restart PostgreSQL in a maintenance window: `sudo systemctl restart postgresql`

## Rollback
- Restore the previous `DB_POOL_SIZE` value and redeploy.

## Escalation
Database Reliability on-call. Involve the owning service team if one client holds most connections.
