# SPANFORGE MASTER BUILD PLAN v6 - COMPLETE
## All Components: CLI, SDK, Web Apps, Products with Clear Priorities & Timeline

**Status:** READY FOR EXECUTION  
**Timeline:** May 2026 – October 2026 (26 weeks)  
**Team:** 2 core engineers, 1 product/GTM, 1 QA/DevOps  

---

## EXECUTIVE SUMMARY: WHAT WE'RE BUILDING

This is **EVERYTHING** broken down by:
- 📦 **SDK** (core services + 25 CLI tools)
- 🌐 **Web Apps** (43 React/Next.js applications)
- 🛠️ **CLI Tools** (60 total: 25 SDK-integrated + 35 standalone)
- 💰 **Products** (11 revenue-generating products)
- 📋 **Artifacts** (documentation, templates, standards)

---

# PART I: COMPLETE COMPONENT BREAKDOWN

## A. SDK CORE SERVICES (What goes in `/src/spanforge/`)

### PRIORITY: CRITICAL (Must ship by Week 6)

#### 1. CORE SERVICES (20 service classes)
**Location:** `/src/spanforge/` (core services already exist, finalize only)  
**Status:** ✅ Mostly exist, need polishing  
**Timeline:** Week 1–2 (minimal work)  

| Service | Purpose | Status | Code File | Effort |
|---|---|---|---|---|
| Event | Create/manage RFC-0001 events | ✅ Done | `event.py` | — |
| Trace | Trace chains for LLM calls | ✅ Done | `trace.py` | — |
| Span | Individual operation tracking | ✅ Done | `_span.py` | — |
| Audit | Log compliance decisions | ✅ Done | `audit.py` | — |
| Policy | Load + manage policies | ✅ Done | `policy.py` | — |
| Gate | Execute gates (security, quality, etc) | ✅ Done | `gate.py` | — |
| Governance | Enforce governance rules | ✅ Done | `governance.py` | — |
| Config | Manage configuration | ✅ Done | `config.py` | — |
| Cache | Cache decisions | ✅ Done | `cache.py` | — |
| Cost | Track AI spending | ✅ Done | `cost.py` | — |
| Drift | Detect model drift | ✅ Done | `drift.py` | — |
| PII | Detect sensitive data | ✅ Done | `redact.py` | — |
| Secrets | Manage encryption keys | ✅ Done | `secrets.py` | — |
| Signing | HMAC signing for audit chains | ✅ Done | `signing.py` | — |
| Validate | Schema validation | ✅ Done | `validate.py` | — |
| Normalizer | Normalize event formats | ✅ Done | `normalizer.py` | — |
| Export | Multi-backend export | ✅ Done | `export/` | — |
| Store | Trace store (local DB) | ✅ Done | `_store.py` | — |
| Stream | Event streaming interface | ✅ Done | `_stream.py` | — |
| ULID | Unique ID generation | ✅ Done | `ulid.py` | — |

**Deliverable:** All 20 services polished + tested

---

#### 2. CLI TOOL INTEGRATION (25 tools integrated into SDK)
**Location:** `/src/spanforge/_cli*.py`  
**Status:** Partial  
**Timeline:** Week 1–6 (6 weeks)  

**GROUP 1A: Event & Schema (8 tools)** — Week 1–2

| Tool | Command | Location | Status | Effort |
|---|---|---|---|---|
| Event Creator | `spanforge event create` | `_cli.py` | Partial | 1–2d |
| Event Validator | `spanforge validate` | `_cli.py` | ✅ | <1d |
| Event Inspector | `spanforge inspect` | `_cli.py` | ✅ | 1d |
| Event Stats | `spanforge stats` | `_cli.py` | Partial | 2d |
| Schema Checker | `spanforge check-compat` | `_cli.py` | ✅ | 1d |
| Deprecation List | `spanforge list-deprecated` | `_cli.py` | ✅ | 1d |
| Consumer Check | `spanforge check-consumers` | `_cli.py` | ✅ | 1d |
| Migration Roadmap | `spanforge migration-roadmap` | `_cli.py` | ✅ | 1d |

**GROUP 1B: Audit & Compliance (7 tools)** — Week 2–3

| Tool | Command | Location | Status | Effort |
|---|---|---|---|---|
| Audit Chain Verifier | `spanforge audit-chain` | `_cli_audit.py` | ✅ | 1–2d |
| Health Check | `spanforge check` | `_cli.py` | Partial | 2d |
| Audit Log Extractor | `spanforge audit extract` | `_cli_audit.py` | ❌ NEW | 2d |
| Compliance Report | `spanforge compliance report` | `_cli_compliance.py` | ❌ NEW | 3d |
| CEC Bundle Generator | `spanforge cec generate` | `_cli_audit.py` | Partial | 3d |
| Audit Gap Finder | `spanforge audit gaps` | `_cli_audit.py` | ❌ NEW | 2d |
| Policy Auditor | `spanforge policy audit` | `_cli_ops.py` | Partial | 2d |

