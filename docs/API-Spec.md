# API Specification

**Base URL:** `/api/v1`
**Auth:** Bearer JWT token (obtained via OAuth2/OIDC login)
**Tenant:** Derived from JWT claims — no `tenant_id` in URL paths

---

## Authentication

### `POST /auth/token`
Exchange OAuth2 authorization code for JWT.

### `POST /auth/refresh`
Refresh an expired JWT.

### `GET /auth/me`
Returns current user info + role.

---

## Analysis

### `POST /analyses`
Start a new analysis run.
```json
{
  "product_codes": ["QIH", "MYN"],
  "date_from": "2025-01-01",
  "date_to": "2025-12-31",
  "sources": ["maude", "internal"],
  "internal_file_id": "uuid-optional"
}
```
Returns: `{ "run_id": "uuid", "status": "queued" }`

### `GET /analyses/{run_id}`
Get analysis results.

### `GET /analyses`
List analyses with filters: `?product_code=QIH&status=complete&limit=20&offset=0`

### `GET /analyses/{run_id}/signals`
Get signals detected in a run.

---

## Documents

### `POST /documents/generate`
Generate a document.
```json
{
  "document_type": "psur",
  "product_code": "QIH",
  "period_start": "2025-01-01",
  "period_end": "2025-12-31",
  "run_id": "uuid-optional"
}
```

### `GET /documents`
List documents: `?product_code=QIH&document_type=psur&limit=10`

### `GET /documents/{id}`
Get document content (markdown).

### `GET /documents/{id}/pdf`
Download PDF.

### `POST /documents/{id}/compliance-check`
Run FDA Compliance Checker on a document.
Returns: `{ "gaps": [...], "pass_rate": 0.85 }`

### `GET /documents/{id}/versions`
List version history.

---

## Signals

### `GET /signals`
List active signals: `?severity=critical&product_code=QIH&status=open`

### `PATCH /signals/{id}`
Update signal status.
```json
{ "status": "investigating", "notes": "..." }
```

---

## Portfolio

### `GET /devices`
List devices in the tenant catalog.

### `GET /portfolio/summary`
Overall risk summary across all devices.

---

## Ingestion

### `POST /ingestion/maude`
Trigger MAUDE ingestion.
```json
{ "product_code": "QIH", "limit": 100, "date_from": "2025-01-01" }
```

### `POST /ingestion/upload`
Upload internal complaint CSV/JSON.
(multipart/form-data)

---

## Admin / Tenant

### `GET /tenant/settings`
Get current tenant configuration.

### `PATCH /tenant/settings`
Update tenant settings (LLM provider, etc.).

### `GET /users`
List users in tenant.

### `POST /users/invite`
Invite a new user.
```json
{ "email": "user@company.com", "role": "analyst" }
```

### `PATCH /users/{id}/role`
Change user role.

### `GET /audit-log`
Query audit log: `?user_id=uuid&action=generate_document&limit=50`

---

## Webhooks (Phase 2)

Events dispatched to a configured endpoint:
- `signal.detected` — new signal above threshold
- `regulatory.update` — new FDA guidance/recall for a watched product code
- `psur.deadline.approaching` — PSUR due in N days
- `analysis.complete` — async analysis run finished

---

## Error Responses

All errors use RFC 7807 Problem Details:
```json
{
  "type": "https://maudesignal.io/errors/not-found",
  "title": "Resource Not Found",
  "status": 404,
  "detail": "Analysis run abc-123 not found in this tenant"
}
```
