import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, InputHTMLAttributes, PointerEvent as ReactPointerEvent, RefObject } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  Download,
  Edit3,
  FileJson,
  FolderOpen,
  History,
  RotateCcw,
  Save,
  Undo2,
  Upload,
  X,
} from "lucide-react";
import { fetchSettings } from "../lib/api";

type DataRecord = Record<string, unknown>;
type Decision = "keep" | "drop";
type PathPart = string | number;

interface DatasetRow { id: string; source: string; data: DataRecord }
interface DecisionHistoryEntry { id: string; previous: Decision | undefined }
interface HuggingFaceCursor { datasetId: string; config: string; split: string; nextOffset: number; total: number | null }
interface DatasetSession { id: string; datasetName: string; sourceKind: "huggingface" | "local"; source: string; rows: number; kept: number; dropped: number; updatedAt: string }

const HF_DATASETS_API = "https://datasets-server.huggingface.co";
const HISTORY_KEY = "ai-vtuber-dataswipe-history";
const MAX_HISTORY = 20;
const SUPPORTED_EXTENSIONS = new Set(["json", "jsonl", "ndjson", "csv", "tsv", "tab", "psv", "txt", "md", "yaml", "yml"]);

function normalizeDatasetId(input: string): string {
  let value = input.trim().replace(/^https?:\/\/(www\.)?huggingface\.co\/datasets\//i, "");
  value = value.split(/[?#]/, 1)[0].replace(/\/(tree|blob|resolve)\/.*$/i, "");
  return value.replace(/^\/+|\/+$/g, "");
}

function asRecord(value: unknown): DataRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as DataRecord) }
    : { text: value == null ? "" : value };
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function previewValue(value: unknown): string {
  if (typeof value === "string") return value.replace(/\s+/g, " ").trim().slice(0, 180);
  if (Array.isArray(value)) return value.slice(0, 3).map(previewValue).filter(Boolean).join(" · ").slice(0, 180);
  if (value && typeof value === "object") return Object.values(value as DataRecord).map(previewValue).filter(Boolean).join(" · ").slice(0, 180);
  return value == null ? "" : String(value);
}

function parseDelimited(text: string, delimiter: string): DataRecord[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i += 1; }
      else quoted = !quoted;
    } else if (char === delimiter && !quoted) {
      row.push(cell); cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell);
      if (row.some((item) => item.trim())) rows.push(row);
      row = []; cell = "";
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); if (row.some((item) => item.trim())) rows.push(row); }
  if (rows.length < 2) return rows.map((values) => ({ value: values.join(delimiter) }));
  const headers = rows[0].map((header, index) => header.trim() || `column_${index + 1}`);
  return rows.slice(1).map((values) => {
    const result: DataRecord = {};
    headers.forEach((header, index) => { result[header] = values[index] ?? ""; });
    return result;
  });
}

function parseSimpleYaml(text: string): DataRecord[] {
  const result: DataRecord = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || line === "---") continue;
    const separator = line.indexOf(":");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim().replace(/^['"]|['"]$/g, "");
    const rawValue = line.slice(separator + 1).trim();
    if (!rawValue) result[key] = "";
    else if (rawValue === "true" || rawValue === "false") result[key] = rawValue === "true";
    else if (!Number.isNaN(Number(rawValue))) result[key] = Number(rawValue);
    else { try { result[key] = JSON.parse(rawValue); } catch { result[key] = rawValue.replace(/^['"]|['"]$/g, ""); } }
  }
  return Object.keys(result).length ? [result] : [{ text }];
}

async function parseLocalFile(file: File): Promise<DataRecord[]> {
  const extension = file.name.toLowerCase().split(".").pop() || "";
  const text = await file.text();
  if (extension === "jsonl" || extension === "ndjson") {
    return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).flatMap((line) => {
      try { return [asRecord(JSON.parse(line))]; } catch { return []; }
    });
  }
  if (extension === "json") {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return parsed.map(asRecord);
      if (Array.isArray(parsed?.rows)) return parsed.rows.map((entry: unknown) => asRecord((entry as { row?: unknown }).row ?? entry));
      return [asRecord(parsed)];
    } catch { return []; }
  }
  if (extension === "csv") return parseDelimited(text, ",");
  if (extension === "tsv" || extension === "tab") return parseDelimited(text, "\t");
  if (extension === "psv") return parseDelimited(text, "|");
  if (extension === "yaml" || extension === "yml") return parseSimpleYaml(text);
  if (extension === "txt" || extension === "md") return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => ({ text: line }));
  return [];
}

function downloadText(filename: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function humanizeKey(key: string): string { return key.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()); }
function cloneValue<T>(value: T): T { if (typeof structuredClone === "function") return structuredClone(value); return JSON.parse(JSON.stringify(value)) as T; }

function setAtPath(root: unknown, path: PathPart[], nextValue: unknown): unknown {
  if (!path.length) return nextValue;
  if (Array.isArray(root)) {
    const copy = [...root];
    const index = Number(path[0]);
    copy[index] = setAtPath(copy[index], path.slice(1), nextValue);
    return copy;
  }
  const copy: DataRecord = root && typeof root === "object" ? { ...(root as DataRecord) } : {};
  const key = String(path[0]);
  copy[key] = setAtPath(copy[key], path.slice(1), nextValue);
  return copy;
}

function escapeRegex(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function preserveCase(source: string, replacement: string): string {
  if (source === source.toUpperCase()) return replacement.toUpperCase();
  if (source[0] === source[0]?.toUpperCase()) return replacement ? replacement[0].toUpperCase() + replacement.slice(1) : replacement;
  return replacement.toLowerCase();
}
function replaceName(text: string, from: string, to: string): string {
  if (!from.trim() || !to.trim()) return text;
  const expression = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escapeRegex(from.trim())})(['’]s)?(?=$|[^\\p{L}\\p{N}_])`, "giu");
  return text.replace(expression, (_match, prefix: string, name: string, possessive?: string) => `${prefix}${preserveCase(name, to.trim())}${possessive || ""}`);
}
function replaceNamesDeep(value: unknown, replacements: Array<{ from: string; to: string }>): unknown {
  if (typeof value === "string") return replacements.reduce((result, item) => replaceName(result, item.from, item.to), value);
  if (Array.isArray(value)) return value.map((item) => replaceNamesDeep(item, replacements));
  if (value && typeof value === "object") { const result: DataRecord = {}; Object.entries(value as DataRecord).forEach(([key, child]) => { result[key] = replaceNamesDeep(child, replacements); }); return result; }
  return value;
}
function countNameMatches(value: unknown, replacements: Array<{ from: string; to: string }>): number {
  if (typeof value === "string") return replacements.reduce<number>((count, item) => { if (!item.from.trim()) return count; const expression = new RegExp(`(^|[^\\p{L}\\p{N}_])${escapeRegex(item.from.trim())}(?=['’]s|$|[^\\p{L}\\p{N}_])`, "giu"); return count + (value.match(expression)?.length || 0); }, 0);
  if (Array.isArray(value)) return value.reduce<number>((count, item) => count + countNameMatches(item, replacements), 0);
  if (value && typeof value === "object") return Object.values(value as DataRecord).reduce<number>((count, item) => count + countNameMatches(item, replacements), 0);
  return 0;
}
function csvCell(value: unknown): string { const text = (typeof value === "string" ? value : displayValue(value)).replace(/\r?\n/g, " "); return /[",]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text; }
function readHistory(): DatasetSession[] { try { const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); return Array.isArray(parsed) ? parsed : []; } catch { return []; } }
function writeHistory(history: DatasetSession[]): void { try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY))); } catch { /* optional */ } }
function sessionStorageKey(kind: "huggingface" | "local", source: string): string { return `ai-vtuber-dataswipe:${kind}:${source}`; }
function readSessionState(kind: "huggingface" | "local", source: string): { decisions: Record<string, Decision>; edits: Record<string, DataRecord> } {
  try {
    const parsed = JSON.parse(localStorage.getItem(sessionStorageKey(kind, source)) || "{}");
    return { decisions: parsed.decisions || {}, edits: parsed.edits || {} };
  } catch { return { decisions: {}, edits: {} }; }
}

