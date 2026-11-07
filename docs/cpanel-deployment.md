# Verified Sales Preview deployment with cPanel UAPI

## Lifecycle and authority

```text
Internal Website -> explicit content/asset approval -> Sales Preview
  -> explicit publication authorization
  -> approved -> deploying -> uploaded -> verifying -> published
```

`published` means that remote inventory and public DNS, HTTPS and exact approved bytes
passed verification. Upload success, HTTP 200 and cPanel's installed-certificate list
alone never establish publication. The lead's commercial status remains `sales_preview`.
No operation contacts a prospect or changes a customer domain.

`SalesPreviewDeploymentService` owns eligibility, snapshots, destination reservations,
state transitions and recovery. `HostGatorPreviewDeploymentProvider` owns cPanel operations
and remote inspection. `PublicPreviewVerifier` accepts injectable DNS/HTTPS ports;
production adapters use Python's resolver, certificate-verifying SSL context and pinned
HTTPS connections. Domain state/recovery policy contains no cPanel logic.

Publication requires the persisted lead, matching identity, content review acknowledgment,
asset publication rights and exact Phase 1 `approved_artifact` identity. Changed bytes,
missing files, unexpected files, traversal and local symlinks fail before hosting requests.
The provider receives an isolated snapshot; only `index.html`, `styles.css` and explicitly
listed passive image assets are uploaded. Manifests, research, README, databases and
credentials are excluded. Existing inventory limits remain 100 files, 25 MiB total and
8 MiB per image.

## Configuration and destination policy

Required runtime settings remain:

```text
BUSINESS_PROSPECTOR_CPANEL_BASE_URL=https://cpanel-host.example:2083
BUSINESS_PROSPECTOR_CPANEL_USERNAME=account-user
BUSINESS_PROSPECTOR_CPANEL_API_TOKEN=<runtime secret>
BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN=previews.example
BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR=public_html/sales-previews
```

Optional `BUSINESS_PROSPECTOR_PREVIEW_EXPECTED_IPS` is a comma-separated list of permitted
public IPv4/IPv6 addresses. When provided, every resolved address must belong to that set.
The launcher recovers this optional setting alongside the five existing settings through
the same allowlisted runtime mechanism. No dependency or registration change is required.
Do not put secrets into repository config, tool arguments, chat or SQLite.

The configured root must be a domain controlled and authorized for demonstrations, never
a customer production domain. The configured base must be a dedicated relative directory.
Tools accept lead IDs, not arbitrary URLs, credentials or remote paths. Slugs derive only
one child hostname and directory. The known lead website hostname and its use as the
preview root are rejected. Configuration ownership remains an operator responsibility;
the application cannot infer ownership of unrelated domains.

Before mutation, `Variables/get_user_information?name=home` retrieves only the account
home setting. The publisher validates that absolute path, then uses
`Fileman/get_file_information` to check it and each existing path component. It never
uses `get_file_information('.')`, which HostGator rejects, or guesses `/home/<user>`;
other home mounts such as `/home2/<user>` work without configuration changes. Remote
symlinks, non-directories, noncanonical paths and unexpected resolved paths fail closed. Absolute document roots must match the actual account home
exactly; suffix matching is prohibited. Existing domains or destination entries block
first publication. Database uniqueness reserves the URL and destination for one lead.
A digest of the cPanel origin/account binds the reservation to its original runtime
configuration without storing credentials. Token rotation does not change that identity.

## Upload strategy and limitations

The supported UAPI operations provide no safe directory swap. This implementation retains
`deployment_mode=direct_first_publish`: create the absent preview subdomain, upload assets
and CSS with `overwrite=0`, then upload `index.html` last. Parent paths and filename absence
are checked before each upload. UAPI creates missing upload directories.

This reduces partial-page exposure but **is not atomic activation**. Assets may already be
public, and directory indexes/default hosting pages may be visible before the index upload.
Do not share the URL until verification reports `published`. No remote temporary staging
files are created; local snapshots and normal manifest-update temporaries are cleaned up.
Manifest-update temporaries live outside the artifact inventory, so an interrupted write
does not poison the approved file set.

