# Security policy

Report vulnerabilities privately through GitHub Security Advisories for
`fileworks/maintenance`. Do not include personal mailbox content.

Security fixes target `main`; this package is internal tooling and is not
released to a package index.

This tool reads and, when explicitly asked, writes GitHub repository settings.
It never stores or prints a credential: authentication is delegated to the `gh`
CLI, which holds whatever least privilege was granted to it, and every value
that reaches a log or report passes through `redact()` first. Settings are only
written by `maintenance.reconcile`, which plans before it acts, refuses a change
whose prerequisites are not observed green, and reads every write back rather
than trusting that it took.

Run it with a `gh` session scoped to `repo` and `admin:org` and nothing more.
`delete_repo` is deliberately outside the required scopes.