function LeafEditor({ value, onChange, editing = true }: { value: unknown; onChange: (value: unknown) => void; editing?: boolean }) {
  if (!editing) return <p className="whitespace-pre-wrap break-words text-[15px] leading-7 text-[#f2f3f5]">{value == null || value === "" ? "—" : displayValue(value)}</p>;
  if (typeof value === "boolean") return <label className="inline-flex items-center gap-2 text-xs text-[#dbdee1]"><input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} className="accent-[#5865f2]" />{value ? "true" : "false"}</label>;
  if (typeof value === "number") return <input type="number" value={value} onChange={(event) => onChange(event.target.value === "" ? 0 : Number(event.target.value))} className="w-full rounded-md border border-[#3a3d43] bg-[#1e1f22] px-2.5 py-2 text-xs text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />;
  if (typeof value === "string") return <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={value.length > 160 || value.includes("\n") ? 5 : 2} className="w-full resize-y rounded-md border border-[#3a3d43] bg-[#1e1f22] px-2.5 py-2 text-xs leading-relaxed text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />;
  return <input value={value == null ? "" : String(value)} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-[#3a3d43] bg-[#1e1f22] px-2.5 py-2 text-xs text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />;
}

function pathsEqual(left: PathPart[] | null | undefined, right: PathPart[] | null | undefined): boolean {
  return Boolean(left && right && left.length === right.length && left.every((part, index) => part === right[index]));
}

function EditHint({ path, editingPath, onEditPath }: { path: PathPart[]; editingPath?: PathPart[] | null; onEditPath?: (path: PathPart[]) => void }) {
  if (!onEditPath || pathsEqual(path, editingPath)) return null;
  return <button type="button" onClick={(event) => { event.stopPropagation(); onEditPath(path); }} className="rounded p-1 text-[#6d6f78] opacity-0 transition-opacity hover:bg-[#3f4147] hover:text-[#dbdee1] group-hover:opacity-100" aria-label="Edit this field"><Edit3 size={12} /></button>;
}

