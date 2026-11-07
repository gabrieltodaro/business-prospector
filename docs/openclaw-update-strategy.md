# Agent instructions audit and OpenClaw update strategy

Date: November 6, 2026 (America/New_York). Investigation baseline: `openclaw-port`, commit `241703636421c475b292c42dbf354e9d790af627`.

This is a repository investigation and a proposed update procedure, not an executed runtime update. Only `AGENTS.md` and this document were changed. The initial investigation left them uncommitted for review; the subsequently authorized documentation finalization versions these two files on `openclaw-port`. Neither task changes application code, implements an update script, accesses the Mac Mini, migrates data or deploys anything.

## A. AGENTS.md findings

### Locations and Git history

There is exactly one `AGENTS.md` in the current repository working tree, including ignored/hidden directories outside `.git`: the tracked root file. No nested instructions were found.

It was introduced in `cebec0dc7d182a80c6cde0e4c8e536d2004c34c4`, **August 25, 2026, 21:31:24 -04:00**, authored/committed as Gabriel Todaro, with subject `Fix cPanel file listing compatibility`. That commit added all 26 lines alongside changes to the cPanel adapter, its tests and its documentation. Neither its message nor the diff explains why AWS guidance was included.

| Ref inspected | Original AGENTS.md state |
| --- | --- |
| `main` | Absent |
| Parent of `cebec0dc` | Absent |
| `cebec0dc`, `696c7b5` | Present; blob `fbe1d674a9cb8635ab887d858e5d22c520f7a323` |
| `fix/business-prospector-phase-1` / `3181abef` | Same blob |
| `feature/business-prospector-phase-2` / `54d4b9e` | Same blob |
| `openclaw-port` / `2417036` and local `origin/openclaw-port` reference | Same blob before this edit |

All reachable history shows one addition and no subsequent edit/deletion. The user's earlier deletion may have been uncommitted or in another checkout; this repository cannot establish that event. A committed tracked file is carried by later branches/updates. Git author metadata identifies who recorded the commit, not which editor, template or assistant authored its text.

**Origin conclusion:** the text resembles generic AWS guidance, but there is no generator marker, template reference or commit rationale proving an external tool produced it. Its introduction is established; its original motivation and authoring tool are not. Do not attribute it to a specific tool without further evidence.

### Actual AWS dependencies

Searches covered tracked active source, configuration, manifests, scripts, tests and the preserved legacy directory. `pyproject.toml` declares `mcp>=1.2,<2` as the production dependency and pytest as the test extra. No AWS SDK, boto3/botocore, AWS credentials/configuration, Secrets Manager client, `asm-exec` integration, AWS provider, CDK/CloudFormation/Terraform infrastructure or AWS service endpoint was found.

AWS-specific operational instructions were confined to the old root `AGENTS.md`; the earlier operational-audit report discusses that requirement historically. Two active validators reject the `x-amz-signature` query parameter (`domain/site_assets.py` and `domain/site_content.py`). These are protective URL rules, not AWS integration, and were preserved. Broad text searches also matched the Roboto font name in legacy assets; that is not boto/AWS code.

The verified infrastructure is Google Places REST discovery, Playwright MCP browser evidence, Python/SQLite, and HostGator/cPanel UAPI publication behind explicit lifecycle authorization. `prospector-de-sites/` is identified by README as legacy; its older Antigravity/Gemini, password/FTP-style configuration and outreach examples are not the current operational contract.

**Decision:** the blanket AWS skill/runtime requirement is unjustified for this codebase. Its credential-protection intent is valid and must remain. Replace the provider-specific mechanism with runtime-local secret handling and explicit operational boundaries. This does not assert that no other application in the user's environment uses AWS.

The earlier local audit was independently blocked at SSH authentication. Removing the inappropriate instruction does not fix SSH credentials or retroactively verify cPanel connectivity.

## B. AGENTS.md changes

