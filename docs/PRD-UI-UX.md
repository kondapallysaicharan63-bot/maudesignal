# UI/UX Requirements & Design Specification

**Version:** 1.0 | **Date:** May 2026

---

## Design Philosophy
- Clean, professional, medical-grade look — trustworthy, not flashy
- Easy navigation for Regulatory Affairs and Quality teams
- **Data isolation always visible** — every user sees a clear "Viewing: [Company]" banner
- Desktop-primary, mobile-friendly
- Dark/Light mode support

---

## Color Scheme

| Role | Hex |
|---|---|
| Primary (Medical Blue) | `#0066CC` |
| Success | `#00CC66` |
| Warning | `#FFAA00` |
| Critical | `#CC0000` |
| Background (Light) | `#F8F9FA` |
| Background (Dark) | `#1A1A2E` |

---

## Layout

### Sidebar (Left)
- Dashboard (Home)
- Analysis
- Documents
- Signals & Risks
- Portfolio (Multiple Devices)
- Regulatory Intelligence *(Phase 2)*
- Settings & Audit Log
- Tenant Switcher *(Enterprise admin only)*

### Top Bar
- Company logo + Company Name
- Device / Portfolio selector
- User profile + Logout
- Notification bell (new signals, regulatory updates)

---

## Pages

### 1. Dashboard (Home)
- **Overall Risk Score** — large colored card (Green/Yellow/Red)
- Key metrics: Total Reports, Active Signals, Next PSUR Deadline, AI/ML Drift Risk
- Recent analyses table
- Quick actions: "New Analysis", "Generate PSUR", "Upload Complaints"

### 2. Analysis Page
- Input: Product code(s), date range, data sources (MAUDE + internal CSV)
- "Run Analysis" button with real-time progress bar
- Results tabs: Summary | Signals & Trends | Subgroup Analysis | Raw Data Explorer

### 3. Documents Page
- Document library with version history
- One-click generation: PSUR | PMS Plan | PMCF Plan | CAPA Input
- **FDA Compliance Checker** results — green/red flags with gap descriptions
- Version compare (diff view)

### 4. Signals & Risks
- Filterable table: Severity, Type, Status, Device
- AI insight cards
- Trend charts over time (Plotly/Altair — interactive)
- Export: PDF, CSV

### 5. Settings / Admin
- Tenant/company settings
- LLM configuration (Local vs Cloud, model selection)
- User management (invite, RBAC assignment)
- Audit logs (searchable, exportable)
- Data backup & export

---

## Key UI Components

| Component | Implementation |
|---|---|
| Cards | Subtle shadow, color-coded status |
| Charts | Plotly or Altair (interactive) |
| Tables | Sortable + filterable + exportable (`st.dataframe`) |
| Status badges | Success / Warning / Critical |
| Progress | Spinner + step indicator during LLM runs |
| Modals | Confirmations, detail views |
| Tenant banner | Persistent top-of-page strip |

---

## Accessibility
- WCAG 2.1 AA compliant
- Keyboard navigation throughout
- High contrast mode toggle
- Screen reader compatible labels

---

## Technology

**Phase 1 (MVP):**
- Streamlit
- `streamlit-option-menu` for sidebar
- `streamlit-authenticator` or custom JWT login
- Plotly for charts

**Phase 2:**
- React.js + FastAPI backend
- Shadcn/UI or Tailwind + Radix UI
- TanStack Table for advanced data grids
