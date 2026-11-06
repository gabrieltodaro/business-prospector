# Mac Mini operational audit

Audit date: November 6, 2026. Report prepared at approximately 20:18 UTC.

> Historical audit attempt: the results below describe this development computer's earlier blocked SSH attempt. During the subsequent Git consolidation task, the owner supplied additional November 6 audit findings: the Mac Mini uses `openclaw-port` at `cebec0dc7d182a80c6cde0e4c8e536d2004c34c4`, SQLite schema v6, six leads, one generated website and a running Business Prospector MCP process. These are owner-provided findings, not newly observed by this audit. No Mac Mini access occurred during consolidation. Local Git confirms that the reported commit is an ancestor of the consolidated development history, but does not establish whether the Mac Mini has uncommitted or otherwise unshared changes. The blocked findings below remain an accurate record of the earlier attempt, not a statement that the additional audit never occurred.

The report was reviewed for GitHub inclusion: no credential values, private server addresses, customer records or actual operational database paths are included. The SSH alias has been redacted. Paths below are development defaults or temporary local test evidence, not a verified inventory of the live host.

**Outcome: Phase 2 committed successfully; operational readiness is blocked by SSH authentication.** The SSH endpoint was reachable and its existing host key matched, but no remote command ran. The Mac Mini runtime, cPanel authentication and historical preview are therefore unverified. This is an access blocker, not evidence that OpenClaw or HostGator is broken.

Only this report was added during Part B. No application code, operational configuration, database, website, dependency, service or remote resource was changed. No push, merge, deployment or Phase 3 branch was created.

## A. Phase 2 Commit

| Item | Result |
| --- | --- |
| Branch | `feature/business-prospector-phase-2` |
| Parent / Phase 1 commit | `3181abef0e799f3dadbc779412a9d11116b99371` |
| Phase 2 commit | `54d4b9e307f35c810a3a4d78fe2d442a8825a499` |
| Exact commit message | `feat: add research-driven personalized website generation` |
| Committed scope | 27 intended files, matching the complete inventory in `docs/phase-2-implementation.md`; 2,113 insertions, 228 deletions |
| Full suite immediately before commit | **474 passed, 0 failed, 0 errors, 0 skipped**, 17.03 seconds |
| Python syntax | All 77 Python source/test files compiled in memory successfully |
| JavaScript syntax | `node --check src/business_prospector/dashboard_static/app.js` passed |
| Diff checks | Working-tree, new-file and staged whitespace checks passed |
| Working tree immediately after commit | **Clean**, verified using `git status --porcelain` |
| Working tree after audit | Only this uncommitted report; staging area empty |
| Remote Git changes | Nothing pushed or merged; Phase 1 history preserved |

Reviewed the implementation report, tracked diffs and new implementation files. The inventory includes research strategy/content models, renderer/CSS, asset integration, draft recovery, lifecycle locks, MCP integration, regression tests, synthetic fixture source and documentation. No material discrepancy from the reported implementation was found. File-type/content review and common credential-pattern checks found no operational credentials, private keys, runtime databases, generated website directories or unrelated files in the staged changes. No secret store was opened for this review.

The full suite ran in the same supported isolated environment as Phase 2:

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/uv run --no-project \
  --python /opt/homebrew/bin/python3.14 \
  --with 'pytest>=8,<10' --with 'mcp>=1.2,<2' \
  python -m pytest --tb=short \
  --junitxml=/tmp/business-prospector-phase2-precommit.xml
```

Output: `/tmp/business-prospector-phase2-precommit.txt`. Tests isolate runtime paths, use synthetic/fake providers and block non-loopback test socket connections. They establish local implementation behavior, not production connectivity.

Desktop/mobile validation remains the previously recorded Phase 2 Chrome inspection at 1440×1000 and 390×844; it was not rerun as a production browser test during this audit. The Phase 2 implementation report's “uncommitted” wording records its original handoff state; this section records the subsequent commit.

## B. SSH Connectivity

**Connection unsuccessful: remote authentication rejected.** Exactly one connection attempt was made with the existing `<configured-host-alias>` alias and existing authentication configuration:

```bash
ssh -v \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o ConnectionAttempts=1 \
  -o StrictHostKeyChecking=yes \
  -o UpdateHostKeys=no \
  -o RequestTTY=no \
  <configured-host-alias> 'hostname; whoami; pwd'
