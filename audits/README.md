# Audits

Each release is audited before it ships: an independent reviewer checks every promise in [SECURITY.md](../SECURITY.md) against the code, that each check can fail, and what no machine checks (a secret on an error path, a fallback that leaks, the supply chain). Its report for a release is `audits/v<version>.md`, with each finding fixed by a test that went red then green, or answered with a reason. The release workflow refuses a tag with no report.
