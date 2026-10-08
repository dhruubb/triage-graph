# RB-010 · Site-to-site VPN tunnel down
Services: vpn-gateway
Severity hint: SEV2, SEV1 if the partner or branch office link is business-critical
Owner: Network Operations

## Symptoms
- Branch users or a partner network cannot reach internal applications.
- The gateway shows the IPsec tunnel as down or phase 2 not established.
- Logs show `IKE_SA_INIT timeout`, `NO_PROPOSAL_CHOSEN` or `AUTHENTICATION_FAILED`.

## Diagnosis
1. [low] Check tunnel status on the gateway: `sudo ipsec statusall`
2. [low] Check reachability of the peer public IP: `ping -c 5 <peer-ip>`
3. [low] Compare phase 1 and phase 2 proposals with the peer's configuration.
4. [low] Check whether the pre-shared key or a certificate was recently rotated.

## Remediation
1. [medium] Restart the tunnel: `sudo ipsec down <conn> && sudo ipsec up <conn>`
2. [medium] Correct a proposal mismatch in the connection config and reload: `sudo ipsec reload`
3. [high] Fail over branch traffic to the backup internet VPN, which reroutes all branch traffic.

## Rollback
- Fail traffic back to the primary tunnel after it is stable for 30 minutes.

## Escalation
Network Operations on-call. Contact the partner's network team for proposal or key changes.