**GROUP 1C: Policy & Gates (6 tools)** — Week 3–4

| Tool | Command | Location | Status | Effort |
|---|---|---|---|---|
| Policy Loader | `spanforge policy load` | `_cli_ops.py` | Partial | 2d |
| Gate Executor | `spanforge gate execute` | `_cli_ops.py` | ❌ NEW | 2d |
| Gate Status | `spanforge gate status` | `_cli_ops.py` | ❌ NEW | 2d |
| T.R.U.S.T. Scorer | `spanforge score` | `_cli_ops.py` | Partial | 2d |
| Readiness Checker | `spanforge readiness check` | `_cli_ops.py` | ❌ NEW | 2d |
| Gate History | `spanforge gate history` | `_cli_ops.py` | ❌ NEW | 2d |

**GROUP 1D: Config & Setup (4 tools)** — Week 4–5

| Tool | Command | Location | Status | Effort |
|---|---|---|---|---|
| Config Init | `spanforge config init` | `_cli.py` | Partial | 1–2d |
| Config Validate | `spanforge config validate` | `_cli.py` | Partial | 1–2d |
| Secrets Manager | `spanforge secrets set/get` | `_cli.py` | ❌ NEW | 1–2d |
| Dev Environment | `spanforge dev reset` | `_cli.py` | ❌ NEW | 2d |

**Deliverable:** All 25 tools shipped in `spanforge` v1.0 package

---

#### 3. FRAMEWORK COMPONENTS (Live v1.0)
**Status:** ✅ Already shipped  
**Timeline:** Reference only  

| Component | Type | Purpose | Status |
|---|---|---|---|
| RFC-0001 Standard | Standard | Open compliance schema | ✅ Live |
| Exit Gate System™ | Framework | Lifecycle stages + gates | ✅ Live |
| T.R.U.S.T. Framework™ | Framework | 5 governance dimensions | ✅ Live |
| CI/CD Gate Pipeline | Framework | 6 sequential gates | ✅ Live |
| CEC (Compliance Evidence Chain) | Framework | HMAC-signed audit bundles | ✅ Live |
| T.R.U.S.T. Scorecard | Framework | 5-pillar assessment | ✅ Live |

---

#### 4. INTEGRATION LIBRARIES (For product SDKs)
**Location:** `/src/spanforge/integrations/`  
**Status:** ✅ Mostly exist  
**Timeline:** Week 1–2 (finalize)  

| Integration | Purpose | Status |
|---|---|---|
| OpenAI | Chat models | ✅ |
| Anthropic | Claude models | ✅ |
| LangChain | LLM framework | ✅ |
| CrewAI | Agent framework | ✅ |
| LlamaIndex | RAG framework | ✅ |
| Gemini | Google models | ✅ |
| Azure OpenAI | Azure models | ✅ |
| Bedrock | AWS models | ✅ |
| Groq | Groq models | ✅ |
| Together | Together models | ✅ |
| Ollama | Local models | ✅ |
| LangGraph | Agentic workflows | ⚠️ Partial |

**Deliverable:** All integrations tested + working

---

#### 5. EXPORTERS (Runtime → external systems)
**Location:** `/src/spanforge/export/` + `/src/spanforge/exporters/`  
**Status:** ✅ Mostly exist  
**Timeline:** Week 1–2 (finalize)  

| Exporter | Target | Status |
|---|---|---|
| OTLP | OpenTelemetry Protocol | ✅ |
| Datadog | Datadog APM | ✅ |
| Grafana | Grafana Loki | ✅ |
| Splunk | Splunk HEC | ✅ |
| Syslog | Syslog servers | ✅ |
| Redis | Redis queue | ✅ |
| Webhooks | HTTP endpoints | ✅ |
| JSONL | File-based | ✅ |
| SQLite | Local database | ✅ |
| S3 | AWS S3 | ✅ |
| GCS | Google Cloud Storage | ✅ |
| Azure Blob | Azure storage | ✅ |
| SIEM (CEF/LEEF) | Security systems | ⚠️ Partial |

**Deliverable:** All exporters tested + working

---

## B. WEB APPLICATIONS (43 React/Next.js apps)

### PRIORITY: HIGH (Build weeks 7–20, ship with products)

**Location:** `/web/` or `/apps/`  
**Team:** Frontend + Backend engineers  
**Status:** ~30% built (partial dashboards exist)  

### Group 1: Product UIs (Required for P2, P8, P1 launches)

#### P2 GitHub App UI (P2 Product)
**Timeline:** Week 7–10 (required for product launch)  
**Effort:** 2–3 weeks