function StructuredEditor({ value, path, onChange, depth = 0, editingPath = null, onEditPath, onHoverPath }: { value: unknown; path: PathPart[]; onChange: (path: PathPart[], value: unknown) => void; depth?: number; editingPath?: PathPart[] | null; onEditPath?: (path: PathPart[]) => void; onHoverPath?: (path: PathPart[] | null) => void }) {
  if (Array.isArray(value)) return <div className={`space-y-2 ${depth ? "border-l border-[#3a3d43] pl-3" : ""}`}>{value.length === 0 ? <p className="text-[11px] text-[#6d6f78]">Empty list</p> : value.map((item, index) => <div key={`${path.join(".")}-${index}`} className="rounded-xl border border-[#3a3d43] bg-[#232428] p-3">{!(item && typeof item === "object" && !Array.isArray(item)) && <div className="mb-2 text-[9px] font-medium uppercase tracking-[0.14em] text-[#6d6f78]">Item {index + 1}</div>}<StructuredEditor value={item} path={[...path, index]} onChange={onChange} depth={depth + 1} editingPath={editingPath} onEditPath={onEditPath} onHoverPath={onHoverPath} /></div>)}</div>;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as DataRecord);
    const roleEntry = entries.find(([key]) => key.toLowerCase() === "role");
    const contentEntry = entries.find(([key]) => ["content", "text", "message"].includes(key.toLowerCase()));
    const renderField = ([key, child]: [string, unknown]) => {
      const fieldPath = [...path, key];
      const fieldEditing = pathsEqual(fieldPath, editingPath);
      return <div key={`${path.join(".")}-${key}`} className="group space-y-1.5" onMouseEnter={() => onHoverPath?.(fieldPath)} onMouseLeave={() => onHoverPath?.(null)}><div className="flex items-center justify-between gap-2"><div className="text-[9px] font-medium uppercase tracking-wider text-[#6d6f78]">{humanizeKey(key)}</div><EditHint path={fieldPath} editingPath={editingPath} onEditPath={onEditPath} /></div>{child && typeof child === "object" ? <StructuredEditor value={child} path={fieldPath} onChange={onChange} depth={depth + 1} editingPath={editingPath} onEditPath={onEditPath} onHoverPath={onHoverPath} /> : <LeafEditor value={child} onChange={(next) => onChange(fieldPath, next)} editing={fieldEditing} />}</div>;
    };
    if (roleEntry && contentEntry) {
      const rolePath = [...path, roleEntry[0]];
      const contentPath = [...path, contentEntry[0]];
      const roleEditing = pathsEqual(rolePath, editingPath);
      const contentEditing = pathsEqual(contentPath, editingPath);
      const extras = entries.filter(([key]) => key !== roleEntry[0] && key !== contentEntry[0]);
      return <div className={`space-y-3 ${depth ? "border-l border-[#3a3d43] pl-3" : ""}`}>
        <div className="group flex items-center gap-2" onMouseEnter={() => onHoverPath?.(rolePath)} onMouseLeave={() => onHoverPath?.(null)}>{roleEditing ? <LeafEditor value={roleEntry[1]} onChange={(next) => onChange(rolePath, next)} editing /> : <span className="text-[9px] font-medium uppercase tracking-[0.14em] text-[#6d6f78]">{String(roleEntry[1])}</span>}<EditHint path={rolePath} editingPath={editingPath} onEditPath={onEditPath} /></div>
        <div className="group space-y-1" onMouseEnter={() => onHoverPath?.(contentPath)} onMouseLeave={() => onHoverPath?.(null)}><div className="flex items-center justify-between gap-2"><span className="text-[9px] uppercase tracking-wider text-[#555861]">{humanizeKey(contentEntry[0])}</span><EditHint path={contentPath} editingPath={editingPath} onEditPath={onEditPath} /></div><LeafEditor value={contentEntry[1]} onChange={(next) => onChange(contentPath, next)} editing={contentEditing} /></div>
        {extras.map(renderField)}
      </div>;
    }
    return <div className={`space-y-3 ${depth ? "border-l border-[#3a3d43] pl-3" : ""}`}>{entries.map(renderField)}</div>;
  }
  return <LeafEditor value={value} onChange={(next) => onChange(path, next)} editing={pathsEqual(path, editingPath)} />;
}
function Stat({ label, value }: { label: string; value: number }) { return <div className="rounded-md border border-[#3a3d43] bg-[#232428] px-3 py-2.5"><p className="text-[10px] uppercase tracking-wider text-[#6d6f78]">{label}</p><p className="mt-0.5 text-lg font-semibold text-[#f2f3f5]">{value.toLocaleString()}</p></div>; }

