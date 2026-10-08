# RB-007 · Payments API latency spike
Services: payments-api
Severity hint: SEV2, SEV1 if payment success rate drops below 95 percent
Owner: Payments Engineering

## Symptoms
- p95 latency on `/v1/payments` rises above 2 seconds.
- Logs show `upstream request timeout` or `context deadline exceeded` when calling the payment gateway.
- The circuit breaker opens and payment success rate falls.

## Diagnosis
1. [low] Check latency by endpoint in the APM dashboard and confirm which dependency is slow.
2. [low] Check the payment gateway status page and our outbound error rate.
3. [low] Check the circuit breaker state: `curl -s http://payments-api.internal/actuator/circuitbreakers`
4. [low] Check database query latency to rule out RB-002.

## Remediation
1. [medium] Fail over to the secondary payment gateway with the feature flag: `flagctl set payments.gateway secondary`
2. [medium] Scale payments-api to absorb retries: `kubectl scale deployment/payments-api -n payments --replicas=<n>`
3. [high] Lower the gateway timeout and retry count only with Payments Engineering approval, because it can cause double charges.

## Rollback
- Switch back to the primary gateway once its error rate is normal for 30 minutes: `flagctl set payments.gateway primary`

## Escalation
Payments Engineering on-call and the incident commander. Inform Customer Support if payments fail for more than 10 minutes.
