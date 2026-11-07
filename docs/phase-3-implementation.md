# Phase 3: verified preview deployment

Implemented on the existing `openclaw-port` branch from baseline `79d49f1`. Development,
tests and packaging used local disposable data. No Mac Mini access, operational migration,
real hosting request/publication, DNS change, credential retrieval or outreach was performed.

## Changes

- Extended the existing application service and HostGator/cPanel adapter. Approval identity,
  exact file inventory, provenance, asset rights, immutable snapshots and commercial status
  boundaries remain mandatory.
- Added provider-independent state/recovery rules and injectable public DNS/HTTPS verification.
  A completed upload is `uploaded`; only an exact remote inventory and successful DNS, TLS,
  HTTP/MIME and approved-byte checks yield `published`. All resolved public addresses and
  the landing page, explicit index, stylesheet and assets are checked.
- Added account/destination binding, unique destination reservations, strict remote ancestor
  checks, no redirect forwarding, non-overwriting uploads and index-last ordering. Unknown
  remote outcomes are persisted and reconciled conservatively.
- Added SQLite **v8** tables `preview_deployments` and `deployment_events`, without changing
  existing lead/research rows. Migration uses a savepoint; failure rolls back and can be
  retried. A newer schema is rejected. State/event writes are transactional; site locks
  serialize draft operations. Credentials and approval inventories are not copied into DB.
- Added MCP tools `sales_preview_deployment_readiness` and
  `verify_sales_preview_deployment`; existing publish supports safe retries, and existing
  status returns persisted history without needing hosting credentials. Dashboard changes
  show verification state/time/action and expose a verification button/public verified link.
- Protected reserved artifacts from revision/reapproval, including after interruptions or
  failed manifest writes. Private manifest projections remain compatible with existing views.
  Legacy publication metadata is unverified until a fresh approved-artifact check passes.

## Validation

Final full suite: **534 passed, 0 failed, 0 errors, 0 skipped** (474 baseline cases plus
60 additional cases). Existing assertions were updated where upload/status semantics
deliberately changed. New tests
exercise a full simulated approval → cPanel → DNS/HTTPS → verified publication lifecycle,
missing/stale approval, content/inventory drift, foreign domains and directories, symlinks,
partial uploads, lost acknowledgments, interrupted uploads/verification, idempotence,
operator-assisted recovery, MCP dispatch/authorization, dashboard routes, schema rollback,
and preservation of six synthetic v7 lead rows and their research.

Public verification tests cover DNS failure/expected-address mismatch, private/multicast
addresses, TLS failure, timeouts, HTTP errors, redirects, MIME mismatch and stale/error pages.
A loopback TLS test generates a disposable certificate/key with the local `openssl` CLI;
it proves trusted-host success and rejection of an untrusted certificate or wrong hostname.
No private key is retained in source control. Tests reject external sockets and DNS.

Wheel build and installation passed in a temporary source copy and separate temporary
Python environment. Installed imports, packaged resources, schema v8 and all **27 registered
MCP tools** passed verification. The full suite also exercises both bundle manifests and the launcher
through stdio with synthetic storage/environment. Python 3.11 grammar, JavaScript/shell syntax
and `git diff --check` passed separately (82 Python files checked). Runtime testing used Python 3.14.8; no claim of
a separate Python 3.11 runtime test is made.

## Recovery and remaining limitations

Completed remote uploads can recover by verification alone. Partial deployments require
operator reconciliation; a new upload is allowed only when both the reserved domain and
its directory are absent. No automatic deletion, partial-file overwrite or atomic swap is
implemented. Index-last ordering reduces partial-page exposure but is not an atomic deploy.

UAPI cannot close the race between remote path inspection and upload against a hostile
concurrent account writer. Use an exclusively managed preview directory. Exact inventory
checks also reject provider-created extra files/directories until reconciled. Public byte
comparison intentionally rejects hosting/CDN transformations. A verification receipt is a
point-in-time observation; no monitoring or automatic DNS/certificate provisioning is added.
The bounded DNS worker pool cannot cancel an already running libc resolution call.

Live HostGator response shapes, permissions, DNS, AutoSSL timing, MIME behavior and recovery
remain unvalidated. The [deployment runbook](cpanel-deployment.md) documents configuration,
states, retry actions, official references and the separately authorized Mac Mini rollout.
The six live leads were not inspected or migrated; compatibility evidence uses synthetic data.
