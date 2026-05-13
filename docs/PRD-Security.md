# Security & Multi-Tenancy Architecture

## Core Principle
**Every company gets complete data isolation.** No shared database rows. No cross-tenant queries.

---

## Multi-Tenancy Model

**Database-per-tenant** (recommended default):
- Each company gets its own SQLite file (small deployments) or PostgreSQL schema (enterprise).
- `tenant_id` is enforced at every ORM model, query, and API endpoint.
- Middleware rejects any request missing a valid tenant context.

**Tenant isolation layers**:
1. Authentication token carries `tenant_id`
2. FastAPI middleware injects tenant context into every request
3. SQLAlchemy session scoped to tenant schema
4. No cross-tenant joins possible by design

---

## Authentication & Authorization

| Layer | Technology |
|---|---|
| Authentication | OAuth2 / OIDC (Keycloak, Auth0, or Ory Kratos) |
| SSO | SAML 2.0, Azure AD, Okta |
| Session | JWT with 30-min expiry |
| RBAC Roles | Admin, Analyst, Viewer, Auditor |

### RBAC Role Permissions

| Action | Admin | Analyst | Viewer | Auditor |
|---|---|---|---|---|
| Run analysis | ✅ | ✅ | ❌ | ❌ |
| Generate documents | ✅ | ✅ | ❌ | ❌ |
| View signals | ✅ | ✅ | ✅ | ✅ |
| Export data | ✅ | ✅ | ❌ | ✅ |
| Manage users | ✅ | ❌ | ❌ | ❌ |
| View audit logs | ✅ | ❌ | ❌ | ✅ |
| Change settings | ✅ | ❌ | ❌ | ❌ |

---

## Data Security

- **Encryption at rest**: AES-256 for database files and stored documents
- **Encryption in transit**: TLS 1.3 for all API traffic
- **Local LLM option**: Ollama inference keeps data fully on-premise (no external API calls)
- **Air-gapped support**: Full functionality with local models + offline FDA guidance index
- **Data minimization**: Only store fields needed for PMS analysis
- **Audit Logging**: Every action logged with: user, action, timestamp, tenant, LLM model used

---

## Compliance Readiness

| Standard | Status |
|---|---|
| SOC 2 Type II | Architecture ready; certification path documented |
| ISO 27001 | Aligned documentation and controls |
| HIPAA | BAA-ready for hosted version; MAUDE data is pre-anonymized |
| 21 CFR Part 11 | Electronic records + audit trail; e-signature in Phase 2 |
| FDA QMSR | Tool Validation Package (IQ/OQ/PQ) provided to customers |

---

## Vulnerability Management

- Dependency scanning via `pip-audit` in CI
- SBOM (Software Bill of Materials) generated per release
- Regular penetration testing (before each major release)
- Responsible disclosure policy in `SECURITY.md`

---

## UI Security Controls

- Clear tenant banner on every screen: **"Viewing: [Company Name] data"**
- No cross-tenant navigation or data leakage
- Session timeout enforced at both client and server
- Role-based page visibility (Viewer cannot see generate/export buttons)
