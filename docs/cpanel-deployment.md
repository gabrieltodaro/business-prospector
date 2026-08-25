# Sales Preview deployment with cPanel UAPI

## Boundary and lifecycle

Publishing is an explicit operation after approval:

```text
Internal Website
  -> human approval
Sales Preview
  -> explicit publish authorization
SalesPreviewDeploymentService
  -> PreviewDeploymentProvider
HostGatorPreviewDeploymentProvider
  -> CPanelUapiClient
  -> cPanel UAPI over HTTPS
```

Publication does not change the lead status to `contacted`. `sales_preview` remains the
commercial lifecycle stage; deployment state is stored separately in the private local
site manifest. No deployment metadata or credential is stored in SQLite.

## Official operations

The current cPanel catalog documents these UAPI v3 operations:

- `GET /execute/DomainInfo/domains_data?format=list` reads domain hosting configuration;
- `GET /execute/SubDomain/addsubdomain` creates the preview subdomain;
- `POST /execute/Fileman/upload_files` uploads multipart files;
- `GET /execute/Fileman/list_files` checks directory contents;
- `GET /execute/Fileman/rename_file` promotes the initial staged directory;
- `GET /execute/Fileman/delete_file` cleans a failed staging directory only;
- `GET /execute/SSL/installed_hosts` reports installed certificate coverage.

The previously supplied `Domains/add_domain` documentation URL is not present in the
current official operation catalog. `SubDomain/addsubdomain` is used through the UAPI
`/execute` endpoint and response envelope (`apiversion=3`), not through the deprecated
cPanel API 2 invocation format.

