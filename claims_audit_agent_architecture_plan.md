# Claims Audit Agent: Detailed Architecture Plan
*Google hackathon build: one agent, one workflow, evidence-backed findings*


## 1. Purpose and Scope
The Claims Audit Agent reviews a closed or open insurance claim file against the organization's Claims Handling Standards and produces a findings report that a human reviewer can trust. Every finding must point back to the source note or communication entry that supports it.
In scope for the hackathon (MVP)
- One agent, one workflow: audit a single claim by claim number.
- Inputs: adjuster notes, communication logs, reference data, and the Claims Handling Standards.
- Deterministic rule checks plus a small set of LLM judgment checks.
- Human approval of the audit plan before execution.
- A findings table with evidence, a severity score, and a downloadable report.
Out of scope for the MVP
- Multi-agent specializations, multi-jurisdiction rule packs, enterprise identity and roles, vector search infrastructure, and worker queues.
## 2. Design Principles
- Deterministic code decides, the model explains. Any pass/fail outcome that can be computed from dates, counts, or field presence is computed in Python. Gemini never overrides a computed result.
- Every finding is grounded. A finding without a source reference (note date, entry type, and text span) is rejected by the system.
- Unknown is not a pass. If the data needed to evaluate a rule is missing, the result is "not evaluable", and that is itself surfaced to the reviewer.
- Human in the loop, enforced on the backend. The execute endpoint refuses to run an unapproved plan, regardless of what the frontend sends.
- Small and demo-ready. Prefer fewer moving parts that work end to end over broad features that half work.
## 3. System Overview
Request path: Reviewer in the Next.js UI, then the FastAPI backend, then the ADK Claims Audit Agent, which calls its tools (data loader, rule engine, judgment checker, report builder) and Gemini, then Firestore for storage, then results stream back to the UI.
Layers
- Presentation: Next.js, React, TypeScript, Tailwind CSS, and shadcn/ui. Screens for claim selection, plan review, run progress, findings with evidence, and report download.
- API: FastAPI with REST endpoints and Server-Sent Events (SSE) for progress. Owns validation, approval enforcement, and run state.
- Agent: Google ADK root agent running a fixed audit procedure, with Gemini as the model for planning, judgment checks, and explanations.
- Audit logic: Python and Pandas modules for the deterministic rule engine and the evidence builder.
- Persistence: Firestore for runs, plans, approvals, findings, evidence, and events. Cloud Storage only if uploads are needed.
- Deployment: Cloud Run for both services, Secret Manager for credentials, GitHub for source.
The ADK API names used below (agents, tools, sessions, tool confirmation) come from my knowledge of ADK; verify them against the current documentation on day one.
## 4. Agent Design
### 4.1 Shape of the agent
One root agent, the Claims Audit Agent, with a fixed procedure encoded in its instructions and enforced by the tools it is allowed to call. The steps run in strict order, so the procedure can be expressed as a sequential workflow (ADK offers workflow agents for this) or as one agent with a tightly scripted instruction. Choose whichever is faster to get working; the behavior is the same.
Procedure
## 5. Load: fetch the claim's notes, communication logs, and reference data.
2. Plan: produce a structured audit plan listing the rules to run, the data each rule needs, and any data gaps already visible.
## 7. Approve: pause for human approval or edits.
## 8. Check (deterministic): run the rule engine and record raw outcomes.
## 9. Check (judgment): run the LLM judgment checks against the notes and logs.
## 10. Synthesize: merge results, deduplicate, assign severity, and attach evidence.
7. Explain and report: Gemini writes plain-language explanations of the recorded outcomes; the report builder assembles the final document.
### 4.2 Tools exposed to the agent
- load_claim(claim_number): returns the normalized claim object (section 5.1).
- get_rule_catalog(): returns the active rule definitions.
- propose_plan(claim): returns a plan validated against the plan schema.
- run_deterministic_checks(claim, rule_ids): returns a list of check results.
- run_judgment_check(claim, check_id): calls Gemini with structured output and returns a validated result.
- build_findings(results): converts results into findings with evidence and severity.
- build_report(run_id): renders the report from stored findings.
The agent can only call these tools. It has no free-form database or file access.
### 4.3 State
Session state holds the run ID, claim number, approved plan version, raw check results, and findings. State is mirrored to Firestore at each step so a run can be resumed or inspected after the fact.
## 12. Data Model
### 5.1 Normalized claim object
The loader converts the raw files into one consistent structure so the rule engine never parses raw JSON.
- claim_number
- timeline: a single list of events merged from adjuster notes and communication logs, each with event_id, source (note or communication), date, adjuster, type, and text, sorted by date with the original order preserved for chronology checks.
- notes: the adjuster note entries, each with a stable ID such as N1, N2.
- communications: the communication log entries, each with a stable ID such as C1, C2.
- reference: values from the reference data workbook (the exact fields depend on the workbook contents, so confirm its columns before building the loader).
- derived: computed fields such as claim open date, close date, and days open.
Stable IDs matter: every finding cites them, and the UI links evidence by ID.
### 5.2 Rule definition (rule catalog entry)
- rule_id, for example COM-02
- standard_section: the section of the Claims Handling Standards it comes from
- title and description
- type: deterministic or judgment
- required_inputs: which fields it needs
- threshold: for example 48 hours
- severity_if_failed: low, medium, high
- remediation: recommended action text
The catalog lives in a YAML or JSON file in the repository, not in a database, so it is versionable and easy to review.
### 5.3 Check result and finding
- Check result: rule_id, status (pass, fail, not_evaluable), observed_value, expected_value, evidence_refs, computed_at.
- Finding: finding_id, run_id, rule_id, severity, status, observed_value, expected_value, evidence_refs, explanation (model-written, based only on the recorded result), recommended_action.
- Evidence reference: source_id (such as N3), date, and an exact quoted excerpt copied from the source.
## 13. Rule Catalog (MVP)
Rules are grouped by the sections of the Claims Handling Standards. IDs are proposals; adjust as needed.
### 6.1 Deterministic rules
- SET-01 Acknowledgment (Section 1): claim acknowledged within 24 hours of receipt. Needs a receipt timestamp and an acknowledgment event. If the receipt time is not recorded, the result is not_evaluable.
- COM-01 Initial contact (Section 2): assigned adjuster contacts the claimant within 48 hours.
- COM-02 Ongoing updates (Section 2): no gap longer than 14 days between claimant updates while the claim is open.
- COM-03 Documentation (Section 2): each communication is reflected in the claim notes with date and a summary.
- INV-01 Investigation time (Section 3): investigation completed within 30 days, unless an extenuating reason is documented.
- RES-01 Initial reserve (Section 4): an initial reserve is documented at first notice.
- RES-02 Reserve review (Section 4): reserve reviewed at least every 60 days, with justification for any change.
- DOC-01 Chronological notes (Section 6): notes appear in date order.
- DOC-02 Final report (Section 6): a final report exists once the claim is resolved.
- FRD-01 SIU referral documented (Section 9): if a fraud indicator is flagged, a referral or a documented decision not to refer exists.
### 6.2 Judgment rules (Gemini, structured output)
- INV-02 Investigation thoroughness (Section 3): were statements, photos, and relevant documents gathered, or were requested items never followed up?
- INV-03 Liability support (Section 3): is the liability conclusion supported by the evidence recorded in the notes?
- DOC-03 Consistency (Section 6): do the notes and communication logs contradict each other on dates or facts?
- FRD-02 Red flags (Section 9): do the notes contain indicators that should have triggered an SIU review?
- LIT-01 Litigation potential (Section 8): was litigation potential identified early where the facts suggest it?
### 6.3 Handling of rules that need data we do not have
Several standards (reserves, settlement authority, regulatory reporting) depend on fields that may not exist in the sample data. The rule engine returns not_evaluable with a reason, and the report shows these in a separate "Data gaps" section. This is honest, and it demonstrates the audit value of the missing documentation itself.
## 14. Deterministic Engine Details
- Date handling: parse all dates to UTC dates. The sample data has dates only (no times), so 24-hour and 48-hour rules are evaluated at day granularity and labeled as such. State this limitation in the finding.
- Anchor events: receipt date comes from the earliest note or the reference data if present; close date comes from the final assessment note or closure communication.
- Gap calculation: sort the timeline, compute day differences between consecutive claimant-facing communications, and flag any gap over the threshold while the claim is open.
- Determinism guarantee: the engine has no randomness and no model calls. The same input always produces the same output, and this is covered by unit tests.
- Result recording: write raw results to storage before any explanation step runs.
## 15. Judgment Checks with Gemini
- Structured output: each check has a response schema (for example, verdict, confidence, evidence_refs, rationale) enforced through Gemini's structured output feature and validated with Pydantic. Invalid output is retried once, then marked failed.
- Grounding: the prompt provides the timeline with stable IDs and instructs the model to cite only those IDs.
- Programmatic verification: after the call, code checks that every cited ID exists and that each quoted excerpt actually appears in that source. Findings that fail verification are dropped or flagged for review.
- Low variance: use a low temperature and a fixed prompt version stored with the run.
- Separation: judgment findings are labeled "AI-assessed" in the UI and report, so reviewers can tell them apart from deterministic findings.
- Explanations: a separate call turns recorded results into plain-language text. The prompt forbids introducing facts that are not in the recorded result.
## 16. Human Approval Flow
- The plan is persisted as a versioned object. The reviewer can approve it as is or remove or add optional checks.
- Approval is recorded against a specific plan version with a timestamp and user identifier.
- POST /execute checks the stored approval for the current plan version and rejects the request otherwise.
- If the reviewer edits the plan, the version increments and the earlier approval no longer applies.
- Within ADK, the pause can use the framework's tool confirmation mechanism or a simple two-request pattern (plan request, then execute request) at the API layer. The two-request pattern is simpler and is the safer fallback.
## 17. API Design (FastAPI)
- POST /api/audits/plan: body with claim number and optional objective; creates a run and returns the plan.
- POST /api/audits/{run_id}/approve: records approval for the given plan version.
- POST /api/audits/{run_id}/execute: starts execution if approved.
- GET /api/audits/{run_id}: status, plan summary, findings.
- GET /api/audits/{run_id}/events: SSE stream of step status.
- GET /api/audits/{run_id}/evidence: evidence list with source excerpts.
- GET /api/audits/{run_id}/report: generated report (PDF or Markdown).
- GET /health: health check.
All request and response bodies use Pydantic models. The frontend types are generated from, or mirrored against, the same schemas.
## 18. Frontend Plan (Next.js)
- Claim selection and objective: pick a claim number from the loaded dataset and add an optional objective.
- Plan review: a checklist of rules grouped by standard section, each marked deterministic or AI-assessed, with Approve and Edit actions.
- Run progress: a step list or simple stepper driven by SSE (load, deterministic checks, judgment checks, synthesis, report). A React Flow canvas is optional polish.
- Findings: a table sorted by severity with rule, status, observed versus expected, and an evidence panel that shows the exact source excerpt and its date.
- Data gaps: a separate list of not_evaluable rules and what data would resolve them.
- Report: summary counts by severity, plus a download button.
Keep it to one main page with tabs. A working end-to-end flow is worth more than extra screens.
## 19. Persistence (Firestore)
- audit_runs: run ID, claim number, status, plan version, approval, prompt and rule catalog versions, timestamps.
- audit_plans: run ID, version, plan content.
- audit_results: raw check results, written before explanations.
- audit_findings: findings with evidence references.
- audit_events: step events for the SSE stream and later inspection.
If the team prefers a different store, SQLite or MongoDB would also work; Firestore is suggested because it fits Google Cloud and needs little setup.
## 20. Deployment
- Two Cloud Run services: audit-api (FastAPI and ADK agent) and audit-web (Next.js).
- Gemini access and any other credentials come from Secret Manager or Cloud Run environment configuration, never from the browser or the repository.
- Service-to-service access uses the API base URL from an environment variable; restrict CORS to the frontend origin.
- SSE on Cloud Run: set a request timeout long enough for a full run, and confirm streaming works through the deployed URL early, not on demo day.
- Repository layout follows the existing plan: frontend/, backend/ (api, agent, rules, judgment, evidence, reports, db), sample_data/, docs/, .env.example, and a README with setup steps.
## 21. Security and Guardrails
- All model calls happen in the backend; credentials never reach the browser.
- Validate uploads and inputs: file type, size, and schema. Claim files contain personal information, so keep logs free of raw claimant data and store only what is needed.
- Prompt injection: claim notes are untrusted text. Prompts treat them as data, outputs are schema-validated, and the agent can only call a fixed set of tools, so injected instructions cannot change behavior beyond the allowed procedure.
- Enforce approval and access checks on the backend.
- Use least-privilege service accounts and HTTPS only.
- Privacy: the standards reference confidentiality requirements, so for the demo use only the sample or anonymized data.
## 22. Testing and Evaluation
- Unit tests for every deterministic rule, using small hand-built timelines that pass, fail, and are not evaluable.
- Golden claim: the sample claim VAPJPAS086739 with expected findings recorded in advance.
- Seeded defects: create two or three synthetic variants of the sample claim (late first contact, 45-day investigation, missing final assessment) and confirm each is caught. This also makes a strong demo.
- Judgment check evaluation: run each judgment check several times on the same input and measure agreement; verify citation validity automatically.
- Clean-session smoke test: run the full workflow in a fresh browser against the deployed URL before the demo.
## 23. Worked Example: Claim VAPJPAS086739
Deterministic
- COM-01: first notes entry 2024-01-29, first contact 2024-01-30, within 48 hours (pass, at day granularity).
- INV-01: received 2024-01-29, closed 2024-02-08, about 10 days, within the 30-day limit (pass).
- COM-02: claim closed within 10 days, so the 14-day update gap rule is not triggered.
- SET-01: no receipt timestamp is recorded, so the 24-hour acknowledgment is not_evaluable.
- RES-01 and RES-02: no reserve documented in the notes (fail or not_evaluable depending on reference data).
- DOC-02: no final report beyond the closing note (fail).
Judgment
- DOC-03: the adjuster note dated 2024-02-01 says the police report was obtained, while the communication log shows the report was requested on 2024-02-01 and received on 2024-02-05. This is a date discrepancy to surface.
- INV-02: photos and videos were requested from the city on 2024-02-01 and never mentioned again.
- INV-03: the "other driver at fault" conclusion rests on the police report and driver statements; no independent witnesses were identified, and the other driver's contrary claim was set aside because the police report did not corroborate it. The reviewer should decide whether that is sufficient.
## 24. Four-Day Plan
- Day 1: rule catalog, normalized claim loader, deterministic engine with unit tests, ADK agent skeleton calling the tools, sample data wired in.
- Day 2: judgment checks with structured output and citation verification, plan and approval endpoints, findings storage, basic Next.js page with findings and evidence panel.
- Day 3: Cloud Run deployment, Firestore, SSE progress, report generation, seeded defect claims, README.
- Day 4: bug fixes, feature freeze, demo rehearsal and recording, pitch deck, submission checklist.
If time is tight, cut in this order: React Flow canvas, SSE (fall back to polling), report PDF (fall back to Markdown), then individual judgment checks. Never cut the approval gate, the evidence links, or the deterministic engine.
## 25. Risks and Open Questions
- ADK familiarity: confirm API details on day one; keep a fallback of plain Python orchestration with Gemini calls if ADK blocks progress.
- Reference data contents: the reference workbook's columns determine which reserve and authority rules can be evaluated; inspect it before finalizing the catalog.
- Date-only data: hour-level rules cannot be checked precisely; decide how to present that to judges.
- One claim is a thin dataset: add a few synthetic claims so the demo shows more than one outcome.
- Model variance: keep judgment checks few and well-grounded rather than many and noisy.