The replacement provides concise engineering guidance rather than reproducing the full technical reports:

- Documents the existing domain → application → infrastructure → MCP/dashboard separation, typed Python conventions, deterministic rules, SOLID and composition.
- Identifies the legacy directory and prevents its installers/password/outreach workflows from being mistaken for the active bundle.
- Documents the authorized Git workflow, isolated test commands, regression/syntax/package checks and honest reporting of documentation-only validation.
- Explains repository initialization side effects, WAL-aware backups, explicit migration authorization, data-path consistency and preservation of lead identities/statuses.
- Retains exact artifact approval, asset rights, integrity hashes, safe-path and published-artifact protections.
- Separates code refresh, dependencies, plugin registration, skill discovery and process restart; points to this strategy for details.
- Removes the unconditional AWS MCP/CLI, Secrets Manager skill, `asm-exec`, AWS naming and AWS infrastructure instructions.
- Preserves and makes explicit the security requirements: credentials stay in the authorized runtime; no secret values in context/logs/Git/arguments, no unrelated store inspection, no operational credential copying, sanitized diagnostics only, TLS/SSH verification, customer privacy and least privilege. Authorized diagnostics may use credentials internally after their actual side effects are reviewed.
- Keeps production access, dependency installation, migrations, restarts, publication, DNS/certificates and lead contact outside ordinary development/push authorization.

At the initial investigation handoff, these edits were **uncommitted and unpushed**. Baseline commit `2417036` contains the old AWS instructions; select the reviewed documentation commit or a verified descendant when planning a controlled update. Publishing documentation to GitHub does not update another checkout automatically. Historical audit reports were left intact.

## C. OpenClaw integration map

### Verified repository behavior

| Layer / file | Verified role | Update consequence |
| --- | --- | --- |
| `plugin.json` | Root Agent Plugins bundle identity, version 0.1.1; description names Oliver Queen | Registration points to a bundle root; this is not an agent/workspace declaration |
| `mcp.json` | Agent Plugins stdio entries for Business Prospector and Playwright; config/data placeholders use `PLUGIN_ROOT`/`PLUGIN_DATA` | Preserve persistent plugin data and valid placeholder expansion |
| `.mcp.json` | Claude-layout compatibility registration using `CLAUDE_PLUGIN_ROOT`; used by the documented older OpenClaw path | Same launcher, different data-path default; do not switch formats and accidentally select a new database |
| `bin/business-prospector-mcp` | Uses explicit interpreter override, dedicated venv, or compatible Python fallback; recovers allowlisted service settings; launches bundle entry point | The launcher belongs to the checkout, but existing processes do not rerun it automatically |
| `run_mcp.py` | Prepends the current bundle's `src/` to `sys.path`, then starts `business_prospector.mcp.server` | Newly spawned MCP uses bundle source rather than the installed package copy |
| Launcher `--dashboard` | Sets checkout `PYTHONPATH`, then runs the dashboard module | Dashboard started by this route also uses checkout source; a direct venv module invocation can instead use installed package files |
| `scripts/setup_openclaw_runtime.py` | Creates/reuses a persistent venv, invokes pip on the checkout, checks imports | Installs a package copy/dependencies; no plugin registration, skill copying, restart, backup or migration rehearsal |
| Root `skills/prospector-setup/SKILL.md` | Configuration guidance | Versioned bundle skill, not proof of a copied workspace installation |
| Root `skills/prospeccao-maps/SKILL.md` | Oliver's discovery/research/qualification instructions | Same distinction; duplicate skill names elsewhere can mask this version |
| `application/runtime.py` | Resolves config/data paths; MCP and dashboard share defaults | Verify actual environment and dashboard `--database` override before updating |
| `resources/`, `dashboard_static/` | Local resource files loaded through package resource helpers | Used from the package actually imported; source/installed-copy mismatch matters |
| Root `AGENTS.md` | Repository engineering instructions | No repository code installs it into Oliver/Tony workspaces |
| `prospector-de-sites/` | Preserved original implementation and skills | Exclude from active synchronization; do not recursively copy every skill in the repository |

