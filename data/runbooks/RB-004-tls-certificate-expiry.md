# RB-004 · TLS certificate expired or about to expire
Services: checkout-web, auth-service, vpn-gateway
Severity hint: SEV3 for a warning, SEV1 once the certificate has expired on a public endpoint
Owner: Platform Security

## Symptoms
- Browsers show `NET::ERR_CERT_DATE_INVALID`.
- Clients fail with `certificate has expired` or `x509: certificate has expired or is not yet valid`.
- The certificate monitor warns that expiry is less than 14 days away.

## Diagnosis
1. [low] Read the certificate dates from the endpoint: `echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -dates`
2. [low] Check the cert-manager Certificate resource: `kubectl describe certificate <name> -n <namespace>`
3. [low] Check for failed ACME challenges: `kubectl get challenges -A`

## Remediation
1. [medium] Trigger a renewal with cert-manager: `cmctl renew <name> -n <namespace>`
2. [medium] If the certificate is managed manually, upload the renewed certificate to the secret: `kubectl create secret tls <secret> --cert=<cert.pem> --key=<key.pem> -n <namespace> --dry-run=client -o yaml | kubectl apply -f -`
3. [medium] Reload the ingress controller so it serves the new certificate: `kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx`

## Rollback
- Re-apply the previous secret from backup if the new certificate chain is incomplete.

## Escalation
Platform Security. For the VPN gateway, also inform Network Operations.
