"""Deterministic log-signature extraction.

Regexes are cheaper and more reliable than an LLM for spotting well-known error
strings. The signatures feed both the intake agent and the retrieval query.
"""

from __future__ import annotations

import re

SIGNATURES: list[tuple[str, str]] = [
    ("oom_killed", r"OOMKilled|exit code 137|out of memory"),
    ("crashloop", r"CrashLoopBackOff"),
    ("disk_full", r"No space left on device|could not extend file|disk (?:usage|is )?full"),
    ("db_too_many_clients", r"too many clients|remaining connection slots|cl_waiting"),
    ("idle_in_transaction", r"idle in transaction"),
    ("tls_cert_expired", r"certificate has expired|ERR_CERT_DATE_INVALID|x509: certificate"),
    ("kafka_lag", r"consumer lag|lag (?:is )?(?:rising|growing)"),
    ("kafka_rebalance", r"rebalanc|Offset commit failed"),
    ("jwt_failure", r"invalid signature|kid not found|token used before issued"),
    ("upstream_timeout", r"upstream request timeout|context deadline exceeded|gateway timeout"),
    ("circuit_breaker_open", r"circuit ?breaker (?:is )?open"),
    ("dns_failure", r"EAI_AGAIN|no such host|NXDOMAIN|SERVFAIL"),
    ("ipsec_failure", r"IKE_SA_INIT|NO_PROPOSAL_CHOSEN|AUTHENTICATION_FAILED|ipsec"),
    ("smtp_rejection", r"\b421\b|\b550\b|SPF fail|status=bounced|status=deferred"),
    ("redis_oom", r"OOM command not allowed|evicted_keys"),
    ("http_5xx", r"\b(?:HTTP/\d\.\d\"? )?5\d\d\b(?= |$|,)|\b5xx\b"),
    ("node_not_ready", r"NotReady|DiskPressure|PLEG is not healthy"),
    ("replication_lag", r"replay_lag|replication lag|conflict with recovery"),
    ("readiness_probe_failed", r"[Rr]eadiness probe failed|rollout (?:is )?stuck"),
    ("missing_config", r"missing required config|KeyError|NullPointerException"),
]
_COMPILED = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in SIGNATURES]


def parse_log_signatures(text: str, max_evidence: int = 120) -> list[dict]:
    found = []
    for name, rx in _COMPILED:
        m = rx.search(text or "")
        if m:
            start = max(0, m.start() - 40)
            found.append({"signature": name, "evidence": text[start:start + max_evidence].strip()})
    return found