UAPI does not offer an atomic no-follow filesystem operation across precheck and upload.
It cannot prevent a hostile account process from swapping paths between requests. Operate
in an exclusively managed preview directory and quiesce competing hosting writers. Atomic
promotion, automated rollback, partial-file replacement and automatic deletion require a
separately reviewed hosting capability; none is claimed here. Unpublish remains unsupported.

## Verification

Verification first checks the exact remote directory tree against the approved inventory.
Missing files produce `partial_deployment`; extra files, links, destination drift or
unreadable remote state fail closed. It then:

1. Resolves the authorized hostname, rejecting nonpublic/multicast addresses and checking
   optional expected IPs. At most eight addresses are accepted.
2. Connects directly to each resolved address, preserving the authorized hostname for SNI,
   certificate hostname/trust validation and HTTP Host. No second DNS lookup, environment
   proxy, insecure HTTP fallback or redirect following occurs.
3. Requires HTTP 200 and the expected MIME type for `/`, `/index.html`, CSS and every asset.
   Every response must equal the approved bytes. Hosting error pages, stale content,
   unexpected redirects and transformed/minified content fail verification.

The public pass has a 30-second total budget, bounded reads and a socket deadline covering
handshake, headers and body. One pass runs per invocation; there are no propagation sleeps
or background retry loops. The system resolver has a bounded two-worker pool and caller
timeouts; Python cannot cancel a libc DNS call already running. Stalled workers can cause
later calls to return `dns_resolver_busy` until the OS resolver returns. cPanel requests
have their own 20-second default timeout; the public budget starts after hosting inspection.
Public verification checks all addresses/files, so unusually slow or large previews can
need another explicit check. No DNS record changes or AutoSSL requests are made.

## Persistence and recovery

Schema **v8** adds `preview_deployments` and append-only `deployment_events`. Existing lead,
assessment, research and benchmark rows are unchanged. A reservation references the lead
and approved aggregate checksum; it does not duplicate the approval inventory. Each
invocation records an attempt ID, state, sanitized progress and verification outcome.
SQLite transactions protect reservations and state/event updates; POSIX site locks serialize
operations on a draft. A private manifest projection remains for compatibility, but SQLite
is authoritative after a deployment reservation exists.

| State/outcome | Required action |
| --- | --- |
| `approved` | Explicit publication request can begin the first upload. |
| `deploying`, `uploaded`, `verifying` after interruption | Retry or verify inspects remote state; it does not repeat an uncertain upload. |
| `upload_failure` | Correct permissions/quota and reconcile the destination. |
| `partial_deployment` | An operator must restore the exact missing approved files or explicitly clean up the failed destination. Automatic partial-file repair is unsupported. |
| `dns_failure` | Correct DNS/wait for propagation externally, then verify again. |
| `tls_failure` | Provision a trusted matching certificate externally, then verify again. |
| `http_failure` | Correct hosting, MIME types or redirects, then verify again. |
| `content_mismatch` | Investigate cache/transformation/tampering; never silently replace approval. |
| `timeout`, `unknown_remote_state` | Reconcile remote state and repeat verification. |
| `published` | Repeated publish returns the last verified receipt without uploads. Explicit verify performs a fresh check. |

A retry can upload again only after a failed attempt and read-only checks establish that
**both domain and destination entry are absent**, for example after separately authorized
operator cleanup. The exact original approval/destination remains required. Existing partial
files are never overwritten. Completed uploads with lost acknowledgments can be recovered
through verification alone. A failed recheck changes current deployment state while retaining
the historical publication guard. Draft revision/reapproval is blocked once a destination
is reserved, including when the manifest projection failed. There is no tool to discard that
reservation or bypass recovery by changing the approved artifact.

The database, filesystem and hosting server are not one transaction. A crash after a durable
state write is reconciled on retry; failures writing the compatibility manifest cannot erase
the database receipt. Backups must cover both SQLite and artifacts. Independent databases
or uncoordinated remote writers cannot share the same preview namespace safely.

