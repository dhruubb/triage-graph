# RB-001 · Pod CrashLoopBackOff or OOMKilled
Services: k8s-platform, payments-api, checkout-web
Severity hint: SEV2 (SEV1 if every replica is down)
Owner: Platform SRE

## Symptoms
- Pods restart repeatedly and show status `CrashLoopBackOff`.
- The last termination reason is `OOMKilled` or exit code 137.
- The ingress returns 502 or 503 while replicas are unavailable.

## Diagnosis
1. [low] List pods that are not running: `kubectl get pods -n <namespace> | grep -v Running`
2. [low] Read the last termination reason and events: `kubectl describe pod <pod> -n <namespace>`
3. [low] Read logs from the crashed container: `kubectl logs <pod> -n <namespace> --previous`
4. [low] Compare memory use with the limit: `kubectl top pod <pod> -n <namespace>`

## Remediation
1. [medium] If the pod was OOMKilled after a traffic increase, raise the memory limit: `kubectl set resources deployment/<deploy> -n <namespace> --limits=memory=<new-limit>`
2. [medium] If a bad ConfigMap caused the crash, fix it and restart: `kubectl rollout restart deployment/<deploy> -n <namespace>`
3. [high] If the crash started with a new release, roll back: `kubectl rollout undo deployment/<deploy> -n <namespace>`

## Rollback
- Restore the previous memory limit: `kubectl set resources deployment/<deploy> -n <namespace> --limits=memory=<old-limit>`

## Escalation
Platform SRE on-call. Hand over to the owning service team if the crash is in application code.
