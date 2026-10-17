"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { AuditEvent, AuditSession, Finding } from "@/lib/api-types";
import {
  approveBatch,
  batchReportUrl,
  executeBatch,
  getActiveDataset,
  getActiveRegulations,
  getBatch,
  listAuditSessions,
  sendChat,
  subscribeBatchEvents,
  uploadDataset,
} from "@/lib/api";

type ChatMsg = { role: "user" | "assistant"; text: string };

/** Keep first occurrence order; latest event wins per step (running → completed). */
function collapseEventsByStep(events: AuditEvent[]): AuditEvent[] {
  const order: string[] = [];
  const byStep = new Map<string, AuditEvent>();
  for (const e of events) {
    if (!byStep.has(e.step)) order.push(e.step);
    byStep.set(e.step, e);
  }
  return order.map((step) => byStep.get(step)!);
}

function upsertEvent(prev: AuditEvent[], ev: AuditEvent): AuditEvent[] {
  const idx = prev.findIndex((e) => e.step === ev.step);
  if (idx < 0) return [...prev, ev];
  const next = [...prev];
  next[idx] = ev;
  return next;
}

function statusBadgeVariant(
  status: string,
): "default" | "success" | "warn" | "danger" | "muted" {
  if (status === "completed") return "success";
  if (status === "running") return "warn";
  if (status === "failed") return "danger";
  if (status === "planned" || status === "pending") return "muted";
  return "default";
}