function HistoryDrawer({ sessions, onResume, onDelete, onClose }: { sessions: DatasetSession[]; onResume: (session: DatasetSession) => void; onDelete: (id: string) => void; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="h-full w-full max-w-md overflow-y-auto border-l border-[#3a3d43] bg-[#2b2d31] p-5 shadow-2xl"><div className="mb-5 flex items-start justify-between gap-3"><div><p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">Dataswipe</p><h2 className="text-lg font-semibold text-[#f2f3f5]">Recent sessions</h2><p className="mt-1 text-xs text-[#949ba4]">Sessions stay in this browser. Local folders must be selected again to resume.</p></div><button onClick={onClose} className="rounded-md p-1.5 text-[#949ba4] hover:bg-[#3f4147] hover:text-[#f2f3f5]" aria-label="Close history"><X size={17} /></button></div>{!sessions.length ? <div className="rounded-md border border-dashed border-[#3a3d43] p-5 text-center text-xs text-[#6d6f78]">No saved sessions yet.</div> : <div className="space-y-2">{sessions.map((session) => <div key={session.id} className="rounded-md border border-[#3a3d43] bg-[#232428] p-3"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-[#dbdee1]">{session.datasetName}</p><p className="mt-1 truncate text-[10px] text-[#6d6f78]">{session.sourceKind === "huggingface" ? "Hugging Face" : "Local folder"} · {session.source || "unknown source"}</p></div><span className="shrink-0 text-[10px] text-[#6d6f78]">{new Date(session.updatedAt).toLocaleDateString()}</span></div><div className="mt-2 flex gap-3 text-[10px] text-[#949ba4]"><span>{session.rows.toLocaleString()} rows</span><span className="text-[#57f287]">{session.kept} kept</span><span className="text-[#ffb4ab]">{session.dropped} dropped</span></div><div className="mt-3 flex gap-2"><button onClick={() => onResume(session)} className="ui-primary-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs"><ArrowRight size={13} />Resume</button><button onClick={() => onDelete(session.id)} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs"><X size={13} />Remove</button></div></div>)}</div>}</aside></div>;
}

function CompletionSummary({ kept, dropped, onExport, onReset }: { kept: number; dropped: number; onExport: (format: "jsonl" | "json" | "csv") => void; onReset: () => void }) {
  return <section className="rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-6 text-center"><div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-[#3f4147]"><Check size={22} className="text-[#dbdee1]" /></div><h2 className="text-base font-semibold text-[#f2f3f5]">Curation complete</h2><p className="mt-1 text-xs text-[#949ba4]">{kept} kept · {dropped} dropped. Export the rows you want to use for training.</p><div className="mt-5 flex flex-wrap justify-center gap-2"><button onClick={() => onExport("jsonl")} disabled={!kept} className="ui-primary-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium disabled:opacity-40"><Download size={14} />Export JSONL</button><button onClick={() => onExport("json")} disabled={!kept} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs disabled:opacity-40"><FileJson size={14} />JSON</button><button onClick={() => onExport("csv")} disabled={!kept} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs disabled:opacity-40"><ArrowRight size={14} />CSV</button><button onClick={onReset} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs"><RotateCcw size={14} />Review again</button></div></section>;
}

function IdentityFields({ label, from, to, onFromChange, onToChange }: { label: string; from: string; to: string; onFromChange: (value: string) => void; onToChange: (value: string) => void }) {
  return <div className="rounded-md border border-[#3a3d43] bg-[#232428] p-3"><p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#949ba4]">{label}</p><div className="grid grid-cols-2 gap-2"><label className="space-y-1"><span className="text-[10px] text-[#6d6f78]">Original</span><input value={from} onChange={(event) => onFromChange(event.target.value)} className="w-full rounded-md border border-[#3a3d43] bg-[#1e1f22] px-2.5 py-2 text-xs text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" /></label><label className="space-y-1"><span className="text-[10px] text-[#6d6f78]">Replace with</span><input value={to} onChange={(event) => onToChange(event.target.value)} placeholder="new name" className="w-full rounded-md border border-[#3a3d43] bg-[#1e1f22] px-2.5 py-2 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:border-[#5865f2] focus:outline-none" /></label></div></div>;
}

function DatasetSetup({ datasetInput, setDatasetInput, importHuggingFace, openLocalFolder, folderInput, handleFolder, busy, error, notice, historyOpen, setHistoryOpen, sessions, resumeSession, removeSession, renderIdentityBar }: { datasetInput: string; setDatasetInput: (value: string) => void; importHuggingFace: () => Promise<void>; openLocalFolder: () => void; folderInput: RefObject<HTMLInputElement>; handleFolder: (event: ChangeEvent<HTMLInputElement>) => void; busy: boolean; error: string; notice: string; historyOpen: boolean; setHistoryOpen: (value: boolean) => void; sessions: DatasetSession[]; resumeSession: (session: DatasetSession) => void; removeSession: (id: string) => void; renderIdentityBar: () => JSX.Element }) {
  return <div className="flex h-full min-w-0 flex-col overflow-y-auto bg-[#313338]"><div className="mx-auto w-full max-w-5xl space-y-4 p-5 sm:p-7"><div className="flex items-center justify-between gap-3 pb-1"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#3f4147]"><Database size={20} className="text-[#dbdee1]" /></div><div><p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">Datasets server</p><h1 className="text-xl font-semibold text-[#f2f3f5]">Dataswipe</h1><p className="mt-0.5 text-xs text-[#949ba4]">Curate training data as human-readable cards, then export a new dataset.</p></div></div><button onClick={() => setHistoryOpen(true)} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs"><History size={14} />History</button></div>{renderIdentityBar()}<section className="rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-4"><div><h2 className="text-sm font-semibold text-[#f2f3f5]">Open a dataset</h2><p className="mt-0.5 text-xs text-[#949ba4]">Use one public Hugging Face link or select a local datasets folder.</p></div><div className="mt-4 space-y-1.5"><label className="text-[10px] uppercase tracking-wider text-[#949ba4]">Hugging Face dataset</label><div className="flex gap-2"><input value={datasetInput} onChange={(event) => setDatasetInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void importHuggingFace(); }} placeholder="org/dataset or https://huggingface.co/datasets/org/dataset" className="min-w-0 flex-1 rounded-md border border-[#3a3d43] bg-[#1e1f22] px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:border-[#5865f2] focus:outline-none" /><button onClick={() => void importHuggingFace()} disabled={busy} className="ui-primary-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium disabled:opacity-50"><Upload size={14} />{busy ? "Loading…" : "Import"}</button></div></div><div className="my-4 flex items-center gap-3"><div className="h-px flex-1 bg-[#3a3d43]" /><span className="text-[10px] uppercase tracking-wider text-[#6d6f78]">or</span><div className="h-px flex-1 bg-[#3a3d43]" /></div><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm text-[#dbdee1]">Local dataset folder</p><p className="mt-0.5 text-[10px] text-[#6d6f78]">JSONL, JSON, CSV, TSV, TXT, Markdown, and YAML files.</p></div><button onClick={openLocalFolder} disabled={busy} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs disabled:opacity-50"><FolderOpen size={14} />Choose folder</button><input ref={folderInput} type="file" multiple onChange={handleFolder} className="hidden" {...({ webkitdirectory: "true", directory: "true" } as InputHTMLAttributes<HTMLInputElement>)} /></div>{error && <div className="mt-4 rounded-md border border-[#f23f43]/30 bg-[#f23f43]/10 px-3 py-2 text-xs text-[#ffb4ab]">{error}</div>}{notice && <div className="mt-4 rounded-md border border-[#5865f2]/30 bg-[#5865f2]/10 px-3 py-2 text-xs text-[#c9cdfb]">{notice}</div>}</section><section className="rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-4"><p className="mb-2 text-[10px] uppercase tracking-wider text-[#6d6f78]">Workflow</p><div className="grid grid-cols-1 gap-3 text-xs text-[#b5bac1] sm:grid-cols-3"><div><span className="font-medium text-[#f2f3f5]">1. Load</span><p className="mt-1 text-[#6d6f78]">Bring in public HF rows or local files.</p></div><div><span className="font-medium text-[#f2f3f5]">2. Swipe & edit</span><p className="mt-1 text-[#6d6f78]">Edit safe leaf fields, then keep or drop cards.</p></div><div><span className="font-medium text-[#f2f3f5]">3. Export</span><p className="mt-1 text-[#6d6f78]">Download a new derived dataset.</p></div></div></section></div>{historyOpen && <HistoryDrawer sessions={sessions} onResume={resumeSession} onDelete={removeSession} onClose={() => setHistoryOpen(false)} />}</div>;
}

export function DatasetEditorPanel() {
  const folderInput = useRef<HTMLInputElement>(null);
  const swipeStart = useRef<{ x: number; y: number } | null>(null);
  const originalRows = useRef<Record<string, DataRecord>>({});
  const [datasetInput, setDatasetInput] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [sourceKind, setSourceKind] = useState<"huggingface" | "local">("huggingface");
  const [sourceLabel, setSourceLabel] = useState("");
  const [hfCursor, setHfCursor] = useState<HuggingFaceCursor | null>(null);
  const [rows, setRows] = useState<DatasetRow[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [decisionHistory, setDecisionHistory] = useState<DecisionHistoryEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [profileNames, setProfileNames] = useState({ user: "", ai: "" });
  const [userFrom, setUserFrom] = useState("Mikudes");
  const [userTo, setUserTo] = useState("");
  const [aiFrom, setAiFrom] = useState("Neuro");
  const [aiTo, setAiTo] = useState("");
  const [sessions, setSessions] = useState<DatasetSession[]>(() => readHistory());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [dragX, setDragX] = useState(0);
  const [leaving, setLeaving] = useState<Decision | null>(null);
  const [editingPath, setEditingPath] = useState<PathPart[] | null>(null);
  const [hoveredPath, setHoveredPath] = useState<PathPart[] | null>(null);

  useEffect(() => { fetchSettings().then((settings) => setProfileNames({ user: settings.user_name || "", ai: settings.character_name || "" })).catch(() => {}); }, []);

  const pendingRows = useMemo(() => rows.filter((row) => !decisions[row.id]), [rows, decisions]);
  const keptRows = useMemo(() => rows.filter((row) => decisions[row.id] === "keep"), [rows, decisions]);
  const droppedCount = useMemo(() => rows.filter((row) => decisions[row.id] === "drop").length, [rows, decisions]);
  const current = pendingRows[0] || null;
  const swipeDirection = leaving || (dragX < -20 ? "drop" : dragX > 20 ? "keep" : null);
  const replacements = useMemo(() => [{ from: userFrom, to: userTo }, { from: aiFrom, to: aiTo }].filter((item) => item.from.trim() && item.to.trim()), [aiFrom, aiTo, userFrom, userTo]);
  const displayData = useMemo(() => current ? replaceNamesDeep(current.data, replacements) as DataRecord : null, [current, replacements]);
  const replacementCount = useMemo(() => keptRows.reduce((count, row) => count + countNameMatches(row.data, replacements), 0), [keptRows, replacements]);

  const rememberSession = useCallback((nextRows: DatasetRow[], nextDecisions: Record<string, Decision>) => {
    if (!datasetName) return;
    const record: DatasetSession = { id: `${sourceKind}:${sourceLabel || datasetName}`, datasetName, sourceKind, source: sourceLabel || datasetName, rows: nextRows.length, kept: nextRows.filter((row) => nextDecisions[row.id] === "keep").length, dropped: nextRows.filter((row) => nextDecisions[row.id] === "drop").length, updatedAt: new Date().toISOString() };
    setSessions((previous) => { const next = [record, ...previous.filter((item) => item.id !== record.id)].slice(0, MAX_HISTORY); writeHistory(next); return next; });
  }, [datasetName, sourceKind, sourceLabel]);
  useEffect(() => {
    if (!rows.length) return;
    rememberSession(rows, decisions);
    const edits: Record<string, DataRecord> = {};
    rows.forEach((row) => {
      if (JSON.stringify(originalRows.current[row.id]) !== JSON.stringify(row.data)) edits[row.id] = row.data;
    });
    if (sourceLabel) {
      try { localStorage.setItem(sessionStorageKey(sourceKind, sourceLabel), JSON.stringify({ decisions, edits })); } catch { /* browser storage is optional */ }
    }
  }, [decisions, rememberSession, rows, sourceKind, sourceLabel]);

  const loadRows = useCallback((loaded: DatasetRow[], label: string, kind: "huggingface" | "local", source = "") => {
    if (!loaded.length) throw new Error("No readable rows were found in this source.");
    const storageSource = source || label;
    const saved = readSessionState(kind, storageSource);
    originalRows.current = Object.fromEntries(loaded.map((row) => [row.id, cloneValue(row.data)]));
    const restoredRows = loaded.map((row) => saved.edits[row.id] ? { ...row, data: saved.edits[row.id] } : row);
    setRows(restoredRows); setDatasetName(label); setSourceLabel(storageSource); setSourceKind(kind); setHfCursor(null); setDecisions(saved.decisions); setDecisionHistory([]); setLeaving(null); setDragX(0); setEditingPath(null); setHoveredPath(null); setError(""); setNotice(Object.keys(saved.decisions).length ? `${loaded.length.toLocaleString()} rows restored from this browser session.` : `${loaded.length.toLocaleString()} rows ready to curate.`);
    const allText = loaded.map((row) => displayValue(row.data)).join(" ");
    setUserFrom(/\bmikudes\b/i.test(allText) ? "Mikudes" : profileNames.user || "Mikudes");
    setAiFrom(/\bneuro\b/i.test(allText) ? "Neuro" : profileNames.ai || "Neuro");
  }, [profileNames.ai, profileNames.user]);

  const importHuggingFace = useCallback(async (inputOverride?: string) => {
    const raw = inputOverride ?? datasetInput;
    const datasetId = normalizeDatasetId(raw);
    if (!datasetId || !datasetId.includes("/")) { setError("Enter a Hugging Face dataset ID or link, for example openai/gsm8k."); return; }
    setBusy(true); setError(""); setNotice("Finding the first available config and split…");
    try {
      const splitResponse = await fetch(`${HF_DATASETS_API}/splits?dataset=${encodeURIComponent(datasetId)}`, { headers: { Accept: "application/json" } });
      if (!splitResponse.ok) throw new Error(splitResponse.status === 401 || splitResponse.status === 403 ? "This dataset is gated or private." : `Hugging Face returned ${splitResponse.status}.`);
      const splitData = await splitResponse.json(); const firstSplit = splitData.splits?.[0];
      if (!firstSplit) throw new Error("No public config or split was found for this dataset.");
      const rowsResponse = await fetch(`${HF_DATASETS_API}/rows?dataset=${encodeURIComponent(datasetId)}&config=${encodeURIComponent(firstSplit.config)}&split=${encodeURIComponent(firstSplit.split)}&offset=0&length=100`, { headers: { Accept: "application/json" } });
      if (!rowsResponse.ok) throw new Error(`Could not load dataset rows (${rowsResponse.status}).`);
      const rowData = await rowsResponse.json();
      const loaded = (rowData.rows || []).map((entry: { row?: unknown; row_idx?: number }, index: number) => ({ id: `hf:${datasetId}:${firstSplit.config}:${firstSplit.split}:${entry.row_idx ?? index}`, source: `${datasetId} · ${firstSplit.config}/${firstSplit.split}`, data: asRecord(entry.row) }));
      loadRows(loaded, `${datasetId} · ${firstSplit.config}/${firstSplit.split}`, "huggingface", datasetId); setDatasetInput(datasetId);
      setHfCursor({ datasetId, config: String(firstSplit.config), split: String(firstSplit.split), nextOffset: loaded.length, total: typeof rowData.num_rows_total === "number" ? rowData.num_rows_total : null });
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Could not load the dataset."); setNotice(""); }
    finally { setBusy(false); }
  }, [datasetInput, loadRows]);

  const loadMoreHuggingFace = useCallback(async () => {
    if (!hfCursor) return;
    setBusy(true); setError(""); setNotice("Loading the next rows…");
    try {
      const response = await fetch(`${HF_DATASETS_API}/rows?dataset=${encodeURIComponent(hfCursor.datasetId)}&config=${encodeURIComponent(hfCursor.config)}&split=${encodeURIComponent(hfCursor.split)}&offset=${hfCursor.nextOffset}&length=100`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`Could not load more rows (${response.status}).`);
      const data = await response.json();
      const nextRows: DatasetRow[] = (data.rows || []).map((entry: { row?: unknown; row_idx?: number }, index: number) => ({ id: `hf:${hfCursor.datasetId}:${hfCursor.config}:${hfCursor.split}:${entry.row_idx ?? hfCursor.nextOffset + index}`, source: `${hfCursor.datasetId} · ${hfCursor.config}/${hfCursor.split}`, data: asRecord(entry.row) }));
      originalRows.current = { ...originalRows.current, ...Object.fromEntries(nextRows.map((row) => [row.id, cloneValue(row.data)])) };
      setRows((previous) => [...previous, ...nextRows]); setHfCursor((previous) => previous ? { ...previous, nextOffset: previous.nextOffset + nextRows.length, total: typeof data.num_rows_total === "number" ? data.num_rows_total : previous.total } : previous); setNotice(nextRows.length ? `${nextRows.length} more rows loaded.` : "No more rows are available in this split."); if (!nextRows.length) setHfCursor(null);
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Could not load more rows."); setNotice(""); }
    finally { setBusy(false); }
  }, [hfCursor]);

  const handleFolder = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []).filter((file) => SUPPORTED_EXTENSIONS.has(file.name.toLowerCase().split(".").pop() || ""));
    if (!files.length) { setError("No supported dataset files were found. Use JSONL, JSON, CSV, TSV, TXT, Markdown, or YAML."); return; }
    setBusy(true); setError(""); setNotice(`Reading ${files.length} dataset file${files.length === 1 ? "" : "s"}…`);
    try {
      const loaded: DatasetRow[] = [];
      for (const file of files) { const parsed = await parseLocalFile(file); const source = file.webkitRelativePath || file.name; parsed.forEach((data, index) => loaded.push({ id: `local:${source}:${index}`, source, data })); }
      const folderLabel = files[0].webkitRelativePath?.split("/")[0] || "local datasets";
      loadRows(loaded, `${folderLabel} · ${files.length} file${files.length === 1 ? "" : "s"}`, "local", folderLabel);
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Could not read the dataset."); setNotice(""); }
    finally { setBusy(false); if (folderInput.current) folderInput.current.value = ""; }
  }, [loadRows]);

  const commitDecision = useCallback((decision: Decision) => {
    if (!current) return;
    setDecisionHistory((previous) => [...previous, { id: current.id, previous: decisions[current.id] }]); setDecisions((previous) => ({ ...previous, [current.id]: decision })); setLeaving(null); setDragX(0); setEditingPath(null); setHoveredPath(null);
  }, [current, decisions]);
  const decide = useCallback((decision: Decision) => { if (!current || leaving) return; setLeaving(decision); window.setTimeout(() => commitDecision(decision), 170); }, [commitDecision, current, leaving]);
  const undo = useCallback(() => { if (leaving) return; const last = decisionHistory[decisionHistory.length - 1]; if (!last) return; setDecisions((previous) => { const next = { ...previous }; if (last.previous) next[last.id] = last.previous; else delete next[last.id]; return next; }); setDecisionHistory((previous) => previous.slice(0, -1)); }, [decisionHistory, leaving]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName)) return;
      if (event.key === "ArrowRight" || ["y", "k"].includes(event.key.toLowerCase())) { event.preventDefault(); decide("keep"); }
      else if (event.key === "ArrowLeft" || ["n", "j"].includes(event.key.toLowerCase())) { event.preventDefault(); decide("drop"); }
      else if (event.key.toLowerCase() === "u" || event.key === "Backspace") { event.preventDefault(); undo(); }
      else if (event.key.toLowerCase() === "e") { event.preventDefault(); if (hoveredPath) setEditingPath((previous) => pathsEqual(previous, hoveredPath) ? null : hoveredPath); }
    };
    window.addEventListener("keydown", onKeyDown); return () => window.removeEventListener("keydown", onKeyDown);
  }, [current?.id, decide, hoveredPath, undo]);

  const updateField = useCallback((rowId: string, path: PathPart[], value: unknown) => { setRows((previous) => previous.map((row) => row.id === rowId ? { ...row, data: setAtPath(row.data, path, value) as DataRecord } : row)); }, []);
  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => { const target = event.target as HTMLElement; if (target.closest("textarea,input,select,button")) return; swipeStart.current = { x: event.clientX, y: event.clientY }; event.currentTarget.setPointerCapture(event.pointerId); }, []);
  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => { if (!swipeStart.current || leaving) return; const delta = event.clientX - swipeStart.current.x; setDragX(Math.max(-180, Math.min(180, delta))); }, [leaving]);
  const onPointerUp = useCallback(() => { if (!swipeStart.current) return; const distance = dragX; swipeStart.current = null; if (Math.abs(distance) > 100) decide(distance > 0 ? "keep" : "drop"); else setDragX(0); }, [decide, dragX]);
  const resetSession = useCallback(() => { if (rows.length && !window.confirm("Reset all keep/drop decisions for this dataset?")) return; setDecisions({}); setDecisionHistory([]); setLeaving(null); setDragX(0); setEditingPath(null); setHoveredPath(null); setNotice("Session reset. All rows are pending again."); }, [rows.length]);
  const clearDataset = useCallback(() => { setRows([]); setHfCursor(null); setDecisions({}); setDecisionHistory([]); setDatasetName(""); setSourceLabel(""); setEditingPath(null); setHoveredPath(null); setNotice(""); setError(""); }, []);
  const exportRows = useCallback((format: "jsonl" | "json" | "csv") => {
    if (!keptRows.length) { setError("Keep at least one row before exporting."); return; }
    const prepared = keptRows.map((row) => replaceNamesDeep(cloneValue(row.data), replacements) as DataRecord);
    const base = (datasetName || "curated-dataset").replace(/[^a-z0-9._-]+/gi, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "curated-dataset";
    if (format === "jsonl") downloadText(`${base}-edited.jsonl`, prepared.map((row) => JSON.stringify(row)).join("\n") + "\n", "application/x-ndjson");
    else if (format === "json") downloadText(`${base}-edited.json`, JSON.stringify(prepared, null, 2), "application/json");
    else { const fields = Array.from(new Set(prepared.flatMap((row) => Object.keys(row)))); const csv = [fields.map(csvCell).join(","), ...prepared.map((row) => fields.map((field) => csvCell(row[field])).join(","))].join("\n"); downloadText(`${base}-edited.csv`, csv, "text/csv"); }
    setNotice(`Exported ${prepared.length.toLocaleString()} kept rows as a new file${replacementCount ? ` with ${replacementCount} name replacement${replacementCount === 1 ? "" : "s"}` : ""}.`);
  }, [datasetName, keptRows, replacementCount, replacements]);
  const resumeSession = useCallback((session: DatasetSession) => { setHistoryOpen(false); if (session.sourceKind === "huggingface") { setDatasetInput(session.source); void importHuggingFace(session.source); } else { clearDataset(); setNotice(`Select the local folder for “${session.datasetName}” to resume this session.`); } }, [clearDataset, importHuggingFace]);
  const removeSession = useCallback((id: string) => { setSessions((previous) => { const next = previous.filter((session) => session.id !== id); writeHistory(next); return next; }); }, []);
  const openLocalFolder = useCallback(() => folderInput.current?.click(), []);

  const renderIdentityBar = () => <section className="rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-4"><div className="mb-3 flex items-start gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#3f4147]"><Database size={17} className="text-[#b5bac1]" /></div><div><h2 className="text-sm font-semibold text-[#f2f3f5]">Dataset identity replacements</h2><p className="mt-0.5 text-xs text-[#949ba4]">Draft-only replacements apply to exported string values. The source file and your active profile stay untouched.</p></div></div><div className="grid grid-cols-1 gap-3 lg:grid-cols-2"><IdentityFields label="Your name" from={userFrom} to={userTo} onFromChange={setUserFrom} onToChange={setUserTo} /><IdentityFields label="AI name" from={aiFrom} to={aiTo} onFromChange={setAiFrom} onToChange={setAiTo} /></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2"><p className="text-[10px] text-[#6d6f78]">{replacementCount ? `${replacementCount} replacement${replacementCount === 1 ? "" : "s"} will be applied to kept rows on export.` : "Leave replacement fields blank to keep the original names."}</p><button onClick={() => { setUserTo(""); setAiTo(""); }} disabled={!userTo && !aiTo} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:opacity-40"><RotateCcw size={13} />Clear replacements</button></div></section>;

  if (!rows.length) return <DatasetSetup datasetInput={datasetInput} setDatasetInput={setDatasetInput} importHuggingFace={importHuggingFace} openLocalFolder={openLocalFolder} folderInput={folderInput} handleFolder={handleFolder} busy={busy} error={error} notice={notice} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} sessions={sessions} resumeSession={resumeSession} removeSession={removeSession} renderIdentityBar={renderIdentityBar} />;

  return <div className="flex h-full min-w-0 flex-col overflow-hidden bg-[#313338]"><input ref={folderInput} type="file" multiple onChange={(event) => void handleFolder(event)} className="hidden" {...({ webkitdirectory: "true", directory: "true" } as InputHTMLAttributes<HTMLInputElement>)} /><div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[#3a3d43] bg-[#2b2d31] px-5 py-3"><div className="min-w-0"><p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">{sourceKind === "local" ? "Local folder" : "Hugging Face"}</p><h1 className="truncate text-sm font-semibold text-[#f2f3f5]">{datasetName}</h1></div><div className="flex items-center gap-1.5">{hfCursor && (hfCursor.total == null || rows.length < hfCursor.total) && <button onClick={() => void loadMoreHuggingFace()} disabled={busy} className="ui-primary-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:opacity-50"><Upload size={13} />{busy ? "Loading…" : "Load more"}</button>}<button onClick={() => setHistoryOpen(true)} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs"><History size={13} />History</button><button onClick={resetSession} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs"><RotateCcw size={14} />Reset</button><button onClick={clearDataset} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs"><FolderOpen size={14} />Change source</button></div></div><div className="flex-1 overflow-y-auto p-4 sm:p-5"><div className="mx-auto w-full max-w-[1600px] space-y-4">{(error || notice) && <div className={`rounded-md border px-3 py-2 text-xs ${error ? "border-[#f23f43]/30 bg-[#f23f43]/10 text-[#ffb4ab]" : "border-[#5865f2]/30 bg-[#5865f2]/10 text-[#c9cdfb]"}`}>{error || notice}</div>}{renderIdentityBar()}{current ? <div className="grid min-h-[520px] grid-cols-1 items-stretch gap-4 xl:grid-cols-[minmax(280px,0.72fr)_minmax(0,1.8fr)]"><section className="min-w-0 rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-4"><div className="mb-4 grid grid-cols-3 gap-2"><Stat label="Pending" value={pendingRows.length} /><Stat label="Kept" value={keptRows.length} /><Stat label="Dropped" value={droppedCount} /></div><div className="mb-3 flex items-center justify-between"><div><h2 className="text-sm font-semibold text-[#f2f3f5]">Queue</h2><p className="mt-1 text-[10px] text-[#6d6f78]">Rows waiting for a decision</p></div><span className="text-xs text-[#949ba4]">{pendingRows.length}</span></div><div className="max-h-[min(55vh,620px)] space-y-1.5 overflow-y-auto pr-1">{pendingRows.slice(0, 40).map((row, index) => { const firstField = Object.keys(row.data)[0]; return <div key={row.id} className={`rounded-md border px-3 py-2 ${index === 0 ? "border-[#5865f2]/70 bg-[#5865f2]/10" : "border-[#3a3d43] bg-[#1e1f22]"}`}><div className="flex items-center justify-between gap-2"><span className="truncate text-[10px] text-[#949ba4]">{row.source}</span><span className="text-[10px] text-[#6d6f78]">#{index + 1}</span></div><p className="mt-1 line-clamp-2 break-words text-xs text-[#dbdee1]">{firstField ? `${humanizeKey(firstField)}: ${previewValue(replaceNamesDeep(row.data[firstField], replacements))}` : "Empty row"}</p></div>; })}</div></section><section className="flex min-h-[520px] min-w-0 flex-col overflow-hidden rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-5"><div className="mb-4 flex items-start justify-between gap-3"><div><p className="text-[10px] uppercase tracking-wider text-[#6d6f78]">Card {rows.length - pendingRows.length + 1} of {rows.length}</p><h2 className="mt-1 text-base font-semibold text-[#f2f3f5]">Swipe to curate</h2><p className="mt-1 max-w-xl truncate text-[10px] text-[#6d6f78]">{current.source}</p></div><span className="shrink-0 text-[10px] text-[#6d6f78]">Drag left to drop · right to keep</span></div><div className="relative mx-auto min-h-[440px] w-full max-w-4xl flex-1 touch-pan-y">{pendingRows.slice(1, 3).reverse().map((row, index) => <div key={row.id} className="absolute inset-x-0 top-0 rounded-lg border border-[#3a3d43] bg-[#232428] p-4" style={{ transform: `translateY(${(index + 1) * 10}px) scale(${1 - (index + 1) * 0.025})`, opacity: 0.65 - index * 0.12 }}><p className="text-[10px] uppercase tracking-wider text-[#6d6f78]">Upcoming card</p><p className="mt-2 line-clamp-4 break-words text-xs text-[#949ba4]">{previewValue(replaceNamesDeep(Object.values(row.data)[0], replacements)) || "Empty row"}</p></div>)}<div data-dataswipe-card="current" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} className={`relative z-10 min-h-[360px] max-h-[min(62vh,650px)] overflow-y-auto rounded-2xl border bg-[#1e1f22] p-5 shadow-[0_18px_50px_rgba(0,0,0,0.32)] ring-1 ring-white/5 transition-transform ${leaving ? "duration-150" : "duration-75"} ${dragX > 60 ? "border-[#23a55a]" : dragX < -60 ? "border-[#f23f43]" : "border-[#5865f2]/50"}`} style={{ transform: `translateX(${leaving === "keep" ? 320 : leaving === "drop" ? -320 : dragX}px) rotate(${leaving === "keep" ? 12 : leaving === "drop" ? -12 : dragX / 22}deg)` }}><div className="mb-4 flex items-center justify-between gap-3"><div className="flex min-w-0 items-center gap-2"><span className={`rounded-xl px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] shadow-lg transition-colors ${dragX > 60 || leaving === "keep" ? "bg-[#23a55a]/15 text-[#57f287]" : dragX < -60 || leaving === "drop" ? "bg-[#f23f43]/15 text-[#ffb4ab]" : "bg-[#3f4147] text-[#949ba4]"}`}>{swipeDirection === "keep" ? "KEEP" : swipeDirection === "drop" ? "DROP" : "EDIT"}</span><button type="button" onClick={() => editingPath ? setEditingPath(null) : hoveredPath && setEditingPath(hoveredPath)} disabled={!editingPath && !hoveredPath} aria-pressed={!!editingPath} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40">{editingPath ? <><Check size={13} />Done <kbd className="rounded border border-[#3a3d43] px-1 text-[9px] text-[#6d6f78]">E</kbd></> : <><Edit3 size={13} />{hoveredPath ? "Edit hovered field" : "Hover a field"} <kbd className="rounded border border-[#3a3d43] px-1 text-[9px] text-[#6d6f78]">E</kbd></>}</button></div><span className="shrink-0 text-[10px] text-[#6d6f78]">{current.id.split(":").slice(-1)[0]}</span></div><StructuredEditor value={displayData || current.data} path={[]} onChange={(path, value) => updateField(current.id, path, value)} editingPath={editingPath} onEditPath={setEditingPath} onHoverPath={setHoveredPath} /></div></div><div className="mt-5 flex items-center justify-between gap-3 border-t border-[#3a3d43] pt-4"><button onClick={undo} disabled={!decisionHistory.length || !!leaving} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs disabled:opacity-40"><Undo2 size={14} />Undo</button><div className="flex items-center gap-2"><button onClick={() => decide("drop")} disabled={!!leaving} className="inline-flex items-center gap-1.5 rounded-md border border-[#f23f43]/40 bg-[#f23f43]/10 px-4 py-2 text-xs font-medium text-[#ffb4ab] hover:bg-[#f23f43]/20 disabled:opacity-40"><ArrowLeft size={15} />Drop <kbd className="rounded border border-current/30 px-1.5 py-0.5 text-[9px] font-semibold opacity-80">N</kbd></button><button onClick={() => decide("keep")} disabled={!!leaving} className="inline-flex items-center gap-1.5 rounded-md bg-[#23a55a] px-4 py-2 text-xs font-medium text-white hover:bg-[#1f8a4c] disabled:opacity-40"><ArrowRight size={15} />Keep <kbd className="rounded border border-current/30 px-1.5 py-0.5 text-[9px] font-semibold opacity-80">Y</kbd></button></div></div></section></div> : <CompletionSummary kept={keptRows.length} dropped={droppedCount} onExport={exportRows} onReset={resetSession} />}<div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#3a3d43] bg-[#2b2d31] p-3"><p className="text-[10px] text-[#6d6f78]">Edits and name replacements stay in memory until you export a new file.</p><div className="flex flex-wrap gap-1.5"><button onClick={() => exportRows("jsonl")} disabled={!keptRows.length} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:opacity-40"><Download size={13} />JSONL</button><button onClick={() => exportRows("json")} disabled={!keptRows.length} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:opacity-40"><FileJson size={13} />JSON</button><button onClick={() => exportRows("csv")} disabled={!keptRows.length} className="ui-muted-button inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs disabled:opacity-40"><Save size={13} />CSV</button></div></div></div></div>{historyOpen && <HistoryDrawer sessions={sessions} onResume={resumeSession} onDelete={removeSession} onClose={() => setHistoryOpen(false)} />}</div>;
}
