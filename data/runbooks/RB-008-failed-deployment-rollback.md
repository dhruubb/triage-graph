# RB-008 · Failed deployment and rollback
Services: payments-api, checkout-web, auth-service
Severity hint: SEV2
Owner: Release Engineering

## Symptoms
- Error rate or latency rises within minutes of a deployment.
- New pods fail readiness probes and the rollout stalls.
- `kubectl rollout status` does not complete.

## Diagnosis
1. [low] Check the rollout: `kubectl rollout status deployment/<deploy> -n <namespace>`
2. [low] Compare revisions: `kubectl rollout history deployment/<deploy> -n <namespace>`
3. [low] Check readiness probe failures: `kubectl describe pod <new-pod> -n <namespace>`
4. [low] Compare the error rate before and after the deploy time in the dashboard.

## Remediation
1. [medium] Pause the rollout to stop more pods from updating: `kubectl rollout pause deployment/<deploy> -n <namespace>`
2. [high] Roll back to the previous revision: `kubectl rollout undo deployment/<deploy> -n <namespace>`
3. [low] Freeze further deploys for the service in the CI pipeline until the cause is known.

## Rollback
- Resume the paused rollout if the new version turns out to be healthy: `kubectl rollout resume deployment/<deploy> -n <namespace>`

## Escalation
Release Engineering and the owning service team.
