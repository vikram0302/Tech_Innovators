import type { AuditEvent, AuditSession, Finding } from "./api-types";

// Same-origin /api/* is proxied to the FastAPI backend via next.config rewrites.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function getActiveRegulations() {
  return request<{
    active: boolean;
    regulation_set_id?: string;
    files?: string[];
  }>("/api/regulations/active");
}

export async function uploadRegulations(files: FileList | File[]) {
  const form = new FormData();
  for (const f of Array.from(files)) form.append("files", f);
  const res = await fetch(`${API_URL}/api/regulations/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function regulationFilePreviewUrl(filename: string) {
  return `${API_URL}/api/regulations/active/files/${encodeURIComponent(filename)}`;
}

export async function removeRegulationFile(filename: string) {
  return request<{
    active: boolean;
    regulation_set_id?: string | null;
    files?: string[];
  }>(`/api/regulations/active/files/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export async function getActiveDataset() {
  return request<{
    active: boolean;
    dataset_id?: string;
    claim_numbers?: string[];
    source_files?: string[];
  }>("/api/dataset/active");
}

export async function uploadDataset(files: {
  adjuster_notes: File;
  communication_logs: File;
  reference: File;
}) {
  const form = new FormData();
  form.append("adjuster_notes", files.adjuster_notes);
  form.append("communication_logs", files.communication_logs);
  form.append("reference", files.reference);
  const res = await fetch(`${API_URL}/api/dataset/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{
    dataset_id: string;
    claim_numbers: string[];
    source_files?: string[];
  }>;
}

export async function createBatchPlan(dataset_id: string, regulation_set_id?: string) {
  return request<{ batch: { batch_id: string; claim_numbers: string[] } }>(
    "/api/batch/plan",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id, regulation_set_id }),
    },
  );
}

export async function approveBatch(batch_id: string) {
  return request(`/api/batch/${batch_id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_version: 1 }),
  });
}

export async function executeBatch(batch_id: string) {
  return request<{ batch_id: string; status: string }>(
    `/api/batch/${batch_id}/execute`,
    { method: "POST" },
  );
}

export async function listAuditSessions() {
  return request<{ sessions: AuditSession[] }>("/api/batch");
}

export async function getBatch(batch_id: string) {
  return request<{
    batch: {
      status: string;
      dataset_id: string;
      regulation_set_id: string;
      claim_numbers?: string[];
      regulation_file_names: string[];
      dataset_file_names: string[];
    };
    findings: Finding[];
    events?: AuditEvent[];
  }>(`/api/batch/${batch_id}`);
}

export function batchReportUrl(batch_id: string) {
  return `${API_URL}/api/batch/${batch_id}/report`;
}

export function subscribeBatchEvents(
  batch_id: string,
  onEvent: (event: AuditEvent) => void,
): EventSource {
  const es = new EventSource(`${API_URL}/api/batch/${batch_id}/events`);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as AuditEvent);
    } catch {
      /* ignore */
    }
  };
  return es;
}

export async function sendChat(
  message: string,
  planning_mode: boolean,
  dataset_id?: string,
) {
  return request<{
    reply: string;
    batch_id?: string;
    actions?: { type: string; batch_id?: string }[];
  }>("/api/chat/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, planning_mode, dataset_id }),
  });
}