| Component | Purpose | Status | Effort |
|---|---|---|---|
| Dashboard | 30-day scan history, SARIF viewer | ❌ New | 5d |
| Settings | API key management, scan rules | ❌ New | 3d |
| Slack Integration UI | Alert config | ❌ New | 2d |
| GitHub Code Scanning | Results viewer | ❌ New | 3d |

**Deliverable:** GitHub App production-ready UI

---

#### P8 Cloud UI (P8 Product)
**Timeline:** Week 7–10 (required for product launch)  
**Effort:** 2–3 weeks

| Component | Purpose | Status | Effort |
|---|---|---|---|
| Trace Viewer | View/search events | ❌ New | 5d |
| Dashboard | Stats, cost tracking | Partial | 3d |
| Retention Tiers | Upgrade flow | ❌ New | 3d |
| Drift Detection | Visual alerts | ❌ New | 3d |

**Deliverable:** Cloud platform production-ready UI

---

#### P7 India UI (P7 Product - GTM only)
**Timeline:** Week 7–10 (no UI coding, just config)  
**Effort:** <1 week

| Component | Purpose | Status | Effort |
|---|---|---|---|
| Localization | Hindi/regional content | ❌ New | 2d |
| Partner Portal | SI onboarding | ❌ New | 3d |

**Deliverable:** India portal UI

---

### Group 2: Enterprise UIs (Required for P1, hardening)

#### P1 Managed SaaS Admin Dashboard
**Timeline:** Week 13–20 (required for P1 launch)  
**Effort:** 4–5 weeks

| Component | Purpose | Status | Effort |
|---|---|---|---|
| Customer Management | Org/model management | ❌ New | 5d |
| Policy Management | Create/edit/deploy policies | ❌ New | 5d |
| Gate Management | Configure + execute gates | Partial | 5d |
| Compliance Dashboard | Real-time compliance status | ❌ New | 5d |
| Audit Trail | Full compliance audit logs | ❌ New | 3d |
| Workflow Engine UI | Approve/reject workflows | ❌ New | 5d |
| Cost Dashboard | Per-model cost tracking | Partial | 3d |
| Reports | PDF/HTML compliance reports | ❌ New | 5d |

**Deliverable:** P1 admin UI production-ready

---

#### P6 Governance Dashboard (Board-level visibility)
**Timeline:** Week 21–30 (requires P1 completion)  
**Effort:** 2–3 weeks

| Component | Purpose | Status | Effort |
|---|---|---|---|
| Executive Summary | KPIs, risk score | ❌ New | 3d |
| Model Portfolio | All models status | ❌ New | 3d |
| Compliance Overview | Framework coverage | ❌ New | 3d |
| Trend Analysis | Historical metrics | ❌ New | 3d |

**Deliverable:** Board-ready dashboard

---

### Group 3: Developer/User UIs (Non-blocking, can delay)

#### P9 Training Data Scanner UI
**Timeline:** Week 21–30 (can delay if needed)  
**Effort:** 1–2 weeks

#### P3 Cost Intelligence Dashboard
**Timeline:** Week 21–30 (can delay if needed)  
**Effort:** 1–2 weeks

#### P4–P5 Audit Trail + Red Team UIs
**Timeline:** Week 21–30 (can delay if needed)  
**Effort:** 1–2 weeks each

#### P10–P11 API + White-Label UIs
**Timeline:** Week 31–60 (low priority)  
**Effort:** 1–2 weeks each

---

## C. CLI TOOLS (60 total)

### Group 1: SDK-Integrated (25 tools, Weeks 1–6)
**See Part B above**

---

### Group 2: Standalone CLI Tools (35 tools, Weeks 7–12)

**Location:** Separate PyPI packages  
**Team:** Backend engineers (parallel work)  
**Status:** ❌ Most do not exist yet  

#### Group 2A: Debugging (6 tools)
**Package:** `spanforge-debug`  
**Timeline:** Week 7–9  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Event Decoder | `spanforge-debug decode` | ❌ New | 1d |
| Trace Replayer | `spanforge-debug replay` | ❌ New | 1d |
| Log Sampler | `spanforge-debug sample` | ❌ New | 1d |
| Performance Profiler | `spanforge-debug profile` | ❌ New | 1d |
| Config Tester | `spanforge-debug test-config` | ❌ New | 1d |
| Event Generator | `spanforge-debug gen-events` | ❌ New | 1d |

**Deliverable:** `pip install spanforge-debug` working

---

#### Group 2B: Secrets & PII (5 tools)
**Packages:** `spanforge-pii`, `spanforge-secrets`  
**Timeline:** Week 7–9  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| PII Scanner | `spanforge-pii scan` | ✅ Core exists | 1d |
| Secrets Detector | `spanforge-secrets scan` | ✅ Core exists | 1d |
| Pattern Builder | `spanforge-secrets patterns` | ❌ New | 1d |
| Remediation Guide | `spanforge-pii remediate` | ❌ New | 1d |
| Compliance Checker | `spanforge-pii compliance` | ❌ New | 1d |

