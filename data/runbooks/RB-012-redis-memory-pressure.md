# RB-012 · Redis cache memory pressure and evictions
Services: checkout-web, auth-service
Severity hint: SEV3, SEV2 if sessions are lost
Owner: Platform SRE

## Symptoms
- Redis `evicted_keys` rises quickly and cache hit rate drops.
- Users are logged out unexpectedly because session keys are evicted.
- Logs show `OOM command not allowed when used memory > 'maxmemory'`.

## Diagnosis
1. [low] Check memory use and evictions: `redis-cli INFO memory` and `redis-cli INFO stats | grep evicted`
2. [low] Find the largest keys: `redis-cli --bigkeys`
3. [low] Check the eviction policy: `redis-cli CONFIG GET maxmemory-policy`

## Remediation
1. [medium] Add TTLs to keys written without one in the next deploy, and delete a known runaway key prefix: `redis-cli --scan --pattern '<prefix>*' | xargs redis-cli unlink`
2. [medium] Raise maxmemory if the node has headroom: `redis-cli CONFIG SET maxmemory <bytes>`
3. [high] Fail over to the replica if the primary is unresponsive: `redis-cli -p 26379 SENTINEL failover <master-name>`

## Rollback
- Restore the previous maxmemory value with `CONFIG SET`.

## Escalation
Platform SRE. Identity Team if session loss affects sign-in.