function computeProgress(events: AuditEvent[], reportReady: boolean): number {
  if (
    reportReady ||
    events.some((e) => e.step === "batch_complete" && e.status === "completed")
  ) {
    return 100;
  }
  const latest = collapseEventsByStep(events);
  if (!latest.length) return 0;
  const done = latest.filter((e) => e.status === "completed").length;
  return Math.round((done / latest.length) * 100);
}

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function AuditPage() {
  const [regsOk, setRegsOk] = useState(false);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [claimCount, setClaimCount] = useState(0);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [pendingApproval, setPendingApproval] = useState(false);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [reportReady, setReportReady] = useState(false);
  const [sessions, setSessions] = useState<AuditSession[]>([]);
  const [dataSources, setDataSources] = useState<{
    claims: string[];
    regulations: string[];
  }>({ claims: [], regulations: [] });
  const [planningMode, setPlanningMode] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      role: "assistant",
      text: "Upload claims data for a new session, then Send to start the audit. Prior audit logs stay in History with their data sources.",
    },
  ]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState({
    notes: false,
    comms: false,
    ref: false,
  });
  const eventSourceRef = useRef<EventSource | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await listAuditSessions();
      setSessions(data.sessions);
    } catch {
      /* API may be down briefly */
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    const reg = await getActiveRegulations();
    setRegsOk(reg.active);
    setDataSources((prev) => ({
      ...prev,
      regulations: reg.files ?? [],
    }));
    const ds = await getActiveDataset();
    if (ds.active && ds.dataset_id) {
      setDatasetId(ds.dataset_id);
      setClaimCount(ds.claim_numbers?.length ?? 0);
      setUpload({ notes: true, comms: true, ref: true });
      setDataSources((prev) => ({
        claims: ds.source_files ?? prev.claims,
        regulations: prev.regulations.length ? prev.regulations : (reg.files ?? []),
      }));
    }
  }, []);

  useEffect(() => {
    refreshStatus().catch(() => undefined);
    refreshSessions().catch(() => undefined);
    return () => {
      eventSourceRef.current?.close();
    };
  }, [refreshStatus, refreshSessions]);

  const resetCurrentSession = useCallback(() => {
    eventSourceRef.current?.close();
    setBatchId(null);
    setPendingApproval(false);
    setEvents([]);
    setFindings([]);
    setReportReady(false);
  }, []);

  const handleBatchEvent = useCallback(
    (bid: string, ev: AuditEvent) => {
      setEvents((prev) => upsertEvent(prev, ev));
      if (ev.step === "batch_complete" && ev.status === "completed") {
        getBatch(bid).then((data) => {
          setFindings(data.findings);
          setEvents(collapseEventsByStep(data.events ?? []));
          setReportReady(true);
          setDataSources({
            claims: data.batch.dataset_file_names ?? [],
            regulations: data.batch.regulation_file_names ?? [],
          });
          refreshSessions();
        });
      }
    },
    [refreshSessions],
  );

  const showPlanInTaskPanel = useCallback(async (bid: string) => {
    const data = await getBatch(bid);
    setBatchId(bid);
    setClaimCount(data.batch.claim_numbers?.length ?? 0);
    setEvents(collapseEventsByStep(data.events ?? []));
    setFindings([]);
    setReportReady(false);
    setDataSources({
      claims: data.batch.dataset_file_names ?? [],
      regulations: data.batch.regulation_file_names ?? [],
    });
  }, []);

  const runBatchExecution = useCallback(
    async (bid: string) => {
      eventSourceRef.current?.close();
      setFindings([]);
      setReportReady(false);
      setPendingApproval(false);
      setBatchId(bid);

      // Keep planned steps visible; SSE will upgrade planned → running → completed.
      try {
        const data = await getBatch(bid);
        setEvents(collapseEventsByStep(data.events ?? []));
      } catch {
        setEvents([]);
      }

      eventSourceRef.current = subscribeBatchEvents(bid, (ev) =>
        handleBatchEvent(bid, ev),
      );
      await executeBatch(bid);
    },
    [handleBatchEvent],
  );

  const loadSession = async (session: AuditSession) => {
    setBusy(true);
    setError(null);
    eventSourceRef.current?.close();
    try {
      const data = await getBatch(session.batch_id);
      setBatchId(session.batch_id);
      setDatasetId(session.dataset_id);
      setClaimCount(session.claim_numbers.length);
      setEvents(collapseEventsByStep(data.events ?? []));
      setFindings(data.findings ?? []);
      setReportReady(session.has_report || session.status === "completed");
      setPendingApproval(false);
      setDataSources({
        claims: session.dataset_file_names ?? [],
        regulations: session.regulation_file_names ?? [],
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onApproveAndStart = async () => {
    if (!batchId) return;
    setBusy(true);
    setError(null);
    try {
      await approveBatch(batchId);
      await runBatchExecution(batchId);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: "Plan approved. Audit is running — follow progress in the Task Panel.",
        },
      ]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onClaimsUpload = async (kind: "notes" | "comms" | "ref", file: File) => {
    setError(null);
    const stash =
      (window as unknown as { __claimsUploadFiles?: Record<string, File> }).__claimsUploadFiles ??
      {};
    if (kind === "notes") stash.adjuster_notes = file;
    if (kind === "comms") stash.communication_logs = file;
    if (kind === "ref") stash.reference = file;
    (window as unknown as { __claimsUploadFiles: Record<string, File> }).__claimsUploadFiles =
      stash;
    setUpload((u) => ({
      ...u,
      notes: kind === "notes" ? true : u.notes,
      comms: kind === "comms" ? true : u.comms,
      ref: kind === "ref" ? true : u.ref,
    }));
    if (stash.adjuster_notes && stash.communication_logs && stash.reference) {
      if (!regsOk) {
        setError("Upload regulations first (Regulations tab).");
        return;
      }
      setBusy(true);
      try {
        const result = await uploadDataset({
          adjuster_notes: stash.adjuster_notes,
          communication_logs: stash.communication_logs,
          reference: stash.reference,
        });
        resetCurrentSession();
        setDatasetId(result.dataset_id);
        setClaimCount(result.claim_numbers.length);
        setDataSources((prev) => ({
          claims: result.source_files ?? [
            "adjuster_notes.json",
            "communication_logs.json",
            "reference.xlsx",
          ],
          regulations: prev.regulations,
        }));
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            text: `New session started with fresh claims data (${result.claim_numbers.length} claim(s)). Prior audits remain in History. Send a message when ready to audit.`,
          },
        ]);
        await refreshSessions();
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    }
  };

  const onSendChat = async () => {
    if (!chatInput.trim()) return;
    if (!datasetId) {
      setError("Upload all three claims files before sending.");
      return;
    }
    const text = chatInput.trim();
    setMessages((m) => [...m, { role: "user", text }]);
    setChatInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await sendChat(text, planningMode, datasetId);
      setMessages((m) => [...m, { role: "assistant", text: res.reply }]);

      const action = res.actions?.[0];
      if (res.batch_id && action?.type === "batch_planned") {
        setPendingApproval(true);
        await showPlanInTaskPanel(res.batch_id);
        await refreshSessions();
      } else if (res.batch_id && action?.type === "batch_ready_to_execute") {
        await runBatchExecution(res.batch_id);
        await refreshSessions();
      } else if (res.batch_id) {
        await showPlanInTaskPanel(res.batch_id);
        await refreshSessions();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const taskEvents = collapseEventsByStep(events);
  const pct = computeProgress(events, reportReady);
  const isComplete = pct === 100;
  const phaseLabel = pendingApproval
    ? "Planning"
    : busy && !reportReady && batchId
      ? "Executing"
      : reportReady || isComplete
        ? "Completed"
        : taskEvents.some((e) => e.status === "running")
          ? "Executing"
          : taskEvents.some((e) => e.status === "planned")
            ? "Planning"
            : "Idle";

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-57px)]">
        <section className="flex w-[45%] flex-col border-r border-slate-200 bg-white">
          <div className="border-b px-4 py-2 text-sm font-medium">Audit Agent</div>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.map((m, i) => (
              <div
                key={i}
                className={`rounded-lg p-3 text-sm ${
                  m.role === "user" ? "ml-8 bg-emerald-50" : "mr-8 bg-slate-50"
                }`}
              >
                {m.text}
              </div>
            ))}
          </div>
          <div className="border-t p-4">
            <p className="mb-2 text-xs font-medium text-slate-500">
              Claims data (new upload = new session)
            </p>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              <FileChip label="Adjuster notes" done={upload.notes} kind="notes" onFile={onClaimsUpload} />
              <FileChip label="Communication logs" done={upload.comms} kind="comms" onFile={onClaimsUpload} />
              <FileChip label="Reference workbook" done={upload.ref} kind="ref" onFile={onClaimsUpload} />
            </div>
            {(dataSources.claims.length > 0 || dataSources.regulations.length > 0) && (
              <div className="mb-3 rounded border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-600">
                <p>
                  <span className="font-medium text-slate-700">Claims sources:</span>{" "}
                  {dataSources.claims.join(", ") || "—"}
                </p>
                <p className="mt-1">
                  <span className="font-medium text-slate-700">Regulation sources:</span>{" "}
                  {dataSources.regulations.join(", ") || "—"}
                </p>
              </div>
            )}
            {!regsOk && (
              <p className="mb-2 text-xs text-amber-700">Regulations not loaded — use Regulations tab first.</p>
            )}
            <label className="mb-2 flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={planningMode}
                onChange={(e) => setPlanningMode(e.target.checked)}
              />
              Planning Mode
            </label>
            {pendingApproval && batchId && (
              <Button
                className="mb-2 w-full bg-emerald-600 hover:bg-emerald-700"
                disabled={busy}
                onClick={onApproveAndStart}
              >
                Approve &amp; Start audit
              </Button>
            )}
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-md border px-2 py-2 text-sm"
                placeholder="Ask the agent to audit all claims…"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !busy && onSendChat()}
                disabled={busy}
              />
              <Button disabled={busy || !datasetId} onClick={onSendChat}>
                Send
              </Button>
            </div>
          </div>
        </section>
        <section className="flex w-[55%] flex-col bg-slate-100">
          <div className="flex items-center justify-between border-b bg-white px-4 py-2 text-sm font-medium">
            <span>Task Panel</span>
            <Badge
              variant={
                phaseLabel === "Completed"
                  ? "success"
                  : phaseLabel === "Executing"
                    ? "warn"
                    : phaseLabel === "Planning"
                      ? "default"
                      : "muted"
              }
            >
              {phaseLabel}
            </Badge>
          </div>
          {error && <p className="m-4 rounded bg-red-50 p-2 text-xs text-red-800">{error}</p>}
          <div className="p-4">
            <div className="mb-2 flex justify-between text-xs text-slate-600">
              <span>
                {isComplete ? "100% completed" : `${pct}% completed`}
                {isComplete && (
                  <Badge variant="success" className="ml-2">
                    Completed
                  </Badge>
                )}
              </span>
              <span>
                {claimCount} claims · batch {batchId?.slice(0, 8) ?? "—"}
              </span>
            </div>
            <div className="h-2 rounded-full bg-slate-200">
              <div
                className="h-2 rounded-full bg-emerald-500 transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-3 text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {pendingApproval ? "Planned steps (awaiting approval)" : "Live plan & execution"}
            </p>
            <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto text-sm">
              {taskEvents.map((ev) => (
                <li key={ev.step} className="flex items-center gap-2 rounded bg-white p-2">
                  <Badge variant={statusBadgeVariant(ev.status)}>{ev.status}</Badge>
                  <span>{ev.message}</span>
                </li>
              ))}
              {taskEvents.length === 0 && (
                <li className="text-slate-500">
                  No tasks yet. With Planning Mode on, Send shows the plan here before you Approve
                  &amp; Start.
                </li>
              )}
            </ul>
          </div>
          <div className="flex-1 overflow-y-auto border-t bg-white p-4">
            <h3 className="text-sm font-semibold">Live Preview</h3>
            {findings.length > 0 ? (
              <table className="mt-2 w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="p-1">Claim</th>
                    <th className="p-1">Rule</th>
                    <th className="p-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.slice(0, 20).map((f) => (
                    <tr key={f.finding_id} className="border-t">
                      <td className="p-1">{f.claim_number ?? "—"}</td>
                      <td className="p-1">{f.rule_id}</td>
                      <td className="p-1">{f.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="mt-4 text-sm text-slate-500">Findings appear when audit completes.</p>
            )}
            {reportReady && batchId && (
              <a
                className="mt-4 inline-block rounded bg-emerald-600 px-3 py-2 text-sm text-white"
                href={batchReportUrl(batchId)}
                target="_blank"
                rel="noreferrer"
              >
                Download combined report (PDF)
              </a>
            )}
          </div>
          <div className="max-h-56 overflow-y-auto border-t bg-slate-50 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-800">Audit history</h3>
              <button
                type="button"
                className="text-xs text-emerald-700 hover:underline"
                onClick={() => refreshSessions()}
              >
                Refresh
              </button>
            </div>
            {sessions.length === 0 ? (
              <p className="text-xs text-slate-500">No saved audit sessions yet.</p>
            ) : (
              <ul className="space-y-2">
                {sessions.map((s) => {
                  const selected = batchId === s.batch_id;
                  return (
                    <li key={s.batch_id}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => loadSession(s)}
                        className={`w-full rounded-md border px-3 py-2 text-left text-xs transition-colors ${
                          selected
                            ? "border-emerald-500 bg-emerald-50"
                            : "border-slate-200 bg-white hover:bg-slate-100"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[11px]">{s.batch_id.slice(0, 8)}…</span>
                          <Badge variant={s.status === "completed" ? "success" : "muted"}>
                            {s.status}
                          </Badge>
                        </div>
                        <p className="mt-1 text-slate-600">{formatWhen(s.created_at)}</p>
                        <p className="mt-1 text-slate-500">
                          Claims: {(s.dataset_file_names || []).join(", ") || s.dataset_id.slice(0, 8)}
                        </p>
                        <p className="text-slate-500">
                          Regs: {(s.regulation_file_names || []).join(", ") || "—"} ·{" "}
                          {s.claim_numbers.length} claims · {s.fail_count} fails
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}

function FileChip({
  label,
  done,
  kind,
  onFile,
}: {
  label: string;
  done: boolean;
  kind: "notes" | "comms" | "ref";
  onFile: (kind: "notes" | "comms" | "ref", file: File) => void;
}) {
  const accept = kind === "ref" ? ".xlsx,.xls,.csv" : ".json";
  return (
    <label className={`cursor-pointer rounded border px-2 py-1 ${done ? "border-emerald-400 bg-emerald-50" : ""}`}>
      {done ? "✓ " : ""}
      {label}
      <input
        type="file"
        className="hidden"
        accept={accept}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(kind, f);
        }}
      />
    </label>
  );
}