```

The command was additionally bounded by a 20-second local subprocess deadline. It returned normally with SSH exit code **255**, not a timeout.

| Check | Result | Evidence |
| --- | --- | --- |
| Existing alias applied | PASS | SSH verbose output reported applying configuration for `<configured-host-alias>` |
| SSH endpoint reached | PASS | SSH progressed through host-key verification to authentication |
| Host identity verification | PASS | Verbose output reported the host was known and matched its existing host key; strict verification remained enabled |
| Non-interactive authentication | FAIL | `Permission denied (publickey,password,keyboard-interactive).` |
| Authenticated remote identity | BLOCKED | No `hostname`, `whoami` or `pwd` output; remote command did not execute |

**Authentication method:** none successfully established. The parenthesized list in the rejection identifies server-advertised methods; it does not establish that password or interactive authentication was attempted. Batch mode prevented interactive prompting. The evidence does not distinguish a missing/unavailable agent identity, rejected key, account policy or another authentication configuration issue.

No retry, alternate account/method, password/MFA request, host-key acceptance, SSH configuration edit, key generation/installation or `authorized_keys` change was performed. The configured address and key details are intentionally omitted.

## C. Runtime Inventory

“Unavailable” below means inaccessible because authentication failed, not missing on the Mac Mini. The development checkout's defaults are reference information only and must not be substituted for observed remote settings.

| Item | Mac Mini state | Local reference / evidence |
| --- | --- | --- |
| OpenClaw version | **Unavailable / BLOCKED** | Launcher comments refer historically to OpenClaw 2026.7.1; this does not prove the current remote version |
| Active workspace and agent runtime | **Unavailable / BLOCKED** | No authenticated remote process/configuration inspection; Oliver Queen/Tony Stark workspace authority cannot be established |
| Business Prospector installation location | **Unavailable / BLOCKED** | Local MCP manifest launches `./bin/business-prospector-mcp` from `${PLUGIN_ROOT}` |
| Active checkout, branch and commit | **Unavailable / BLOCKED** | No remote Git command ran; do not assume it equals the development checkout |
| Installed package version | **Unavailable / BLOCKED** | Development `gapps-business-prospector` package version is **0.1.1** |
| Python interpreter / virtual environment | **Unavailable / BLOCKED** | Launcher precedence: `BUSINESS_PROSPECTOR_PYTHON`, then `~/.openclaw/venvs/business-prospector/bin/python`, then a `python3` that imports `mcp`; package requires Python ≥3.11 |
| Dependencies/importability | **Not tested remotely / BLOCKED** | Development runtime dependency is `mcp>=1.2,<2`; local suite passes, but no remote import was attempted |
| MCP registration | **Unavailable / BLOCKED** | Development `mcp.json` declares stdio server `business-prospector`; declaration is not evidence of active remote registration |
| Launcher availability | **Unavailable remotely / BLOCKED** | `bin/business-prospector-mcp` exists in the committed development checkout only; remote existence/executability unknown |
| Configuration sources | **Unavailable remotely / BLOCKED** | Local manifest supplies `BUSINESS_PROSPECTOR_CONFIG=${PLUGIN_ROOT}/config/default.json`; application falls back to packaged default config |
| Runtime data directory | **Unavailable / BLOCKED** | Local MCP manifest supplies `BUSINESS_PROSPECTOR_DATA_DIR=${PLUGIN_DATA}`; application fallback is `~/.openclaw/data/business-prospector` |
| SQLite location | **Unavailable / BLOCKED** | Development MCP resolves `<data_dir>/business-prospector.db`; no actual remote path established |
| SQLite schema and lead access | **Not tested / BLOCKED** | Development schema is v7; no remote connection, migration, row query or database initialization occurred |
| Generated artifacts | **Unavailable / BLOCKED** | Development location is `<data_dir>/sites`; presence of remote artifacts unknown |
| Reviewed asset/revision directories | **Unavailable / BLOCKED** | Phase 2 uses `<data_dir>/reviewed-assets` and `<data_dir>/site-revisions` |
| Dashboard status/configuration | **Unavailable / BLOCKED** | Development defaults to `127.0.0.1:8765`; CLI `--database` can override the shared default database |
| Dashboard/MCP database agreement | **Not tested / BLOCKED** | Development code shares path resolution; actual process environment/arguments may differ |
| launchd / scheduled jobs | **Unavailable / BLOCKED** | No remote job/process inventory or scheduler command ran |

### Safe inspection boundaries found locally

- `SQLiteLeadRepository.__init__` creates the parent directory and calls initialization, which enables WAL, executes schema statements/migrations and writes `PRAGMA user_version`. Starting the dashboard or calling repository-backed MCP operations is therefore **not a safe substitute for a read-only database audit**. None was run against operational data.
- A follow-up must use a genuinely read-only SQLite inspection path, accounting for any live WAL/shared-memory state and stopping rather than creating missing database/sidecar files. Inspect schema and aggregate counts without exposing lead records unnecessarily. Do not assume an immutable connection gives a current snapshot of a database being written concurrently.
- The launcher can source the OpenClaw service environment before any `--check` action. It was inspected as source, not executed operationally. A future audit must inspect the actual remote launcher/configuration before choosing its diagnostic path; a “check” label alone does not guarantee absence of initialization or shell side effects.
- Package version **0.1.1** was unchanged by Phase 1/2, so version equality would not prove feature parity. Compare the active commit or specific installed files, generator 3.0.0, strategy 3.0 and revision/integrity interfaces.

Sources inspected: `mcp.json`, `pyproject.toml`, `bin/business-prospector-mcp`, `application/runtime.py`, `mcp/server.py`, `dashboard.py`, `infrastructure/sqlite_repository.py` under `src/business_prospector` where applicable.

## D. HostGator Connectivity

All configuration values and their presence on the Mac Mini remain **unknown**. No cPanel request was made and no HTTP status code was observed.

| Check | Result | Evidence |
| --- | --- | --- |
| cPanel configuration | **BLOCKED** | Could not inspect the authorized remote runtime environment |
| Authentication | **BLOCKED** | No runtime-backed cPanel authentication diagnostic could execute |
| Domain listing | **BLOCKED** | No `DomainInfo/list_domains` or `domains_data` response obtained |
| Subdomain listing | **BLOCKED** | No remote domain inventory obtained |
| Document-root access | **BLOCKED** | No domain/root comparison or file metadata listing performed |
| SSL inspection | **BLOCKED** | No installed-certificate response or public TLS handshake performed |
| Existing preview discovery | **BLOCKED** | Remote manifests, receipts, domains and roots inaccessible |
| Public HTTPS response | **BLOCKED** | No historical preview URL established from reliable deployment evidence |
| Static asset accessibility | **BLOCKED** | No identified public preview or referenced asset inventory to check |

Configuration presence, separately for every required variable:

| Variable | Presence | Value disclosed |
| --- | --- | --- |
| `BUSINESS_PROSPECTOR_CPANEL_BASE_URL` | Unknown / BLOCKED | No |
| `BUSINESS_PROSPECTOR_CPANEL_USERNAME` | Unknown / BLOCKED | No |
| `BUSINESS_PROSPECTOR_CPANEL_API_TOKEN` | Unknown / BLOCKED | No |
| `BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN` | Unknown / BLOCKED | No |
| `BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR` | Unknown / BLOCKED | No |

No credential was read, printed, copied to the development computer or stored. No unrelated secret store was inspected. Repository `AGENTS.md` additionally requires loading `aws-secrets-manager` before credential work; neither that skill nor a `retrieve_skill` tool was available in the inspected session/installed skill locations. Credential-dependent work must satisfy that repository instruction in a follow-up. SSH authentication is the immediate blocker for the entire remote audit.

### Diagnostic implementation review, not execution

The committed development code provides suitable narrow read-only call paths:

- `CPanelConnectivityService.test()` calls `CPanelUapiClient.list_domains_diagnostic()`, issuing `GET /execute/DomainInfo/list_domains` without a repository or publication call.
- `HostGatorPreviewDeploymentProvider.status()` calls domain configuration, file-listing and installed-SSL methods. In the reviewed implementation it does not call subdomain creation, upload, deletion, publication or database initialization.
- `cpanel_smoke --status --preview-slug <evidence-backed-slug>` delegates to that status path. Its `--execute` branch invokes publication and is prohibited for this audit.
- `cpanel_configuration_status()` checks local configuration only; a “configured” result would not prove connectivity.

These are **static findings about the development commit**, not validation of the unknown installed remote code. No diagnostic command was executed on the Mac Mini or against cPanel. Actual remote code must be inspected before execution.

Two distinctions matter for Phase 3: provider status infers file presence from metadata, not public content hashes; its SSL status checks domain coverage in installed-host data, not a verified public TLS connection and certificate validity period. Neither substitutes for public verification.

## E. Existing Preview Status

**The previously published test preview could not be confirmed or disproved. No verified historical preview URL was identified.**

- Mac Mini deployment manifests, local test artifacts, stored receipts and historical slugs: **BLOCKED** by SSH authentication.
- cPanel subdomains and remote document roots: **BLOCKED**; no API call attempted.
- A filename-only scan of the development repository, including ignored files but excluding `.git`, found no `site-manifest.json`, matching deployment/receipt JSON files or `.db`/`.sqlite`/`.sqlite3` runtime databases. This limited local result says nothing about Mac Mini storage.
- Documentation contains example slugs/URLs and example deployment metadata. These are not publication receipts and were not treated as real historical destinations or probed.
- The Phase 2 dental/restaurant demonstrations are explicitly local and unpublished. They do not establish that the earlier HostGator test remains live.
- The current technical smoke implementation returns its result but does not itself persist a commercial deployment receipt in the site manifest. A missing local commercial receipt alone would therefore not disprove an earlier technical publication.

DNS resolution, HTTPS/TLS validity, HTTP status, expected HTML, CSS/assets and public-to-local checksum comparison were **not tested** because a trustworthy target URL/artifact was unavailable. No website was modified or republished.

## F. Compatibility Assessment

| Area | Verified development baseline | Remote comparison / required action |
| --- | --- | --- |
| Package version | 0.1.1 | Remote unknown; version alone is insufficient |
| Phase 1 | Present in parent `3181abef…` | Establish whether active remote code includes immutable approvals, restricted public inventory and schema v7 before any upgrade/publication |
| Phase 2 | Present in `54d4b9e…`; generator 3.0.0, strategy 3.0 | Verify active checkout/installed modules and packaged `preview.css`; do not infer parity from another checkout |
| Python/dependencies | Python ≥3.11, MCP ≥1.2 and <2; no new Phase 2 runtime dependency | Remote interpreter, dependency versions and POSIX locking support must be verified |
| SQLite | Schema v7, unchanged by Phase 2 | Remote version unknown. If already v7, Phase 2 needs no new schema migration. Older schemas require a separately authorized, backed-up migration plan; do not trigger initialization merely to inspect them |
| Runtime paths | Shared application defaults; dashboard `--database` can override | Confirm MCP plugin-data path and dashboard process arguments/environment resolve to the same existing DB/sites |
| Configuration | Existing five cPanel variables; optional reviewed local asset library | Presence and validity unknown; no specific missing variable or required configuration change has been established |
| Existing approvals | Exact version-1 public inventory/hash receipt required | Inspect historical receipts. Unpublished legacy approvals without integrity identities need review/reapproval; successful revisions invalidate prior approvals |
| Published previews | Replacement/reapproval of published artifacts is protected | Do not revise or silently upgrade existing published artifacts. Identify and inspect them first |
| Deployment manifests | Phase 1 integrity format remains version 1; Phase 2 adds private strategy/content/revision fields | No blanket Phase 2 manifest migration. Determine whether any remote legacy inventory/receipt is incomplete before proposing case-specific regeneration/reapproval |
| Disclosure/indexing | New generation includes independent-demo disclosure and noindex | Existing remote pages do not acquire these automatically; verify historical public bytes separately |

**Precise assessment:** the development code passes its complete local suite and is committed. Production compatibility cannot be certified because the authoritative runtime and database were not accessible. No runtime upgrade, configuration edit, migration or reapproval was executed, and none should be prescribed as definitely required until remote inventory is obtained.

## G. Phase 3 Readiness

**Classification: Blocked.**

The blocker is non-interactive SSH authentication, preventing the required authoritative-runtime, database and hosting checks. Host reachability and host-key verification passed; runtime registration, dependency validity, Phase 1/2 parity, cPanel access and the earlier public preview did not receive operational verification.

Local engineering preparation is complete enough to review Phase 3 scope, but this audit does not justify claiming the real environment is ready or implementing deployment changes against assumed production state. Once access and the credential-handling prerequisite are resolved, complete the read-only audit before choosing the smallest necessary Phase 3 changes.

## H. Recommended Next Actions

1. **Restore audit access and finish the inventory.** An authorized operator should resolve the existing SSH authentication issue without sending passwords/private keys through chat. Make the required credential-handling skill available or explicitly resolve the repository instruction for the existing non-AWS runtime. Codex can then repeat one bounded non-interactive connection and inspect the active OpenClaw installation, MCP registration, interpreter, launch jobs, runtime paths and schema without starting/migrating the application. This audit made no authentication changes.
2. **Establish hosting evidence before implementation.** Once the actual remote diagnostic implementations are reviewed, Codex can check only configuration presence and execute allowlisted read-only cPanel diagnostics. Discover the earlier preview from receipts/domain roots, then verify public DNS, TLS, HTTP, CSS/assets and hashes where an exact local artifact exists. Do not invent a slug or use a documentation example as a test destination.
3. **Implement the bounded Phase 3 gaps locally under a new task authorization.** Use this inventory to define controlled deployment preflight and public verification requirements: exact approval receipt, destination isolation, explicit authorization, verified TLS/HTTP/assets/content identity, and honest partial-failure reporting. Reuse the existing adapter and test with fake providers first. No Phase 3 code or branch was created here.
4. **Prepare the runtime only if needed.** Codex can prepare a concrete upgrade/configuration/migration plan and local validation. Applying it to the Mac Mini, installing dependencies, changing configuration or restarting services requires separate authorization; any migration needs an approved backup/recovery plan. Matching code and runtime paths must be established before publication.
5. **Publish one synthetic preview with explicit authorization.** Review a synthetic artifact and its destination, obtain exact content/asset approval as appropriate to the chosen lifecycle, then separately authorize one bounded publication. Codex can execute that authorized operation and preserve sanitized receipts. Neither commercial approval nor permission to audit grants permission to upload/create a subdomain. DNS/certificate changes and cleanup need their own applicable authorization; do not silently broaden publication into infrastructure repair.
6. **Verify the resulting public website.** Codex can automate read-only DNS/TLS/HTTP and allowlisted static-asset checks, compare downloaded public bytes against the approved inventory, and inspect desktop/mobile rendering. Record mismatches and partial deployments accurately; a 200 response or cPanel file listing alone is insufficient. Do not republish or delete to fix discrepancies without authorization.
7. **Prepare the first real commercial preview.** Human review must establish target facts, current evidence, asset rights, independent-demo disclosure and design/content quality. Codex can generate and validate locally within a later authorized task. Require fresh artifact-specific approval and separate publication authorization. Lead contact/outreach remains a separate decision and is not authorized by this audit.

## Evidence and boundaries

- Fresh full-suite evidence: `/tmp/business-prospector-phase2-precommit.txt` and `/tmp/business-prospector-phase2-precommit.xml` on the development computer.
- Commit and clean-tree verification: local Git output for `54d4b9e307f35c810a3a4d78fe2d442a8825a499`.
- SSH evidence: one captured invocation, known-host match, exit 255, sanitized authentication rejection, empty remote identity output. Raw verbose authentication details were not persisted in the repository.
- Static inspection: committed source/docs listed above plus `application/technical_deployment.py`, `infrastructure/cpanel.py` and `cpanel_smoke.py`.
- No cPanel HTTP status codes, remote SQL results, deployed hashes or public verification results exist for this attempt. They are deliberately not inferred from mocked tests or documentation.
- No operational resources were changed and no credentials were disclosed. This report was originally left uncommitted for review; it is now included in the separately authorized Git consolidation.

## Consolidation and controlled-update addendum

During the separately authorized local Git consolidation, the existing migration branch was identified as `openclaw-port`. Its local and GitHub tips were both `696c7b536437ca1120dcb78c22f1bbfe96f61787`. It was fast-forwarded to Phase 2 commit `54d4b9e307f35c810a3a4d78fe2d442a8825a499`, preserving Phase 1 commit `3181abef0e799f3dadbc779412a9d11116b99371` and all prior migration commits. No conflict resolution, cherry-pick, squash or history rewrite was necessary. The report is the only additional consolidation change.

Fresh consolidated-branch verification:

- Complete suite: **474 passed, zero failed/errors/skipped**, 16.88 seconds, using isolated temporary runtime data and fake providers.
- All **83 tracked Python files** passed in-memory syntax compilation; the dashboard JavaScript passed `node --check`.
- Source distribution and wheel built from a temporary Git archive. All **49 packaged modules** imported successfully outside the checkout with networking disabled during the import probe. CSS, synthetic fixtures, packaged configuration and dashboard assets were present.
- Existing launcher/Agent Plugins/compatibility-manifest and stdio MCP integration tests passed in the full suite; no operational OpenClaw process was invoked.
- No production dependency change was introduced by Phase 1/2; the packaging change includes `resources/*.css`.
- Diff checks, changed-file review and common credential-pattern checks passed. No runtime database, generated website, credential material or private customer record was included in the consolidation changes.
- A separate temporary-database probe used the v6 schema extracted from reported Mac Mini commit `cebec0dc7d182a80c6cde0e4c8e536d2004c34c4`. Initialization with consolidated code produced schema v7 and the `benchmark_selections` table while preserving all six synthetic lead rows exactly, including IDs and statuses. A pre-existing synthetic site file remained unchanged. This is a local migration check, not validation or migration of the operational six leads.
- One pre-existing metadata inconsistency remains: distribution/plugin version is `0.1.1`, while `business_prospector.__version__` is `0.1.0`. It predates this consolidation and does not prevent builds/imports/tests. Verify future runtime parity by commit/content identity, not only the version string.

The consolidated code is ready to serve as the source for a **separately planned, controlled Mac Mini update**, subject to these prerequisites:

1. Inventory and preserve any uncommitted, untracked or unshared Mac Mini migration work before integrating; local ancestry of the reported commit does not prove the remote working tree is clean.
2. Obtain a consistent backup of the existing SQLite database, including its active WAL state as applicable, plus the existing website directory and private manifests. Verify restore procedures before allowing application initialization to migrate v6 to v7. Check all six operational lead identities/statuses after the authorized migration.
3. Preserve the existing website byte-for-byte during the runtime update. Do not regenerate, replace, publish or delete it merely because the generator changed. Inspect legacy inventories/approval receipts and require explicit reapproval of unpublished previews where Phase 1 integrity metadata is absent; published artifacts remain protected from replacement.
4. Verify the actual Python interpreter/dependencies, packaged resources, executable launcher and both MCP registration compatibility paths. Confirm the configured plugin-data directory and dashboard database override refer to the intended existing database and sites; the shared Phase 1 path resolver must not silently select a different data store.
5. Separately authorize any checkout/dependency/configuration update, migration and service restart. Recheck runtime imports and MCP tools after the controlled update before planning a publication operation.

No Mac Mini connection, command, update, database migration, service restart or website publication was performed during consolidation. No Phase 3 implementation was started.
