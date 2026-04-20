"""
InjectionGuard — lightweight text scanner for prompt injection and shell command
injection patterns in LLM agent pipelines.

Zero external dependencies (stdlib only).

Usage::

    from tripartite_memory.guards import InjectionGuard

    result = InjectionGuard.scan_text_for_injection(user_input)
    if result["score"] >= 50:
        raise ValueError(f"High-risk input rejected: {result['summary']}")

Score interpretation:
    0        — clean
    1–49     — medium-risk findings only (review recommended)
    50–100   — high-risk pattern detected (block recommended)
"""

import re
from typing import Dict, Any, List


class InjectionGuard:
    """
    Scans arbitrary text for patterns associated with prompt injection,
    shell command injection, and LLM instruction-override attacks.

    All patterns are stateless regex — safe to call from async contexts
    and across threads without locking.
    """

    HIGH_RISK_PATTERNS = [
        (r'(?i)subprocess.*shell\s*=\s*True',
         "Use of shell=True in subprocess"),
        (r'os\.system\s*\(',
         "os.system() call detected"),
        (r'eval\s*\([^)]{0,80}\)',
         "eval() usage detected"),
        (r'(?i)exec\s*\([^)]{0,80}\)',
         "exec() usage detected"),
        (r'(?i)--allow-root|--privileged|cap_add.*SYS_ADMIN',
         "Container privilege escalation attempt"),
        (r'(?i)(ignore previous instructions|disregard previous|act as|forget everything)',
         "Attempt to subvert LLM instructions"),
        (r'(?i)(output only json|return json only|format as json)',
         "Attempt to force specific output format"),
        (r'(?i)<script>|javascript:',
         "HTML/JavaScript injection attempt"),
        (r'(?i)rm -rf|sudo |passwd|chown|chmod|wget|curl |\bnc\s|python -c',
         "Malicious shell command patterns"),
        # Template injection: only flag when shell operators are embedded (not plain ${VAR})
        (r'\$\{[^}]*[;|&`$][^}]*\}|\%\{[^}]*[;|&`$][^}]*\}',
         "Template injection with embedded shell operators"),
        # Backtick exec: only flag when followed by a known shell command (not markdown inline code)
        (r'`[^`]*\s+(rm|sudo|wget|curl|chmod|chown|passwd|nc|python|bash|sh)\b',
         "Backtick shell command execution"),
    ]

    MEDIUM_RISK_PATTERNS = [
        (r'(?i)TODO.*(?:security|injection|xss|csrf)',
         "Security-related TODO comment"),
        (r'(?i)DEBUG\s*=\s*True',
         "DEBUG mode enabled (potential information leak)"),
        (r'&&|\|\|',
         "Logical operator chaining (review in shell/command context)"),
    ]

    @staticmethod
    def scan_text_for_injection(text: str) -> Dict[str, Any]:
        """
        Scan *text* for injection patterns and return a risk report.

        Returns a dict with:
            score     — int 0–100. 0 = clean, ≥50 = high-risk finding present.
            findings  — list of {severity, description, pattern} dicts.
            summary   — human-readable one-liner.
        """
        findings: List[Dict[str, str]] = []
        injection_score = 0

        for pattern, desc in InjectionGuard.HIGH_RISK_PATTERNS:
            if re.search(pattern, text):
                findings.append({"severity": "HIGH", "description": desc, "pattern": pattern})
                injection_score += 50

        for pattern, desc in InjectionGuard.MEDIUM_RISK_PATTERNS:
            if re.search(pattern, text):
                findings.append({"severity": "MEDIUM", "description": desc, "pattern": pattern})
                injection_score += 10

        injection_score = min(injection_score, 100)

        return {
            "score": injection_score,
            "findings": findings,
            "summary": f"Injection scan score: {injection_score}. {len(findings)} finding(s).",
        }

    @staticmethod
    def is_safe(text: str, threshold: int = 50) -> bool:
        """Return True if the text scores below *threshold* (default 50)."""
        return InjectionGuard.scan_text_for_injection(text)["score"] < threshold