**Deliverable:** `pip install spanforge-pii` + `pip install spanforge-secrets` working

---

#### Group 2C: Cost Intelligence (5 tools)
**Package:** `spanforge-cost`  
**Timeline:** Week 9–11  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Cost Calculator | `spanforge-cost calc` | ✅ Core exists | 1d |
| Budget Monitor | `spanforge-cost budget` | ✅ Core exists | 1d |
| Cost Optimizer | `spanforge-cost optimize` | ❌ New | 1d |
| Pricing Explorer | `spanforge-cost prices` | ❌ New | 1d |
| Forecast Tool | `spanforge-cost forecast` | ❌ New | 1d |

**Deliverable:** `pip install spanforge-cost` working

---

#### Group 2D: Drift Detection (4 tools)
**Package:** `spanforge-drift`  
**Timeline:** Week 9–11  
**Effort:** 2–3 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Drift Detector | `spanforge-drift detect` | ✅ Core exists | 1d |
| Baseline Builder | `spanforge-drift baseline` | ✅ Core exists | 1d |
| Drift Reporter | `spanforge-drift report` | ❌ New | 1d |
| Retraining Trigger | `spanforge-drift retrain` | ❌ New | 1d |

**Deliverable:** `pip install spanforge-drift` working

---

#### Group 2E: Training Data (5 tools)
**Package:** `spanforge-training-data`  
**Timeline:** Week 11–12  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Training Data Scanner | `spanforge-training-data scan` | ✅ Core exists | 1d |
| Bias Detector | `spanforge-training-data bias` | ✅ Core exists | 1d |
| Data Lineage Tracker | `spanforge-training-data lineage` | ❌ New | 1d |
| Synthetic Data Detector | `spanforge-training-data synthetic` | ❌ New | 1d |
| Data Provenance | `spanforge-training-data provenance` | ❌ New | 1d |

**Deliverable:** `pip install spanforge-training-data` working

---

#### Group 2F: Governance (5 tools)
**Packages:** `spanforge-policy`, `spanforge-escalations`  
**Timeline:** Week 11–12  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Policy Designer | `spanforge-policy design` | ❌ New | 1d |
| Rule Engine Tester | `spanforge-policy test` | ❌ New | 1d |
| Escalation Manager | `spanforge-escalations list` | ❌ New | 1d |
| Escalation Approver | `spanforge-escalations approve` | ❌ New | 1d |
| Policy Diff | `spanforge-policy diff` | ❌ New | 1d |

**Deliverable:** Both packages working

---

#### Group 2G: Integration & Export (5 tools)
**Package:** `spanforge-export`  
**Timeline:** Week 11–12  
**Effort:** 3–4 weeks

| Tool | Command | Status | Effort |
|---|---|---|---|
| Datadog Exporter | `spanforge-export datadog` | ✅ Core exists | 1d |
| Splunk Forwarder | `spanforge-export splunk` | ✅ Core exists | 1d |
| Webhook Dispatcher | `spanforge-export webhook` | ✅ Core exists | 1d |
| Cloud Storage Sync | `spanforge-export s3` | ✅ Core exists | 1d |
| SIEM Integration | `spanforge-export siem` | ✅ Core exists | 1d |

**Deliverable:** `pip install spanforge-export` working

---

## D. PRODUCTS (11 revenue-generating products)

### PRIORITY: Tiered by revenue potential + GTM urgency

#### PHASE 1: Market Entry (Weeks 7–10)
**Goal:** Generate first revenue + validate PMF  
**Team:** Product + Backend + Frontend  

| Product | Type | Status | Effort | Timeline | Revenue Potential |
|---|---|---|---|---|---|
| **P2: Secrets & PII GitHub App** | SaaS (GitHub) | ❌ Partial | 4–6w | W7–10 | $720k–$960k ARR |
| **P8: SpanForge Cloud** | SaaS | ❌ Partial | 4–6w | W7–10 | $200k–$400k ARR |
| **P7: SpanForge India** | GTM only | ❌ Planning | 4–6w | W7–10 | INR 200k–500k/mo |

**Success Metrics by Week 10:**
- P2: 500 Team customers, $60k MRR
- P8: 100 Cloud customers, $50k MRR  
- P7: 5 SI partners signed
- **Phase 1 Total ARR: $1.4M**

---

#### PHASE 2: Product Depth (Weeks 11–30)
**Goal:** Expand market, validate core products  
**Team:** Product + Backend (parallel to Phase 1)  