Normative references: [UAPI overview](https://api.docs.cpanel.net/openapi/cpanel/overview/),
[API tokens](https://api.docs.cpanel.net/cpanel/tokens/),
[create subdomain](https://api.docs.cpanel.net/specifications/cpanel.openapi/subdomain/subdomain-addsubdomain),
[domain configuration](https://api.docs.cpanel.net/specifications/cpanel.openapi/domain-information/domaininfo-domains_data),
[upload files](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-upload_files),
[list files](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-list_files),
[rename](https://api.docs.cpanel.net/specifications/cpanel.openapi/manage-files/fileman-rename_file), and
[installed SSL hosts](https://api.docs.cpanel.net/specifications/cpanel.openapi/cpanel-account-ssl-management/ssl-installed_hosts).

The standard cPanel documentation shows a UAPI v3 outer envelope containing
`apiversion`, `module`, `func` and `result`. Some hosting environments or proxies have
been observed returning that `result` object directly. `CPanelUapiClient` normalizes
both the documented wrapped form and this credible flattened response variant at one
transport boundary. A flattened object is accepted only when it contains both `status`
and `data`; arbitrary JSON objects remain malformed. Application and domain code never
depend on which transport response shape was received. This is compatibility with an
observed hosting response variant, not a provider guarantee.

## Authentication and secrets

Only cPanel API Token authentication is supported:

```http
Authorization: cpanel <username>:<api-token>
```

Required runtime variables:

```text
BUSINESS_PROSPECTOR_CPANEL_BASE_URL=https://cpanel-hostname.example:2083
BUSINESS_PROSPECTOR_CPANEL_USERNAME=cpanel-account-user
BUSINESS_PROSPECTOR_CPANEL_API_TOKEN=<secret>
BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN=gapps.tech
BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR=public_html/sales-previews
```

The token belongs only in OpenClaw's user-owned service environment. It must not be put
in manifests, repository config, SQLite, site manifests, dashboard requests, logs or
chat. `cpanel_status` returns only `configured` and `root_domain`; it performs no network
request. The launcher recovers only the five allowlisted variables when OpenClaw 2026.7.1
starts MCP with a sanitized environment.

## Domain and remote-path policy

The MCP accepts only a persisted lead id and an explicit authorization boolean. It never
accepts a host, username, token, domain or remote path.

For preview slug `drlaura`, the provider derives:

```text
FQDN:          drlaura.gapps.tech
document root: public_html/sales-previews/drlaura
```

The slug must be lowercase ASCII letters/digits/hyphens, at most 32 characters. Remote
paths are relative, normalized and confined below the configured base directory.
Existing domains are idempotent only when their document root matches. A different root
is a structured conflict and is never modified.

Creating a cPanel domain and provisioning public DNS are distinct responsibilities. If
DNS is external, a future `DnsProvider` must manage the record or wildcard independently.
This implementation contains no DNS, Cloudflare or registrar integration.

## Public artifact and upload

Before upload, Python revalidates the generated site and Sales Preview metadata. Every
rendered asset must have `approval_status=approved_for_publish` and acceptable rights.

Only these files are eligible:

```text
index.html
styles.css
assets/** regular files
```

The uploader rejects symlinks, traversal, more than 100 files and more than 25 MiB total.
It does not upload `site-manifest.json`, `README.md`, SQLite, source files or secrets.
Uploads use multipart UAPI requests with `overwrite=0` and permissions `0644`.

## Staging, idempotence and atomicity

Initial publication uses:

```text
public_html/sales-previews/.staging-<slug>-<artifact-id>/
  -> validate every upload result
  -> ensure subdomain/document root
  -> Fileman/rename_file to public_html/sales-previews/<slug>/
```

`rename_file` only succeeds when the destination does not exist. This gives a narrow
promotion boundary for the first publication, but it is not a general atomic directory
swap. If a final directory already exists, changed-artifact replacement is rejected.
An unchanged artifact is idempotent through its SHA-256 artifact identity in local
deployment metadata and does not upload again.

Failed uploads are failures even if some files succeeded. The provider attempts to delete
only its exact staging directory. It never deletes the final root, parent directory or an
unrelated domain.

## SSL and commercial readiness

`SSL/installed_hosts` is read-only. If the FQDN is covered, `ssl_status=active`; otherwise
the result is `pending` or `unknown`. Publication may therefore succeed while HTTPS is
pending. Such a URL must not be sent to a prospect.

The provider does not start AutoSSL. The current cPanel-user operation catalog includes
AutoSSL status/actions, but certificate issuance also depends on DNS and provider policy.
WHM is not required or used.

## Status and unpublish

`sales_preview_deployment_status(lead_id)` reads:

- domain presence and document root;
- presence of `index.html` and `styles.css`;
- installed SSL coverage.

It does not perform a public HTTP GET and does not mutate local metadata.

`unpublish` currently returns `unsupported` without a network call. Recursive UAPI deletion
exists, but removing both domain configuration and content safely is not transactional.
The conservative result is intentional.

## Deployment metadata

After success, the private local `site-manifest.json` receives:

```json
{
  "deployment": {
    "deployment_status": "published",
    "deployment_id": "artifact checksum prefix",
    "artifact_checksum": "sha256...",
    "preview_url": "https://drlaura.gapps.tech",
    "files_uploaded": 3,
    "domain_status": "created",
    "ssl_status": "pending",
    "published_at": "...",
    "last_checked_at": null,
    "warnings": []
  }
}
```

No credential is persisted. The manifest itself is excluded from public upload.

## Production checklist

1. Review implementation and offline tests.
2. In cPanel, open **Security → Manage API Tokens**.
3. Create a dedicated token named for Business Prospector; use the shortest supported
   expiration/least privilege compatible with the required UAPI functions.
4. Copy it once into `~/.openclaw/service-env/ai.openclaw.gateway.env`; never put it in Git
   or chat.
5. Restrict that file to the account owner (`chmod 600`).
6. Restart the OpenClaw Gateway and run `bin/business-prospector-mcp --check-cpanel-env`.
7. Confirm `business-prospector__cpanel_status` reports configured without revealing the
   token, username or hostname.
8. First test with a throwaway approved lead/slug, never Laura.
9. Confirm cPanel domain/document root, DNS, uploaded files and SSL independently.
10. Revoke the token immediately if any secret exposure is suspected.

## Future SSH/SFTP adapter

SSH is not a dependency. After HostGator enables it, a future architecture may compose:

```text
HostGatorPreviewDeploymentProvider
├── CPanelDomainManager
└── SftpArtifactUploader
```

SFTP could provide efficient recursive transfer, controlled directory swaps, cleanup and
rollback. It must remain behind the same provider boundary and use a dedicated key/secret
boundary; FTP and cPanel passwords remain prohibited.