Legacy manifest-only `published` records are displayed as uploaded/unverified until a
current approved artifact passes verification. They are never automatically uploaded again.
They need a valid Phase 1 approval; missing approval requires operator reconciliation, not
fabricated metadata. Existing leads are not automatically deployed or reapproved by migration.

## MCP and dashboard

| Tool | Effect |
| --- | --- |
| `get_sales_preview_readiness` | Existing content/asset review readiness. |
| `approve_sales_preview` | Explicit human content/asset approval; no hosting access. |
| `sales_preview_deployment_readiness(lead_id)` | Local approval, artifact, configured target and reservation checks. No remote availability claim. |
| `publish_sales_preview(lead_id, explicitly_authorized)` | Controlled initial deployment or safe retry. Boolean must be exactly true. |
| `sales_preview_deployment_status(lead_id)` | Persisted state, history and last verification; no hosting request or hosting credentials needed. |
| `verify_sales_preview_deployment(lead_id)` | Reads hosting/public URLs and persists the result; never uploads. Also works after a published lead advances commercially. |

A successful MCP envelope means the operation ran; callers must examine
`data.deployment_status == "published"` before treating the URL as verified. Failure states
include a corrective action. Verification writes local evidence and is not a read-only
local operation. Repository construction can migrate SQLite; local status is not an
operational read-only database audit.

The existing dashboard shows persisted deployment state, verification time and corrective
action. **Publish Preview** retains explicit confirmation. **Verify Public Preview** uses
`POST /api/leads/<id>/verify-deployment` with `{}`; GET deployment status reads local history.
Only currently verified previews receive a public link. Listing cards makes no hosting call.

The administrative `python -m business_prospector.cpanel_smoke` retains dry-run by default
and independent `--execute --confirm <slug>` gates. It reports upload/provider status, not
commercial publication, does not approve a lead or persist a deployment, and must not be
used to bypass the commercial workflow. Its technical-test cleanup remains manual.

## Mac Mini rollout (separate authorization required)

Follow [the update strategy](openclaw-update-strategy.md). Phase 3 development does not
authorize operational changes. Confirm actual source/process ownership and the shared data
path; quiesce application writers, make a consistent WAL-aware SQLite backup and preserve
sites/private manifests. Rehearse v7→v8 and recovery on disposable copies before permitting
repository construction against live data. Validate all existing lead rows/statuses and
artifact hashes. No reset, reseed or automatic approval/deployment is needed.

Restart only affected MCP/dashboard processes through supported scoped management and
verify tool discovery. A new chat alone does not prove Python imports reloaded. Do not
replace agent persona, memory or copied skills. No operational dependency installation is
required solely for Phase 3. Any later rollback must coordinate code, database and artifacts;
rolling back Git alone does not remove v8 deployment reservations safely.

With separate hosting authorization, validate a synthetic throwaway approved preview:
account-home response shape, ancestor/symlink metadata, strict listing, upload directory
creation, DNS (including IPv6), certificate chain, MIME types, exact responses, retry and
cleanup. HostGator behavior and account permissions remain **unvalidated live**.

## Official references

- [cPanel UAPI overview](https://api.docs.cpanel.net/openapi/cpanel/overview/) and [API tokens](https://api.docs.cpanel.net/cpanel/tokens/).
- [Create subdomain](https://api.docs.cpanel.net/specifications/cpanel.openapi/subdomain/subdomain-addsubdomain), [domain configuration](https://api.docs.cpanel.net/specifications/cpanel.openapi/domain-information/domaininfo-domains_data).
- [Account home setting](https://api.docs.cpanel.net/specifications/cpanel.openapi/account-information/variables-get_user_information).
- [Upload files](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-upload_files), [list files](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-list_files), [file information](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-get_file_information).
- [Python SSL contexts](https://docs.python.org/3.11/library/ssl.html#ssl.create_default_context), [HTTP client](https://docs.python.org/3.11/library/http.client.html), [SQLite backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
- [SQLite transactions](https://sqlite.org/lang_transaction.html), [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