Repository-intended path:

```text
Oliver's allowed skills/tools            Tony's allowed skills/tools (unknown)
                  \                       /
          OpenClaw plugin registration / skill discovery
                   |                     |
           bundle skill files      stdio MCP registration
                                         |
                             bin/business-prospector-mcp
                                         |
                      dedicated Python + checkout/run_mcp.py
                                         |
                         checkout/src/business_prospector
                                         |
                        configured SQLite and site storage
```

This diagram does not claim both agents currently have access or share a process/database. There is no Tony-specific integration, agent roster, workspace mapping, persona file, process supervisor or synchronization manifest in this repository.

### Source updates and process lifetime

For the configured launcher, newly started MCP processes load Python from the bundle checkout. Existing Python module objects remain in memory: a Git update is not a code reload. Resource/config readers may read changed files before a process restarts, so updating a live checkout while work continues risks mixed revisions. Stop or drain the affected work first. A running dashboard with changed Python modules needs its own scoped restart; unchanged Playwright does not need restarting just because Business Prospector changed.

A new agent session can refresh instructions/tool discovery, but is not evidence that every existing MCP subprocess was replaced. Verify actual owning process, start time, import path and tool schema. Do not assume either one shared MCP or one MCP per agent/session.

### What is known about the Mac Mini

The user reports checkout `/Users/minigabz/Developer/Gapps/business-prospector`, branch `openclaw-port`, commit `cebec0dc…`, a dedicated venv, plugin registration, a running MCP, SQLite v6 with six leads and one generated website. These are owner-supplied audit findings, not newly inspected in this task.

Unverified: whether registration uses a link or copied bundle; the actual loaded root/interpreter/data directory; OpenClaw version; skill shadowing or workspace copies; process/session ownership; and whether Oliver and Tony use shared or separate workspaces and tool permissions. No installed/copy destination for either skill can be established locally. The setup script contains no skill synchronization step, and the README recommends linking the bundle with `plugins install -l` rather than copying skills.

### Current documentation versus installed-version assumptions

The following sources were checked on November 6, 2026. They describe current OpenClaw, not proof of behavior on the older Mac Mini installation:

