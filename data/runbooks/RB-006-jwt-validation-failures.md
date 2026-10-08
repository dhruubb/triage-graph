# RB-006 · JWT validation failures in the auth service
Services: auth-service
Severity hint: SEV2, SEV1 if no user can sign in
Owner: Identity Team

## Symptoms
- Users are logged out or receive 401 errors right after signing in.
- Logs show `invalid signature`, `kid not found` or `token used before issued`.
- Failures start after a signing-key rotation or on specific nodes only.

## Diagnosis
1. [low] Compare the `kid` in failing tokens with the published JWKS: `curl -s https://<auth-host>/.well-known/jwks.json`
2. [low] Check clock drift on auth nodes: `chronyc tracking`
3. [low] Check when the signing key last rotated in the key vault audit log.

## Remediation
1. [medium] If the JWKS cache is stale, restart the auth service pods: `kubectl rollout restart deployment/auth-service -n identity`
2. [medium] If a node clock has drifted, resync it: `sudo chronyc makestep`
3. [high] If the new signing key is broken, re-activate the previous key in the key vault and republish the JWKS.

## Rollback
- Keep the previous key published in the JWKS for 24 hours after any rotation.

## Escalation
Identity Team on-call. Security must approve any change to signing keys.
