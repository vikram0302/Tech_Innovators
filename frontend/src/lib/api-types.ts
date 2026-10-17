export type AuditRunStatus =
  | "planned"
  | "approved"
  | "running"
  | "completed"
  | "failed";

export type CheckStatus = "pass" | "fail" | "not_evaluable";
export type Severity = "low" | "medium" | "high";

export interface EvidenceRef {
  source_id: string;
  date?: string | null;
  excerpt: string;
}

export interface PlanRuleItem {
  rule_id: string;
  enabled: boolean;
  data_gaps: string[];
}

export interface AuditPlan {
  run_id: string;
  version: number;
  claim_number: string;
  objective?: string | null;
  rules: PlanRuleItem[];
  data_gaps_summary: string[];
}

export interface RunApproval {
  plan_version: number;
  approved_at: string;
  approved_by: string;
}

export interface RunSummary {
  run_id: string;
  claim_number: string;
  status: AuditRunStatus;
  plan_version: number;
  approval?: RunApproval | null;
  objective?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  finding_id: string;
  run_id: string;
  claim_number?: string | null;
  rule_id: string;
  severity: Severity;
  status: CheckStatus;
  observed_value?: string | null;
  expected_value?: string | null;
  evidence_refs: EvidenceRef[];
  explanation?: string | null;
  recommended_action?: string | null;
  assessment_type: "deterministic" | "ai_assessed";
}

export interface AuditEvent {
  event_id: string;
  run_id: string;
  step: string;
  message: string;
  status: string;
  created_at: string;
}

export interface EvidenceItem {
  source_id: string;
  date?: string | null;
  excerpt: string;
  rule_ids: string[];
}

export interface AuditSession {
  batch_id: string;
  dataset_id: string;
  regulation_set_id: string;
  claim_numbers: string[];
  status: AuditRunStatus;
  regulation_file_names: string[];
  dataset_file_names: string[];
  created_at: string;
  updated_at: string;
  finding_count: number;
  fail_count: number;
  has_report: boolean;
}
