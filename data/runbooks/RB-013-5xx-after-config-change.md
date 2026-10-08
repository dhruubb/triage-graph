# RB-013 · 5xx spike after a configuration or feature-flag change
Services: checkout-web, payments-api
Severity hint: SEV2
Owner: Release Engineering

## Symptoms
- HTTP 500 or 503 rate jumps right after a config or feature-flag change, with no code deploy.
- Errors are limited to users in the flag's rollout cohort.
- Logs show `NullPointerException`, `KeyError` or `missing required config`.

## Diagnosis
1. [low] List recent flag changes: `flagctl audit --since 2h`
2. [low] Diff the running config with the previous version in Git.
3. [low] Check whether errors match the flag cohort in the dashboard.

## Remediation
1. [low] Turn the feature flag off: `flagctl set <flag> off`
2. [medium] Revert the config change and restart the service: `kubectl rollout restart deployment/<deploy> -n <namespace>`

## Rollback
- Re-enable the flag for 1 percent of users once a fix ships: `flagctl set <flag> 1%`

## Escalation
Release Engineering and the flag owner.
