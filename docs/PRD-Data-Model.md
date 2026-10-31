# Data Model

> **Pre-existing planning draft (May 2026), kept for history.** It describes plans, not what
> MaudeSignal does today. Today: U.S. FDA data (MAUDE, recalls, 510(k)). UK MHRA alerts
> appear as labelled regulator context only, not counted. EU data is not included yet.
> Current scope: [README](../README.md#today--tomorrow).

## Core Entities

### Multi-Tenancy Foundation
Every table carries `tenant_id`. Row-level security enforced at both ORM and DB layers.

```
Tenant
  id (PK)
  name
  slug
  database_url (or schema name)
  created_at
  is_active

User
  id (PK)
  tenant_id (FK → Tenant) [indexed]
  email
  role: enum(admin, analyst, viewer, auditor)
  sso_subject (for OAuth2/OIDC)
  last_login_at
  is_active
```

### Device & Ingestion
```
DeviceCatalogRecord
  id, tenant_id
  product_code, device_name, device_class
  applicant_name, 510k_number
  is_ai_ml: bool
  created_at

RawReportRecord
  id, tenant_id
  mdr_report_key, report_number
  product_code, device_name
  event_type, event_date
  narrative_text
  source: enum(maude, internal_csv, recalls_api)
  raw_json
  ingested_at

NormalizedEventRecord
  id, tenant_id
  raw_report_id (FK)
  product_code, event_date
  patient_outcome, device_problem
  normalized_at
```

### Extraction & Classification
```
ExtractionRecord
  id, tenant_id
  raw_report_id (FK)
  skill_name, skill_version
  failure_mode, failure_category
  device_type_category: enum(hardware, samd, ai_ml, ivd, combination)
  severity_level: enum(critical, serious, moderate, minor)
  causality_assessment
  confidence_score (max 0.95)
  extracted_at

LLMAuditLogRecord
  id, tenant_id
  extraction_id (FK)
  provider, model, temperature
  prompt_tokens, completion_tokens
  latency_ms
  raw_response_json
  created_at
```

### Analysis & Signals
```
RootCauseReportRecord
  id, tenant_id
  run_id
  failure_mode, cluster_size
  hypothesis_text
  supporting_report_ids (JSON array)
  skill_version
  created_at

TrendSnapshotRecord
  id, tenant_id
  product_code, metric_name
  period_start, period_end
  trend_direction: enum(up, down, flat)
  p_value, slope
  narrative_text
  created_at

AlertRuleRecord
  id, tenant_id
  metric, operator, threshold
  delivery: enum(console, slack, email)
  is_active

AlertEventRecord
  id, tenant_id
  rule_id (FK)
  triggered_at, value_observed
  notified_at
```

### Reporting
```
PsurReportRecord
  id, tenant_id
  product_code
  period_start, period_end
  status: enum(draft, under_review, approved)
  report_markdown, report_pdf_path
  fda_compliance_gaps (JSON array)
  version
  generated_at, approved_at, approved_by
```

### External Sources
```
ExternalSourceRecord
  id, tenant_id
  source_type: enum(pubmed, clinicaltrials, recalls_api, eudamed)
  external_id
  title, summary, url
  relevance_score
  fetched_at
```

---

## Key Indexes
- `(tenant_id, product_code)` on all analysis tables
- `(tenant_id, event_date)` on RawReportRecord
- `(tenant_id, created_at)` on PsurReportRecord
- `tenant_id` on every table (FK + index)

## Migration Strategy
- SQLite for development and small deployments
- PostgreSQL for production with per-tenant schema
- Alembic migrations with tenant-aware revision scripts
