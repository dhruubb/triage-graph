# RB-015 · Kubernetes node NotReady or disk pressure
Services: k8s-platform
Severity hint: SEV3 for one node, SEV2 if several nodes are affected
Owner: Platform SRE

## Symptoms
- `kubectl get nodes` shows a node as `NotReady` or with `DiskPressure`.
- Pods on that node are evicted or stuck in `Terminating`.
- Kubelet logs show `image garbage collection failed` or `PLEG is not healthy`.

## Diagnosis
1. [low] Check node conditions: `kubectl describe node <node>`
2. [low] Check kubelet status on the node: `sudo systemctl status kubelet`
3. [low] Check disk use for images and logs: `df -h /var/lib/containerd /var/log`

## Remediation
1. [medium] Cordon and drain the node: `kubectl cordon <node> && kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`
2. [medium] Remove unused images to free disk: `sudo crictl rmi --prune`
3. [medium] Restart the kubelet: `sudo systemctl restart kubelet`
4. [high] Replace the node through the node pool if it does not recover.

## Rollback
- Uncordon the node once it is Ready: `kubectl uncordon <node>`

## Escalation
Platform SRE on-call.
