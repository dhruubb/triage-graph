# RB-009 · DNS resolution failures inside the cluster
Services: k8s-platform
Severity hint: SEV2, SEV1 if several services cannot reach each other
Owner: Platform SRE

## Symptoms
- Services log `getaddrinfo EAI_AGAIN`, `no such host` or `i/o timeout` on internal names.
- Errors are intermittent and affect several services at once.
- CoreDNS pods are restarting or using high CPU.

## Diagnosis
1. [low] Check CoreDNS pods: `kubectl get pods -n kube-system -l k8s-app=kube-dns`
2. [low] Test resolution from a debug pod: `kubectl run dnsutils --rm -it --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 -- nslookup kubernetes.default`
3. [low] Read CoreDNS logs for errors: `kubectl logs -n kube-system -l k8s-app=kube-dns --tail=200`
4. [low] Check conntrack table usage on nodes: `sudo conntrack -S`

## Remediation
1. [medium] Scale CoreDNS up: `kubectl scale deployment/coredns -n kube-system --replicas=<n>`
2. [medium] Restart CoreDNS if pods are stuck: `kubectl rollout restart deployment/coredns -n kube-system`
3. [high] Apply a corrected CoreDNS ConfigMap if a recent change broke forwarding: `kubectl apply -f coredns-configmap.yaml`

## Rollback
- Re-apply the previous CoreDNS ConfigMap from Git.

## Escalation
Platform SRE on-call.