| Product | Type | Status | Effort | Timeline | Revenue Potential |
|---|---|---|---|---|---|
| **P9: Training Data Scanner** | SaaS | 80% built | 2–3w | W11–20 | $100k–$200k ARR |
| **P3: Cost Intelligence** | SaaS | 60% built | 3–4w | W11–20 | $300k–$600k ARR |
| **P4: Audit Trail SaaS** | SaaS | 40% built | 4–5w | W11–20 | $200k–$400k ARR |
| **P5: Red Team SaaS** | SaaS | 60% built | 4–5w | W11–20 | $150k–$300k ARR |

**Success Metrics by Week 30:**
- First paying customers for P9, P3, P4, P5
- **Phase 2 Total ARR: +$750k = $2.2M combined**

---

#### PHASE 3: Enterprise Flagship (Weeks 31–60)
**Goal:** Lock in enterprise customers, maximize ARPU  
**Team:** Full team (product, engineering, sales)  

| Product | Type | Status | Effort | Timeline | Revenue Potential |
|---|---|---|---|---|---|
| **P1: Managed SaaS** | SaaS | 20% built | 8–10w | W31–50 | $5M–$10M ARR |
| **P6: Governance Dashboard** | SaaS | 30% built | 3–4w | W31–40 | $200k–$400k ARR |

**Success Metrics by Week 60:**
- 3–5 enterprise customers (P1)
- $100k MRR from P1 alone
- **Phase 3 Total ARR: +$5.5M = $7.7M combined**

---

#### PHASE 4: Channel & Scale (Weeks 61–90)
**Goal:** Partner distribution, maximize reach  

| Product | Type | Status | Effort | Timeline | Revenue Potential |
|---|---|---|---|---|---|
| **P10: Compliance API** | API | 50% built | 3–4w | W61–70 | $100k–$200k ARR |
| **P11: SI White-Label** | Channel | Sales-only | 2–3w | W61–70 | $300k–$600k ARR |

**Success Metrics by Week 90:**
- 10+ SI partners using white-label
- **Year 1 Total ARR: ~$3M baseline**

---

## E. ARTIFACTS & DOCUMENTATION

### PRIORITY: Build alongside products (not blocking)

#### Framework & Standard Documents (Weeks 1–6)

| Artifact | Type | Purpose | Status | Effort |
|---|---|---|---|---|
| RFC-0001 SPANFORGE | Open Standard | Compliance event schema | ✅ Live | — |
| Spanforge Way v5.0 | Framework | Governance methodology | ✅ Live | — |
| T.R.U.S.T. Framework v2.2 | Framework | 5 governance dimensions | ✅ Live | — |
| Exit Gate System™ | Framework | Lifecycle + gates | ✅ Live | — |
| CI/CD Gate Pipeline | Framework | 6 sequential gates | ✅ Live | — |

**Deliverable:** All frameworks documented + published

---

#### User Documentation (Weeks 1–20, ongoing)

| Doc | Type | Purpose | Status | Effort |
|---|---|---|---|---|
| Installation Guide | Guide | Setup + config | Partial | 2d |
| Quickstart (5-min) | Tutorial | First experience | Partial | 2d |
| CLI Reference (25 tools) | Reference | All CLI commands | ❌ New | 3d |
| Policy Writing Guide | Guide | How to write policies | Partial | 2d |
| Integration Examples | Examples | Per-integration | Partial | 2d |
| Troubleshooting | Guide | Common issues + fixes | Partial | 2d |
| API Reference | Reference | SDK methods | ✅ Auto-generated | — |
| Video Tutorials | Video | 3–5 min walkthroughs | ❌ New | 5d |

**Deliverable:** Complete documentation suite

---

#### Compliance & Legal (Weeks 1–20)

| Artifact | Type | Purpose | Status | Effort |
|---|---|---|---|---|
| Privacy Policy | Legal | GDPR/CCPA compliance | ❌ New | 1d |
| Terms of Service | Legal | Legal framework | ❌ New | 1d |
| Security Policy | Policy | Data handling + encryption | ✅ Partial | 1d |
| SOC 2 Compliance | Certification | For enterprise sales | ⚠️ In progress | 2w |
| ISO 27001 Roadmap | Roadmap | Security standard | ⚠️ Planning | 2w |

**Deliverable:** Enterprise-ready compliance docs

---

---

# PART II: COMPLETE TIMELINE & PRIORITIES

## WEEK-BY-WEEK EXECUTION PLAN

### WEEKS 1–6: SDK CORE + PRODUCT FOUNDATION

#### Week 1–2: GROUP 1A (8 CLI tools) + SDK Services Finalization
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng (CLI), 1 QA  
**Output:**
- ✅ 8 CLI tools finalized
- ✅ 20 SDK services polished
- ✅ All integrations tested
- ✅ All exporters tested

