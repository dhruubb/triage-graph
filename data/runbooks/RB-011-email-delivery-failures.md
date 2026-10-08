# RB-011 · Email delivery failures or bounce spike
Services: email-service
Severity hint: SEV3, SEV2 for password-reset or OTP emails
Owner: Messaging Team

## Symptoms
- Bounce rate rises above 5 percent or the outbound queue keeps growing.
- Users report that OTP or password-reset emails never arrive.
- SMTP logs show `421 Too many connections`, `550 5.7.1 rejected` or `SPF fail`.

## Diagnosis
1. [low] Check the outbound queue: `postqueue -p | tail -1`
2. [low] Read recent SMTP errors: `sudo grep -E "status=(bounced|deferred)" /var/log/mail.log | tail -50`
3. [low] Check SPF, DKIM and DMARC records: `dig TXT <domain>`
4. [low] Check whether the sending IP is on a blocklist.

## Remediation
1. [medium] Throttle outbound sending to the affected provider and flush the queue: `sudo postqueue -f`
2. [medium] Switch transactional email to the backup relay: `flagctl set email.relay backup`
3. [high] Purge the deferred queue only if it is full of spam or duplicates: `sudo postsuper -d ALL deferred`

## Rollback
- Switch back to the primary relay: `flagctl set email.relay primary`

## Escalation
Messaging Team on-call. Security if the domain is being spoofed.
