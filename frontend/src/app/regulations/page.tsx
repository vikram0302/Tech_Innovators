"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  getActiveRegulations,
  regulationFilePreviewUrl,
  removeRegulationFile,
  uploadRegulations,
} from "@/lib/api";

function isPdf(name: string) {
  return name.toLowerCase().endsWith(".pdf");
}

export default function RegulationsPage() {
  const [active, setActive] = useState<{
    active: boolean;
    regulation_set_id?: string;
    files?: string[];
  }>({ active: false });
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const data = await getActiveRegulations();
    setActive(data);
    setSelectedFile((prev) => {
      if (prev && !data.files?.includes(prev)) {
        setTextPreview(null);
        return null;
      }
      return prev;
    });
  }, []);

  useEffect(() => {
    refresh().catch((e) => {
      const msg = String(e);
      if (msg.includes("Not Found")) {
        setError(
          "Cannot reach the audit API. Start the backend (scripts/start-api.ps1), then restart npm run dev.",
        );
      } else {
        setError(msg);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once on mount
  }, []);

  useEffect(() => {
    setPreviewError(null);
    setTextPreview(null);
    if (pdfPreviewUrl) {
      URL.revokeObjectURL(pdfPreviewUrl);
      setPdfPreviewUrl(null);
    }
    if (!selectedFile) return;

    let cancelled = false;
    const url = regulationFilePreviewUrl(selectedFile);

    (async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) {
          const body = await res.text();
          let detail = body;
          try {
            detail = JSON.parse(body).detail ?? body;
          } catch {
            /* plain text */
          }
          if (res.status === 404 && detail === "Not Found") {
            throw new Error(
              "Preview API is unavailable. Restart the backend (scripts/start-api.ps1) and refresh this page.",
            );
          }
          throw new Error(detail || res.statusText);
        }
        if (isPdf(selectedFile)) {
          const blob = await res.blob();
          if (cancelled) return;
          const objectUrl = URL.createObjectURL(blob);
          setPdfPreviewUrl(objectUrl);
        } else {
          const text = await res.text();
          if (!cancelled) setTextPreview(text);
        }
      } catch (e) {
        if (!cancelled) setPreviewError(String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- revoke prior blob when selection changes
  }, [selectedFile]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    try {
      await uploadRegulations(files);
      await refresh();
      const first = files[0]?.name;
      if (first) setSelectedFile(first);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onRemove = async (filename: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Remove "${filename}" from the active regulation set?`)) return;
    setBusy(true);
    setError(null);
    try {
      const result = await removeRegulationFile(filename);
      setActive({
        active: result.active,
        regulation_set_id: result.regulation_set_id ?? undefined,
        files: result.files,
      });
      if (selectedFile === filename) {
        setSelectedFile(result.files?.[0] ?? null);
        setTextPreview(null);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const fileList = active.files ?? [];

  return (
    <AppShell>
      <div className="flex min-h-[calc(100vh-3.5rem)] flex-col lg:flex-row">
        <section className="flex w-full flex-col border-b border-slate-200 bg-white p-6 lg:w-[42%] lg:border-b-0 lg:border-r">
          <h1 className="text-xl font-semibold text-slate-900">Regulations</h1>
          <p className="mt-2 text-sm text-slate-600">
            Upload standards here. Audits use this active set — select a file to preview it on the
            right.
          </p>
          {error && (
            <p className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>
          )}
          <div className="mt-6 rounded-lg border-2 border-dashed border-emerald-200 bg-slate-50 p-6 text-center">
            <p className="text-sm text-slate-600">PDF, TXT, or MD — multiple files allowed</p>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
              onChange={onUpload}
            />
            <Button
              disabled={busy}
              type="button"
              className="mt-4"
              onClick={() => fileInputRef.current?.click()}
            >
              {busy ? "Working…" : "Upload regulations"}
            </Button>
          </div>

          {active.active && (
            <div className="mt-6 flex min-h-0 flex-1 flex-col">
              <p className="text-sm font-medium text-emerald-700">Active regulation set</p>
              <p className="mt-1 font-mono text-xs text-slate-500">{active.regulation_set_id}</p>
              <ul className="mt-3 space-y-1 overflow-y-auto">
                {fileList.map((f) => {
                  const selected = selectedFile === f;
                  return (
                    <li key={f}>
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => setSelectedFile(f)}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") setSelectedFile(f);
                        }}
                        className={`flex cursor-pointer items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                          selected
                            ? "border-emerald-500 bg-emerald-50 text-emerald-900"
                            : "border-slate-200 bg-white text-slate-800 hover:bg-slate-50"
                        }`}
                      >
                        <span className="truncate">{f}</span>
                        <button
                          type="button"
                          disabled={busy}
                          className="shrink-0 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
                          onClick={(ev) => onRemove(f, ev)}
                          aria-label={`Remove ${f}`}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>

        <section className="flex min-h-[50vh] flex-1 flex-col bg-slate-100 p-6 lg:min-h-0">
          <h2 className="text-sm font-medium text-slate-700">Preview</h2>
          {!selectedFile && (
            <p className="mt-8 text-center text-sm text-slate-500">
              {fileList.length
                ? "Click a document on the left to preview it here."
                : "Upload a regulation file to get started."}
            </p>
          )}
          {previewError && (
            <p className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-800">{previewError}</p>
          )}
          {selectedFile && isPdf(selectedFile) && !previewError && (
            <>
              {!pdfPreviewUrl && (
                <p className="mt-8 text-center text-sm text-slate-500">Loading preview…</p>
              )}
              {pdfPreviewUrl && (
                <iframe
                  title={selectedFile}
                  src={pdfPreviewUrl}
                  className="mt-4 min-h-[70vh] w-full flex-1 rounded-lg border border-slate-300 bg-white shadow-sm"
                />
              )}
            </>
          )}
          {selectedFile && !isPdf(selectedFile) && !previewError && (
            <pre className="mt-4 max-h-[calc(100vh-10rem)] flex-1 overflow-auto rounded-lg border border-slate-300 bg-white p-4 text-xs leading-relaxed text-slate-800 shadow-sm whitespace-pre-wrap">
              {textPreview ?? "Loading…"}
            </pre>
          )}
        </section>
      </div>
    </AppShell>
  );
}
