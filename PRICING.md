# spanforge Pricing

spanforge is MIT-licensed open-source software. The core library is and always will be **free**.

The paid tiers described below are for **hosted services, commercial support, and enterprise add-ons** built on top of the open-source library.

---

## Tiers at a glance

| | **Community** | **Cloud** | **Cloud Team** | **Compliance** |
|---|---|---|---|---|
| **Price** | Free (MIT) | $29 / month flat | $99 / month flat | $299 / month flat |
| **License** | MIT | MIT + Cloud ToS | MIT + Cloud ToS | MIT + Enterprise Agreement |
| **Core SDK** | ✅ All features | ✅ All features | ✅ All features | ✅ All features |
| **HMAC signing** | ✅ | ✅ | ✅ | ✅ |
| **PII redaction** | ✅ | ✅ | ✅ | ✅ |
| **OTLP / Datadog / Grafana export** | ✅ | ✅ | ✅ | ✅ |
| **CloudExporter (hosted ingest)** | — | ✅ | ✅ | ✅ |
| **SPA Trace Viewer (`serve` / `ui`)** | ✅ (local) | ✅ (hosted dashboard) | ✅ (hosted dashboard) | ✅ (hosted dashboard) |
| **CLI tools** | ✅ | ✅ | ✅ | ✅ |
| **GitHub Issues support** | ✅ | ✅ | ✅ | ✅ |
| **Slack / Teams alerting** | ✅ (self-setup) | ✅ (self-setup) | ✅ (managed) | ✅ (managed) |
| **Redis cache backend** | ✅ (self-hosted) | ✅ (self-hosted) | ✅ (self-hosted) | ✅ |
| **Event retention** | Local only | 30 days, 100K events/month | 90 days, 1M events/month | 90 days, unlimited |
| **Shared workspaces** | — | — | ✅ | ✅ |
| **Email support SLA** | — | — | 48-hour | 4-hour |
| **Dedicated Slack channel** | — | — | — | ✅ |
| **Compliance evidence generation** | — | — | ✅ | ✅ |
| **HIPAA/SOC2 evidence + PDF export** | — | — | — | ✅ |
| **Model registry metadata in attestations** | — | — | ✅ | ✅ |
| **Explanation coverage metric** | — | — | ✅ | ✅ |
| **Signed chain verification API** | ✅ (CLI) | ✅ (CLI + SDK) | ✅ (CLI + SDK) | ✅ (CLI + SDK + API) |
| **Private vulnerability disclosure** | — | ✔ | ✅ | ✅ |
| **Security review / pen-test support** | — | — | — | ✅ |
| **Custom integrations** | — | — | — | ✅ |
| **Training & onboarding** | — | — | — | ✅ |
| **Air-gapped deployment support** | — | — | — | ✅ |

---

## Community (Free)

- Full MIT-licensed SDK — use in production, commercial projects, forks, anything
- 58-file test suite, 3,000+ tests, 90%+ coverage
- Local SPA trace viewer (`spanforge serve` / `spanforge ui`)
- GitHub Issues, GitHub Discussions, SECURITY.md responsible-disclosure
- No usage limits, no call-home, no API key required

---

## Cloud — $29 / month flat

Designed for **solo developers and small projects** who want hosted trace storage.

Includes everything in Community plus:
- **CloudExporter** — send events to hosted ingest with `exporter="cloud"`
- **Hosted trace viewer dashboard** with 30-day retention, 100K events/month
- **Priority GitHub issue triage** — your issues are labelled `cloud` and reviewed first

---

## Cloud Team — $99 / month flat

Designed for **startups and growing teams** who need shared workspaces and compliance.

Includes everything in Cloud plus:
- **90-day retention**, 1M events/month
- **Shared workspaces** for team collaboration
- **48-hour email support SLA**
- **Compliance evidence generation** (`spanforge compliance generate`)
- **Managed alerting configuration** — we help you hook up Slack / PagerDuty
- **Private vulnerability notifications** — 7-day advance notice before public CVE disclosure

To get started: email [team@getspanforge.com](mailto:team@getspanforge.com)

---

## Compliance — $299 / month flat

Designed for **regulated industries, large teams, and air-gapped deployments**.

Includes everything in Cloud Team plus:
- **4-hour support SLA** with dedicated Slack channel
- **HIPAA/SOC 2 evidence packages** generated from spanforge audit events, with PDF export
- **Signed chain verification API**
- **Air-gapped deployment support** — signed wheel distribution, no PyPI required
- **Custom integration development** — proprietary LLM providers, internal exporters
- **Security review participation** — we join your pen-test team’s debriefs
- **Training & onboarding** — live sessions for your engineering team

To get started: email [enterprise@getspanforge.com](mailto:enterprise@getspanforge.com)

---

## FAQ

**Is the SDK source code ever gated behind a paid tier?**
No. The entire SDK is MIT-licensed and publicly available on GitHub. Paid tiers cover services, support, and SLAs — not code access.

**Can I self-host everything on the Enterprise tier?**
Yes. All spanforge components run entirely on your infrastructure. There is no required cloud service.

**What happens to my data?**
spanforge never transmits your events anywhere without your explicit configuration. If you use `exporter="console"` or `exporter="jsonl"`, data stays entirely on your machine.

**Can I upgrade from Community to Cloud mid-year?**
Yes — contact [team@getspanforge.com](mailto:team@getspanforge.com).

**Is there a discount for non-profits or academic institutions?**
Yes — 50% discount for verified non-profits and academic organisations. Contact us.

---

*Pricing is subject to change. Existing subscribers are grandfathered for 12 months after any price change.*