**Deliverable:** `spanforge` v1.0 beta ready

---

#### Week 2–3: GROUP 1B (7 CLI tools)
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng (CLI), 1 Security Eng  
**Output:**
- ✅ 7 CLI tools finalized
- ✅ CEC bundle production-ready
- ✅ Compliance mapping framework (hardcoded for Phase 1)

**Deliverable:** Audit + compliance tools ready

---

#### Week 3–4: GROUP 1C (6 CLI tools)
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng (CLI)  
**Output:**
- ✅ 6 CLI tools finalized
- ✅ Gate execution + scoring working
- ✅ Readiness scoring implemented

**Deliverable:** Policy + gate tools ready

---

#### Week 4–5: GROUP 1D (4 CLI tools) + Documentation Start
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng (CLI), 1 Tech Writer  
**Output:**
- ✅ 4 CLI tools finalized
- ✅ `spanforge config init` working
- ✅ `spanforge dev reset` creating clean environments
- ✅ Quick start documentation

**Deliverable:** Developer onboarding ready (<5 min setup)

---

#### Week 5–6: Integration + Testing + v1.0 Release
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng, 1 QA, 1 Tech Writer  
**Output:**
- ✅ E2E testing: all 25 tools + SDK + integrations
- ✅ Test coverage: >90%
- ✅ Full documentation (CLI reference + API docs)
- ✅ `spanforge` v1.0 released on PyPI
- ✅ GitHub repo public

**Deliverable:** **`spanforge` v1.0 production release**

---

### WEEKS 7–10: PRODUCT LAUNCHES (P2, P8, P7)

#### Week 7–8: P2 (GitHub App) + P8 (Cloud) Backend
**Priority:** 🔴 CRITICAL  
**Team:** 2 Backend Eng (parallel), 1 Frontend Eng  
**Output:**
- Backend service: FastAPI + PostgreSQL
- P2: GitHub OAuth + webhook handling
- P8: Event ingest + trace viewer API
- P7: SI partner portal backend

**Start:** Week 8–9 frontend UI work

---

#### Week 8–9: Frontend UIs for P2, P8, P7
**Priority:** 🔴 CRITICAL  
**Team:** 1 Frontend Eng (P2/P8), 1 Frontend Eng (P7)  
**Output:**
- P2 GitHub App dashboard + settings
- P8 trace viewer dashboard
- P7 partner onboarding portal

---

#### Week 9–10: Product Hardening + GTM
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng, 1 QA, 1 GTM/Product  
**Output:**
- All 3 products: security audit + performance testing
- P2: GitHub Marketplace listing + marketing
- P8: Landing page + pricing page
- P7: SI partner agreements signed
- **GO-LIVE:** P2, P8, P7

**Success Metrics:**
- P2: 500 Team customers, $60k MRR
- P8: 100 Cloud customers, $50k MRR
- P7: 5 SI partners + first revenue

**Deliverable:** **3 products live + generating revenue**

---

### WEEKS 11–12: STANDALONE CLI TOOLS (35 tools)

#### Week 11: Groups 2A, 2B, 2C (16 tools)
**Priority:** 🟡 HIGH  
**Team:** 2 Backend Eng (parallel)  
**Output:**
- `spanforge-debug` (6 tools)
- `spanforge-pii` + `spanforge-secrets` (5 tools)
- `spanforge-cost` (5 tools)

**Deliverable:** 16 tools on PyPI

---

#### Week 12: Groups 2D, 2E, 2F, 2G (19 tools)
**Priority:** 🟡 HIGH  
**Team:** 2 Backend Eng (parallel)  
**Output:**
- `spanforge-drift` (4 tools)
- `spanforge-training-data` (5 tools)
- `spanforge-policy` + `spanforge-escalations` (5 tools)
- `spanforge-export` (5 tools)

**Deliverable:** All 35 standalone tools on PyPI

---

### WEEKS 13–20: ENTERPRISE HARDENING (CORE-13 to CORE-22)

#### Week 13–14: CORE-13 + CORE-14 + CORE-15
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng, 1 Infrastructure Eng  
**Output:**
- CORE-13: Compliance Mapping Engine production-ready
- CORE-14: Cost Readiness Integration
- CORE-15: Workflow Engine finalization

---

#### Week 15–16: CORE-16 (Control/Data Plane)
**Priority:** 🔴 CRITICAL  
**Team:** 1 Infrastructure Eng, 1 Backend Eng  
**Effort:** 4–5 weeks (started Week 13, completes Week 16)  
**Output:**
- Control plane: registry, gates, workflow, compliance
- Data plane: enforcement, drift detection, audit
- One-directional updates working
- Architecture validated at scale

---