- Bundle skill roots map into OpenClaw skills, and Agent Plugins/Claude bundles have distinct manifest and placeholder conventions. [Plugin bundles](https://docs.openclaw.ai/plugins/bundles)
- Current plugin management supports scoped `openclaw plugins reload <plugin-id>` after source/manifest edits. Apply/reload receipts and actual runtime inspection distinguish a completed reload from a saved change; some cases still require restarting the gateway. Treat this command as a candidate only after confirming installed-version support and its effect on this bundle's MCP children. [Manage plugins](https://docs.openclaw.ai/plugins/manage-plugins#apply-changes-and-inspect)
- Current skill discovery can refresh file-backed skills for the next turn when watching is enabled. Higher-precedence workspace/managed copies can override plugin skills. A Git edit to a linked skill does not update an independent copy. [Skills](https://docs.openclaw.ai/tools/skills)
- Workspace `AGENTS.md` is session bootstrap guidance. Repository instructions and each agent's workspace instructions are separate unless configuration explicitly makes them the same. For changed bootstrap instructions, use a fresh affected session as the conservative acceptance step, without deleting existing conversation history. [Agent workspace](https://docs.openclaw.ai/concepts/agent-workspace)
- Configuration application depends on the changed fields and reload mode; a reload may replace a subsystem or require a gateway restart. Do not assume every config edit is harmless or hot-reloadable. [Config hot reload](https://docs.openclaw.ai/gateway/configuration/hot-reload)

The existing README's older-version advice to start a new Oliver session is conservative, but does not establish a subprocess restart mechanism. The cPanel documentation's gateway restart advice concerns environment propagation, not a requirement for every source change. Do not run capability-acceptance, doctor repair, plugin enable/install or configuration commands merely to “refresh” without reviewing their effects and authorization.

### Files that actually changed for the proposed initial upgrade

Comparing `cebec0dc…` to `2417036`:

- `plugin.json`, both MCP manifests, `run_mcp.py`, the installer, active root skills and `config/` are unchanged.
- The launcher adds the checkout-aware `--dashboard` path.
- Application code/resources and schema move to Phase 1/2; packaging adds preview CSS. Production dependency constraints are unchanged.
- Consequently, if the runtime is already linked to this checkout and has no shadowing copies, the initial upgrade needs no skill copy, registration rewrite, agent persona change or OpenClaw upgrade merely to obtain Phase 2. It needs controlled code/data validation and replacement of affected running application processes.
- If registration is copied, the copy is authoritative until deliberately updated; Git alone is insufficient. Sync only the verified active bundle, preserving its runtime data identity. If a dashboard directly uses the installed wheel, refresh that package or deliberately adopt the existing launcher route under authorization.

## D. Minimum update requirements by change type

These are conditional recommendations, not operations executed here.

| Change type | Minimum necessary action | Gateway / session impact |
| --- | --- | --- |
| Python source | Update the actual loaded bundle to the reviewed SHA; replace affected Business Prospector MCP processes and any affected dashboard process | Scoped supported reload/restart first; verify new code/tools. A fresh chat alone is not proof. Gateway restart only if the actual process owner offers no reliable narrower mechanism |
| Python dependencies | Check the effective venv; if requirements changed or imports fail, prepare/install the reviewed dependency set while affected work is stopped, then restart its consumers | No global OpenClaw upgrade by default; avoid modifying a venv while live MCPs use it |
| MCP registration | Validate both manifest formats, plugin identity and effective paths; apply only a necessary registration change via supported installed-version controls | Refresh tool discovery in affected sessions and verify child processes; broader restart only if required |
| OpenClaw skill instructions | Update linked source; if a verified independent copy is authoritative, review and synchronize only that skill, preserving local edits | Use supported skill refresh/watcher behavior; otherwise a fresh affected session. No Python restart solely for skill prose |
| Agent instructions | Update the actual authorized instruction file, preserving persona/memory and unrelated directives; do not copy root AGENTS wholesale into both workspaces | Fresh affected agent session for a deterministic acceptance check; no gateway restart solely for instruction prose |
| SQLite schema | Quiesce all application writers, back up consistently, rehearse on a copy, explicitly authorize/apply once, compare existing data | No automatic gateway restart requirement. Do not allow concurrent old/new application versions to initialize/mutate the database |
| OpenClaw gateway configuration | Change only necessary fields; validate installed-version behavior and confirm effective application | Hot-apply only when supported; authorize a gateway restart if the actual changed fields/environment require it |
| CSS/fixtures/package assets | Synchronize resources with the code revision and verify the path actually imported; refresh installed copy only for consumers that use it | No regeneration of existing websites; reload affected UI/resources as needed and avoid mixed revisions during update |

## E. Recommended small update workflow

A small script with `--check --target <full-SHA>` and `--apply --target <same-full-SHA>` is sufficient once runtime ownership/reload capabilities are established. **No script is implemented here.** Do not add a daemon, CI/CD system, automatic pulling schedule or parallel release machinery for this need.

### Proposed mode boundaries

- **`--check`:** report-only for the live checkout/runtime: verify identity, clean tree including untracked work, ancestry, actual registration/data paths, dependency availability and changed-file categories. Compare the remote branch without updating the working tree. Obtain missing target objects in private temporary validation storage if needed. Use disposable data for tests/builds/migration rehearsal. No operational imports that initialize repositories, installs, credential dumps, registration/config edits, restarts or production database writes. State all temporary writes and unavailable checks explicitly. A check requiring operational inspection must first have that access authorized.
- **`--apply`:** require explicit authorization for the exact target and planned code/data/reload effects; rerun preconditions, stop on drift, and apply only the reviewed plan. An invocation is not permission for publication, outreach, DNS changes, an OpenClaw upgrade or broad repair. Serialize updates with a lock outside public site roots.
- Return clear planned/applied/failed stages and sanitized evidence. Keep the script small: identify state, validate, protect data, fast-forward, reload, verify. If runtime ownership is unknown, fail with a concrete prerequisite rather than guessing a kill/restart command.

### Ordered procedure

1. **Verify the published development revision.** Require appropriate validation, clean Git state and the exact reviewed target SHA on `openclaw-port` in GitHub. Implementation changes require passing runtime tests; documentation-only changes require review and diff/link checks. The initial investigation left its instruction fix for a separately authorized commit/push. Baseline `2417036` contains Phase 1/2 but not the replacement AGENTS; the controlled update target must include the documentation finalization as well.
2. **Inventory before changing the Mac Mini.** Confirm actual checkout, current commit, branch, dirty/untracked work, effective plugin link/copy, interpreter, active skill sources, MCP/dashboard processes and Oliver/Tony tool/workspace ownership. Record the existing data directory, six lead identities/statuses, schema, and website/private-manifest hashes without disclosing records. Do not overwrite divergent or local work; resolve it separately.
3. **Prepare and approve the exact plan.** Require the reviewed target to be available on the intended branch and a fast-forward from the preserved runtime checkout. Review dependency/schema/manifest/skill deltas and installed-version reload support. Rehearse tests, imports/resources and v6→v7 migration on disposable data/copies. If state differs from the earlier six-lead/one-site inventory, report and validate the actual current baseline.
4. **Drain affected work and protect data.** Pause prospecting, generation, approvals/publication and dashboard writes for all consumers of the same database. Stop only the affected managed MCP/dashboard consumers using their actual owner; never broad `pkill`. Make a consistent SQLite backup with WAL handled correctly, preserve the website/manifest/revision directories and configuration locally with restricted permissions, and record prior code/dependency state. Verify recoverability before moving code. Keep unrelated OpenClaw agents/services running where ownership permits.
5. **Update only the reviewed code.** Fetch the authorized branch, recheck the pinned SHA and unchanged local state, then fast-forward to that exact SHA; do not blindly pull a moving tip. Do not use `reset --hard`, clean away files, auto-stash local work or merge runtime divergence without review. A linked bundle requires no duplicate copying. Keep data outside Git and preserve registration/data-directory identity.
6. **Apply only needed environment/schema changes.** Skip dependency installation when the effective venv satisfies unchanged requirements and checkout-based imports/resources pass. If installation is needed, the existing setup script is a building block, not a complete update transaction. Rehearse the database change, then apply it once under maintenance authorization before resuming consumers. Verify v7 and compare all preserved lead rows/statuses. Do not generate or revise the existing website. Do not migrate data between fallback and Agent Plugins directories implicitly.
7. **Reload the narrowest affected scope.** Use a verified supported plugin/MCP reload for this installed OpenClaw version and confirm replacement children/tool schemas. Restart the dashboard separately only if affected. Start fresh affected agent sessions where instruction/tool snapshots need it; preserve their histories. If a scoped restart is unsupported or fails to replace the real consumers, report the need for an explicitly authorized gateway restart instead of pretending the new code is active.
8. **Health-check and resume.** Verify commit/import path/interpreter, dependency imports, packaged resources, MCP initialize/tools-list and expected Phase 2 tool signatures. First use a disposable database for any mutating smoke tool; `prospect_fake` writes records and must not be a production health check. After the authorized migration, perform controlled read-only checks against the intended DB, confirm lead preservation and unchanged existing website hashes, and check both agents' tool visibility without prospecting/outreach. Keep cPanel configuration presence separate from network authentication/publication. Resume only after required checks pass.

### Recovery rule

If any apply stage fails, stop affected work and preserve backups, old artifacts and diagnostics. Do not repeatedly initialize/migrate, delete a website, reset Git or restore an older database over newer writes automatically. A database-changing update requires a coordinated reviewed recovery of code, dependencies and data; reversing only the Git revision is not a guaranteed rollback. The current installer has no such recovery transaction.

## F. Automation, risks and remaining blockers

**Automatable once authorized:** local history/diff classification, clean-tree and target checks, syntax/tests/build/import probes, disposable migration checks, backup/hash verification, pinned fast-forward, a version-verified scoped reload, and sanitized post-update checks. No credentials need to enter chat or be copied off the runtime.

**Requires explicit operational authorization:** live inventory access, maintenance/draining, protected runtime backups, applying code/dependencies/configuration, live schema changes and restarts. These can be approved as one concrete bounded update plan; routine steps within that plan need not ask repeatedly. Publication, outreach and unrelated infrastructure changes remain separate.

**Can be verified offline:** branch ancestry, AWS absence in repository integration, source versus installed-package loading rules, manifest compatibility, changed skill inventory, package contents, deterministic generation/approval behavior, and synthetic lead/artifact preservation. The earlier consolidation already passed 474 tests and a six-row synthetic v6→v7 probe; those are historical local results, not fresh runtime validation from this investigation.

**Requires Mac Mini inspection:** exact OpenClaw version and scoped reload support; plugin source path/link/copy; MCP process ownership/lifetime; effective Python environment; dashboard start command; six-lead and site baseline freshness; any extra local migration work; current registration/data path; and actual Oliver/Tony workspace and permission boundaries.

Specific risks:

- **Six leads:** repository construction performs schema initialization. A seemingly read-only application check can migrate the DB; a path mismatch can select/create the wrong database. Copy-based rehearsal and a consistent backup precede approved live initialization.
- **Existing website:** runtime update should not touch it. Regeneration is separate and can invalidate approval; old receipts without Phase 1 integrity may need explicit reapproval before future publication. Already-published artifacts remain protected.
- **Oliver/Tony:** a shared runtime means a scoped plugin reload may affect both; separate agent workspaces can contain different stale skill copies. Never replace their workspace AGENTS, persona or memory wholesale.
- **Skill coverage:** the root active skills cover setup and prospecting, and the prospecting skill explicitly excludes website generation/deployment. Phase 2 MCP capability does not itself update Oliver/Tony role instructions or grant authorization. Any later generation-oriented skill/instruction change needs a separate scoped task.
- **Installer limitations:** setup installs into the persistent venv and performs only import checks; it has no `--check/--apply`, version pinning, quiescing, data backup, migration rehearsal, registration verification, restart orchestration or rollback. Do not run it on every Git pull by habit.
- **Documentation/version drift:** current online reload features may not exist on the older installed runtime. The package distribution version is 0.1.1 while the pre-existing module `__version__` is 0.1.0; use commit/import identity to distinguish revisions. Some older runbook steps are broad installation recipes, not safe minimal-update automation.
- **Instruction distribution:** committing/pushing this AGENTS correction does not apply it to other checkouts. Those retain the old requirement until a controlled update includes the documentation commit. Removing it does not repair SSH or establish cPanel health.

## Verification of this change

The initial investigation used local Git/file inspection and official documentation only. Documentation finalization additionally verifies GitHub branch identities before and after the authorized commit/push. No OpenClaw CLI/runtime, setup script, service-env file, operational database or Mac Mini connection is invoked. Changes are documentation-only; no new runtime tests are needed or claimed. Finalization checks the two-file diff, Markdown links/structure, sensitive-content review, preserved Phase 1/2 ancestry, unchanged `main`, matching local/remote commit identities and a clean working tree.
