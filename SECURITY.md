# Security and private data

Do not publish passwords, OAuth tokens, application secrets, signed licenses,
game/request tickets, account identifiers, browser profiles, or raw captures.
DPAPI-protected files are still private and must not be committed.

`private/`, `analysis/`, `artifacts/`, local installations, build outputs, and
common capture/binary formats are excluded by `.gitignore`. Review staged files
before every commit; ignore rules do not remove files that were already tracked.
They also do not protect manual uploads: do not publish an unfiltered ZIP of the
working folder, which still contains local-only data.

This prototype is version-pinned and not security-hardened. Only run it with
accounts, software, and machines you are authorized to use. Do not change Windows
security settings or anti-cheat protections to work around launcher problems.

## Reporting

Use GitHub private vulnerability reporting if the repository has it enabled.
Otherwise request a private contact channel without publishing sensitive details.
Do not attach raw logs, account state, or proprietary binaries to a public issue.

If credentials are exposed, revoke/rotate them where possible. Removing the file
in a later commit does not remove it from Git history.