#### Week 17–18: CORE-17 (Event Streaming) + CORE-18 (Module Sandbox)
**Priority:** 🔴 CRITICAL  
**Team:** 1 Infrastructure Eng (CORE-17), 1 Security Eng (CORE-18)  
**Effort:** 4–6 weeks (started Week 15, completes Week 18)  
**Output:**
- Kafka/Pulsar deployment
- Producer: data plane → events
- Consumers: compliance mapper, drift detector, cost tracker
- Module sandbox: TRUSTED/MONITORED/UNTRUSTED

---

#### Week 19–20: CORE-19 + CORE-20 + CORE-21 + CORE-22
**Priority:** 🔴 CRITICAL  
**Team:** 1 Backend Eng (CORE-19/20), 1 QA Eng (CORE-21), 1 Engineering Lead (CORE-22)  
**Output:**
- Feature flags: progressive rollout working
- Developer experience: `@monitor()` decorator, improved errors
- Performance testing: 10k events/sec, 99.9% uptime
- All 10 production readiness gates passing

**Deliverable:** **Enterprise-grade infrastructure complete**

---

### WEEKS 21–30: EXPANDED PRODUCT SUITE (P1, P3–P6, P9)

#### Week 21–25: P1 (Managed SaaS) MVP
**Priority:** 🔴 CRITICAL  
**Team:** 2 Backend Eng, 2 Frontend Eng  
**Effort:** 8–10 weeks (started Week 13, MVP by Week 25)  
**Output:**
- Admin dashboard: customers, policies, gates
- Compliance dashboard: real-time status
- Audit trail: full logging
- Workflow engine UI: approvals
- Pricing: $2k–$15k/month tiers

---

#### Week 26–30: P3, P4, P5, P6 (Support Products)
**Priority:** 🟡 HIGH  
**Team:** 2 Backend Eng, 1 Frontend Eng  
**Output:**
- P3: Cost Intelligence Dashboard
- P4: Audit Trail SaaS
- P5: Red Team SaaS
- P6: Governance Dashboard
- All with landing pages + marketing

**Deliverable:** 4 products + P1 generating revenue

---

### WEEKS 31–60: SCALE & CHANNEL (P10, P11, P9)

#### Week 31–50: P1 Maturity + Sales Ramp
**Priority:** 🟡 HIGH  
**Team:** Sales, 1 Backend Eng (support)  
**Output:**
- Professional services revenue
- 3–5 enterprise customers
- $100k+ MRR
- Customer success playbook

---

#### Week 51–70: Channel Products (P10, P11)
**Priority:** 🟡 MEDIUM  
**Team:** 1 Backend Eng, 1 GTM  
**Output:**
- P10: Compliance API (REST endpoints)
- P11: SI White-Label program
- 10+ SI partners active

**Deliverable:** Channel revenue flowing

---

---

# PART III: PRIORITY MATRIX

## What Gets Built WHEN

### 🔴 CRITICAL PATH (MUST SHIP ON TIME)

| Week Range | Component | Why | If Late |
|---|---|---|---|
| W1–6 | 25 SDK CLI tools | All products depend on this | All products delayed |
| W1–6 | SDK services finalization | Core platform | All products blocked |
| W7–10 | P2 GitHub App | First revenue, market entry | Entire business plan at risk |
| W7–10 | P8 Cloud | Developer funnel | Entire business plan at risk |
| W7–10 | P7 India | Time-sensitive DPDP window | Lost market opportunity |
| W13–20 | Enterprise hardening (CORE-13 to 22) | EU AI Act enforcement (Aug 2) | Regulatory exposure |

---

### 🟡 HIGH PRIORITY (Ship weeks 7–20, OK to slip 1–2 weeks)

| Week Range | Component | Why | If Late |
|---|---|---|---|
| W11–12 | 35 standalone CLI tools | Developer acquisition | GTM momentum lost |
| W11–30 | P3, P4, P5, P6 | Product portfolio expansion | Revenue slower to scale |
| W21–30 | P1 MVP | Enterprise revenue | Series A at risk |

---

### 🟢 MEDIUM PRIORITY (Ship weeks 21–60, OK to slip 3–4 weeks)

| Week Range | Component | Why | If Late |
|---|---|---|---|
| W21–60 | P9, P10, P11 | Channel revenue | Series A still achievable |
| W1–20 | Web apps (except products) | Sales enablement | Can delay until Q3 |
| W1–20 | Documentation | Developer success | Can delay, catch up later |

---

### ⚪ OPTIONAL (If time permits, can push to Q4)

| Component | Why |
|---|---|
| P6 Governance Dashboard | Enterprise nice-to-have |
| Advanced compliance reporting | Can use basic version first |
| Advanced analytics | Can add in future releases |

---

---

# PART IV: TEAM ALLOCATION & RESOURCE PLAN

## Team Structure

### Core Engineering Team (2 FTE)

| Person | Role | Weeks 1–6 | Weeks 7–12 | Weeks 13–20 | Weeks 21–60 |
|---|---|---|---|---|---|
| Backend Eng #1 | SDK + CLI + Products | Group 1A+1B | P2 backend | CORE-15/17/19 | P1 backend |
| Backend Eng #2 | Integrations + Products | Group 1C+1D | P8 backend | CORE-16/18/20 | P3–P5 |

### Frontend Team (1–2 FTE, part-time Week 1–6)

| Person | Role | Weeks 1–6 | Weeks 7–20 | Weeks 21–60 |
|---|---|---|---|---|
| Frontend Eng #1 | Product UIs | Docs/help | P2+P8 UI | P1 UI |
| Frontend Eng #2 (part-time) | — | — | P7+P6 UI | P9–P11 UI |

### Product/GTM (1 FTE)

| Person | Role | Timeline | Output |
|---|---|---|---|
| Product Manager | Product vision + roadmap | W1–60 | 11 products shipped |
| GTM/Sales | Go-to-market + partnerships | W7–60 | Revenue targets hit |

### QA/DevOps (1 FTE)

| Person | Role | Timeline | Output |
|---|---|---|---|
| QA Engineer | Testing + documentation | W1–60 | >90% coverage, docs |
| DevOps Engineer | Infrastructure + deployment | W7–20 | Enterprise-ready infra |

---

---

# PART V: SUCCESS METRICS BY PHASE

## Phase 1 Success (Week 6)
- ✅ `spanforge` v1.0 released to PyPI
- ✅ 25 CLI tools production-ready
- ✅ >90% test coverage
- ✅ Full documentation complete

## Phase 2 Success (Week 10)
- ✅ P2: 500 Team customers, $60k MRR
- ✅ P8: 100 Cloud customers, $50k MRR
- ✅ P7: 5 SI partners signed
- ✅ **Total ARR: $1.4M**

## Phase 3 Success (Week 20)
- ✅ Enterprise hardening complete (CORE-13 to 22)
- ✅ 35 standalone CLI tools on PyPI
- ✅ 4 support products (P3, P4, P5, P6) shipping
- ✅ **Total ARR: $2.2M**

## Phase 4 Success (Week 60)
- ✅ P1 (Managed SaaS) shipping with 3–5 enterprise customers
- ✅ P10 (Compliance API) shipping
- ✅ P11 (SI White-Label) with 10+ partners
- ✅ **Total ARR: $3M+ baseline**

---

---

# APPENDIX: QUICK REFERENCE - WHAT GOES WHERE

## SDK (`/src/spanforge/`)
- ✅ 20 core services (Event, Trace, Span, etc)
- ✅ 12 integrations (OpenAI, LangChain, etc)
- ✅ 13 exporters (Datadog, Splunk, S3, etc)
- ✅ 25 CLI tools (Groups 1A–1D)
- ✅ Framework components (RFC-0001, Exit Gate, T.R.U.S.T., etc)

## Web Applications (`/web/` or `/apps/`)
- ✅ P2 UI: GitHub App dashboard + settings
- ✅ P8 UI: Trace viewer + cloud dashboard
- ✅ P7 UI: SI partner portal
- ✅ P1 UI: Admin dashboard + compliance
- ✅ P3 UI: Cost intelligence dashboard
- ✅ P4–P6 UIs: Audit trail, red team, governance
- ✅ P9–P11 UIs: Training data, API, white-label

## Standalone CLI Packages (`/src/spanforge-*` or `/cli/`)
- ✅ `spanforge-debug` (6 tools)
- ✅ `spanforge-pii` (5 tools)
- ✅ `spanforge-secrets` (part of above)
- ✅ `spanforge-cost` (5 tools)
- ✅ `spanforge-drift` (4 tools)
- ✅ `spanforge-training-data` (5 tools)
- ✅ `spanforge-policy` (5 tools)
- ✅ `spanforge-escalations` (part of above)
- ✅ `spanforge-export` (5 tools)

## Products (SaaS Services)
- ✅ P2: GitHub app (separate backend)
- ✅ P8: Cloud platform (separate backend + frontend)
- ✅ P7: India portal (configuration + GTM)
- ✅ P1: Managed SaaS (separate backend + enterprise UI)
- ✅ P3–P11: 9 additional SaaS products

## Documentation & Artifacts
- ✅ RFC-0001 standard
- ✅ Spanforge Way framework
- ✅ T.R.U.S.T. Framework
- ✅ CLI reference
- ✅ Quickstart guide
- ✅ Integration examples
- ✅ API reference
- ✅ Compliance docs

---

**Document Version:** 6.0 (Complete Master Build Plan)  
**Created:** May 1, 2026  
**Status:** READY FOR EXECUTION BY FULL TEAM
