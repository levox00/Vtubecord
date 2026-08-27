import { useEffect, useMemo, useState } from "react";
import { fetchPresets, deletePreset, applyPreset, createPreset, updatePreset } from "../lib/api";
import type { CharacterProfile, Preset, Settings } from "../types";
import {
  Bookmark, BookmarkPlus, Check, Copy, Edit2, Eye, RefreshCw, Trash2, X,
  Brain, Volume2, Palette, Mic, Layers, FolderOpen, User, Link2, Search,
} from "lucide-react";

export type PresetType = "master" | "llm" | "tts" | "avatar" | "stt";
type TabType = "all" | PresetType;

export interface MasterPresetReferences {
  llm_preset_id?: string;
  tts_preset_id?: string;
  avatar_preset_id?: string;
  stt_preset_id?: string;
  character_profile_id?: string;
}

export interface MasterPresetsProps {
  presets?: Preset[];
  currentSettings?: Settings | null;
  onApply?: (id: string) => Promise<void> | void;
  onRename?: (id: string, name: string) => Promise<void> | void;
  onOverwrite?: (id: string) => Promise<void> | void;
  onDelete?: (id: string) => Promise<void> | void;
  onDuplicate?: (preset: Preset) => Promise<void> | void;
  onSaveNew?: (name: string, type: string) => Promise<void> | void;
  onSaveMaster?: (name: string, references: MasterPresetReferences) => Promise<void> | void;
  onUpdateMaster?: (id: string, name: string, references: MasterPresetReferences) => Promise<void> | void;
  characterProfiles?: CharacterProfile[];
  onApplyCharacterProfile?: (id: string) => Promise<void> | void;
  onDuplicateCharacterProfile?: (id: string, name: string) => Promise<void> | void;
  onRenameCharacterProfile?: (id: string, name: string) => Promise<void> | void;
  onDeleteCharacterProfile?: (id: string) => Promise<void> | void;
  onClose?: () => void;
  /** Kept for compatibility with older callers; the current channel is unscoped. */
  fixedType?: Exclude<PresetType, "master">;
  title?: string;
  description?: string;
}

const TAB_CONFIG: Array<{ id: TabType; label: string; icon: React.ElementType; color: string }> = [
  { id: "all", label: "All", icon: Layers, color: "#949ba4" },
  { id: "master", label: "Master", icon: Bookmark, color: "#b5bac1" },
  { id: "llm", label: "LLM", icon: Brain, color: "#b5bac1" },
  { id: "tts", label: "TTS", icon: Volume2, color: "#b5bac1" },
  { id: "avatar", label: "Avatar", icon: Palette, color: "#b5bac1" },
  { id: "stt", label: "Whisper", icon: Mic, color: "#b5bac1" },
];

const ENGINE_TYPES: Array<{ type: Exclude<PresetType, "master">; label: string; key: keyof MasterPresetReferences }> = [
  { type: "llm", label: "LLM", key: "llm_preset_id" },
  { type: "tts", label: "TTS", key: "tts_preset_id" },
  { type: "avatar", label: "Avatar", key: "avatar_preset_id" },
  { type: "stt", label: "Whisper", key: "stt_preset_id" },
];

function readUiPreference<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function writeUiPreference(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* optional UI preference */ }
}

function FemaleGenderIcon({ size = 12, className = "text-[#eb459e]" }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="8" r="5" /><path d="M12 13v8" /><path d="M9 17h6" /></svg>;
}

function MaleGenderIcon({ size = 12, className = "text-[#5865f2]" }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="10" cy="14" r="5" /><path d="M19 5l-5.4 5.4" /><path d="M19 5h-5" /><path d="M19 5v5" /></svg>;
}

function getPresetGender(p: { name: string; data?: any }): "female" | "male" | null {
  const name = p.name.toLowerCase();
  const gender = ((p.data?.character_gender || p.data?.user_gender || p.data?.gender || "") as string).toLowerCase();
  if (name.includes("female") || name.includes("women") || name.includes("girl") || gender === "female") return "female";
  if (name.includes("male") || name.includes("man") || name.includes("boy") || gender === "male") return "male";
  return null;
}

export function MasterPresets({
  presets: initialPresets,
  currentSettings,
  onApply: propOnApply,
  onRename: propOnRename,
  onOverwrite: propOnOverwrite,
  onDelete: propOnDelete,
  onDuplicate: propOnDuplicate,
  onSaveNew: propOnSaveNew,
  onSaveMaster: propOnSaveMaster,
  onUpdateMaster: propOnUpdateMaster,
  characterProfiles = [],
  onApplyCharacterProfile,
  onDuplicateCharacterProfile,
  onRenameCharacterProfile,
  onDeleteCharacterProfile,
  onClose,
  fixedType,
  title,
  description,
}: MasterPresetsProps) {
  const [localPresets, setLocalPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(!initialPresets);
  const [activeTab, setActiveTab] = useState<TabType>(() => fixedType ?? readUiPreference<TabType>("ai-vtuber:master-presets-tab", "all"));
  const [selectedPreset, setSelectedPreset] = useState<Preset | null>(null);
  const [modalMode, setModalMode] = useState<"view" | "rename" | "create" | "edit-master" | null>(null);
  const [modalInput, setModalInput] = useState("");
  const [modalType, setModalType] = useState<PresetType>(fixedType ?? "master");
  const [masterReferences, setMasterReferences] = useState<MasterPresetReferences>({});
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [overwritePresetId, setOverwritePresetId] = useState<string | null>(null);

  const presets = (initialPresets ?? localPresets).filter((preset) => !fixedType || preset.type === fixedType);

  const loadPresets = async () => {
    if (initialPresets) return;
    setLoading(true);
    try { setLocalPresets(await fetchPresets()); }
    catch (error) { console.error("Failed to load presets", error); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (!initialPresets) void loadPresets(); }, [initialPresets]);
  useEffect(() => { if (fixedType) { setActiveTab(fixedType); setModalType(fixedType); } }, [fixedType]);
  useEffect(() => { if (!fixedType) writeUiPreference("ai-vtuber:master-presets-tab", activeTab); }, [activeTab, fixedType]);

  const showNotification = (message: string) => {
    setActionSuccess(message);
    window.setTimeout(() => setActionSuccess(null), 2500);
  };

  const handleApply = async (id: string) => {
    try { if (propOnApply) await propOnApply(id); else await applyPreset(id); showNotification("Preset applied successfully"); }
    catch (error) { console.error("Failed to apply preset", error); }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Are you sure you want to delete preset "${name}"?`)) return;
    try {
      if (propOnDelete) await propOnDelete(id);
      else { await deletePreset(id); setLocalPresets((prev) => prev.filter((preset) => preset.id !== id)); }
      if (selectedPreset?.id === id) { setSelectedPreset(null); setModalMode(null); }
      showNotification("Preset deleted");
    } catch (error) { console.error("Failed to delete preset", error); }
  };

  const handleDuplicate = async (preset: Preset) => {
    try {
      if (propOnDuplicate) await propOnDuplicate(preset);
      else { const created = await createPreset({ name: `${preset.name} Copy`, type: preset.type, data: preset.data }); setLocalPresets((prev) => [...prev, created]); }
      showNotification(`Duplicated "${preset.name}"`);
    } catch (error) { console.error("Failed to duplicate preset", error); }
  };

  const handleOverwrite = async (id: string) => {
    const target = presets.find((preset) => preset.id === id);
    if (!target) return;
    try {
      if (propOnOverwrite) await propOnOverwrite(id);
      else if (currentSettings) {
        const updated = await updatePreset(id, { data: currentSettings });
        setLocalPresets((prev) => prev.map((preset) => preset.id === id ? updated : preset));
      }
      showNotification("Preset overwritten with current settings");
    } catch (error) { console.error("Failed to overwrite preset", error); }
    finally { setOverwritePresetId(null); }
  };

  const handleConfirmModal = async () => {
    const name = modalInput.trim();
    if (!name) return;
    try {
      if (modalMode === "rename" && selectedPreset) {
        if (propOnRename) await propOnRename(selectedPreset.id, name);
        else { const updated = await updatePreset(selectedPreset.id, { name }); setLocalPresets((prev) => prev.map((preset) => preset.id === selectedPreset.id ? updated : preset)); }
        showNotification("Preset renamed");
      } else if (modalMode === "edit-master" && selectedPreset && propOnUpdateMaster) {
        await propOnUpdateMaster(selectedPreset.id, name, masterReferences);
        showNotification("Master preset updated");
      } else if (modalMode === "create") {
        if (modalType === "master" && propOnSaveMaster) await propOnSaveMaster(name, masterReferences);
        else if (propOnSaveNew) await propOnSaveNew(name, modalType);
        else if (currentSettings) { const created = await createPreset({ name, type: modalType, data: currentSettings }); setLocalPresets((prev) => [...prev, created]); }
        showNotification(`Saved "${name}" preset`);
      }
    } catch (error) { console.error("Preset operation failed", error); }
    setModalMode(null); setSelectedPreset(null); setModalInput(""); setMasterReferences({});
  };

  const filteredPresets = useMemo(() => activeTab === "all" ? presets : presets.filter((preset) => preset.type === activeTab), [presets, activeTab]);
  const enginePresets = (type: Exclude<PresetType, "master">) => presets.filter((preset) => preset.type === type);

  return (
    <div className="master-presets-quiet h-full min-w-0 bg-[#1e1f22] overflow-y-auto p-4 flex flex-col">
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-[#2b2d31]">
        <div className="flex items-center gap-2"><div className="p-1.5 rounded-md bg-[#3f4147] text-[#b5bac1]"><Bookmark size={18} /></div><div><h2 className="text-sm font-semibold text-[#dbdee1]">{title ?? "Master Presets"}</h2><p className="text-[11px] text-[#949ba4]">{description ?? "Bundle one LLM, TTS, avatar, Whisper, and persona preset"}</p></div></div>
        <div className="flex items-center gap-2">{actionSuccess && <div className="flex items-center gap-1.5 text-xs text-[#57f287] bg-[#57f287]/10 px-2.5 py-1 rounded"><Check size={14} /> {actionSuccess}</div>}<button onClick={() => { setModalMode("create"); setModalType("master"); setModalInput(""); setMasterReferences({}); }} className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium"><BookmarkPlus size={14} /> New master preset</button>{onClose && <button onClick={onClose} className="p-1.5 rounded hover:bg-[#2b2d31] text-[#949ba4]"><X size={16} /></button>}</div>
      </div>

      {!fixedType && <div className="mb-4 rounded-xl border border-[#2b2d31] bg-[#2b2d31]/60 p-3"><div className="flex items-center justify-between mb-2"><div className="flex items-center gap-2 text-xs font-semibold text-[#dbdee1]"><User size={14} className="text-[#eb459e]" /> Personas / character profiles <span className="rounded-full bg-[#1e1f22] px-1.5 text-[10px] text-[#949ba4]">{characterProfiles.length}</span></div><span className="text-[10px] text-[#949ba4]">Markdown profiles</span></div>{characterProfiles.length === 0 ? <p className="rounded border border-dashed border-[#3f4147] px-3 py-3 text-[11px] text-[#949ba4]">No personas loaded. Use Character settings to create or reload a Markdown profile.</p> : <div className="grid grid-cols-1 md:grid-cols-2 gap-2">{characterProfiles.map((profile) => <div key={profile.id} className="flex items-center gap-2 rounded-lg border border-[#1f2023] bg-[#1e1f22] px-2.5 py-2">{profile.profile_picture ? <img src={profile.profile_picture} alt="" className="h-8 w-8 rounded-full object-cover" /> : <div className="h-8 w-8 rounded-full bg-[#5865f2] flex items-center justify-center text-xs font-semibold text-white">{profile.name.slice(0, 1).toUpperCase()}</div>}<div className="min-w-0 flex-1"><div className="truncate text-xs font-medium text-[#dbdee1]">{profile.name}{profile.active ? <span className="ml-1 text-[10px] text-[#57f287]">active</span> : null}</div><div className="truncate text-[10px] text-[#6d6f78]">{profile.id}.md</div></div><button onClick={() => void onApplyCharacterProfile?.(profile.id)} className="rounded bg-[#23a55a] px-2 py-1 text-[10px] font-medium text-white">Apply</button><button onClick={() => void onDuplicateCharacterProfile?.(profile.id, `${profile.name} Copy`)} title="Duplicate persona" className="p-1 text-[#949ba4] hover:text-white"><Copy size={12} /></button><button onClick={() => { const next = window.prompt("Rename persona", profile.name)?.trim(); if (next) void onRenameCharacterProfile?.(profile.id, next); }} title="Rename persona" className="p-1 text-[#949ba4] hover:text-white"><Edit2 size={12} /></button><button onClick={() => { if (!profile.active && characterProfiles.length > 1 && window.confirm(`Delete ${profile.name}?`)) void onDeleteCharacterProfile?.(profile.id); }} title="Delete persona" className="p-1 text-[#949ba4] hover:text-[#f23f43]"><Trash2 size={12} /></button></div>)}</div>}</div>}

      {!fixedType && <div className="flex gap-1.5 mb-4 overflow-x-auto pb-1">{TAB_CONFIG.map(({ id, label, icon: Icon, color }) => { const count = id === "all" ? presets.length : presets.filter((preset) => preset.type === id).length; const active = activeTab === id; return <button key={id} onClick={() => setActiveTab(id)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${active ? "bg-[#5865f2] text-white" : "bg-[#2b2d31] text-[#949ba4] hover:text-[#dbdee1]"}`}><Icon size={13} style={{ color: active ? "#fff" : color }} /><span>{label}</span><span className={`text-[10px] px-1.5 rounded-full ${active ? "bg-white/20" : "bg-[#1e1f22]"}`}>{count}</span></button>; })}</div>}

      <div className="flex-1 overflow-y-auto space-y-2">{loading ? <div className="flex justify-center py-12 text-xs text-[#949ba4]">Loading presets...</div> : filteredPresets.length === 0 ? <div className="flex flex-col items-center justify-center py-16 text-xs text-[#949ba4] border border-dashed border-[#2b2d31] rounded-xl"><FolderOpen size={36} className="text-[#4e5058] mb-2" /><p className="font-medium text-[#dbdee1]">No presets found in this category</p><p className="text-[11px] text-[#6d6f78] mt-1">Use the settings section to save an engine preset, or create a master preset above.</p></div> : filteredPresets.map((preset) => { const meta = TAB_CONFIG.find((tab) => tab.id === preset.type) ?? TAB_CONFIG[0]; const Icon = meta.icon; const gender = getPresetGender(preset); return <div key={preset.id} className="bg-[#2b2d31] border border-[#1f2023] hover:border-[#3f4147] rounded-lg p-3 flex items-center gap-3 group"><div className="p-2.5 rounded-lg" style={{ backgroundColor: `${meta.color}20` }}><Icon size={18} style={{ color: meta.color }} /></div><div className="flex-1 min-w-0"><div className="flex items-center gap-2"><span className="text-sm font-medium text-[#dbdee1] truncate">{preset.name}</span>{gender === "female" && <FemaleGenderIcon size={12} />}{gender === "male" && <MaleGenderIcon size={12} />}<span className="text-[9px] uppercase px-1.5 py-0.5 rounded font-mono" style={{ backgroundColor: `${meta.color}20`, color: meta.color }}>{preset.type}</span></div><div className="text-[10px] text-[#6d6f78] mt-0.5">ID: {preset.id} · {new Date(preset.created_at).toLocaleDateString()}</div>{preset.type === "master" && <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-[#949ba4]"><Link2 size={11} />{Object.entries(preset.data || {}).filter(([, value]) => Boolean(value)).map(([key]) => key.replace(/_preset_id|_profile_id/g, "")).join(" · ") || "Keeps current settings"}</div>}</div><div className="flex items-center gap-1.5"><button onClick={() => void handleApply(preset.id)} className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#23a55a] text-white text-xs font-medium"><Check size={12} /> Apply</button><button onClick={() => void handleDuplicate(preset)} title="Duplicate" className="p-1.5 text-[#949ba4] hover:text-white"><Copy size={14} /></button>{preset.type === "master" && propOnUpdateMaster && <button onClick={() => { setSelectedPreset(preset); setModalInput(preset.name); setModalType("master"); setMasterReferences(preset.data as MasterPresetReferences); setModalMode("edit-master"); }} title="Edit master components" className="p-1.5 text-[#949ba4] hover:text-[#57f287]"><Link2 size={14} /></button>}<button onClick={() => setOverwritePresetId(preset.id)} title="Choose a preset to overwrite" className="p-1.5 text-[#949ba4] hover:text-[#fee75c]"><RefreshCw size={14} /></button><button onClick={() => { setSelectedPreset(preset); setModalMode("view"); }} title="View data" className="p-1.5 text-[#949ba4] hover:text-[#5865f2]"><Eye size={14} /></button><button onClick={() => { setSelectedPreset(preset); setModalInput(preset.name); setModalMode("rename"); }} title="Rename" className="p-1.5 text-[#949ba4] hover:text-white"><Edit2 size={14} /></button><button onClick={() => void handleDelete(preset.id, preset.name)} title="Delete" className="p-1.5 text-[#949ba4] hover:text-[#f23f43]"><Trash2 size={14} /></button></div></div>; })}</div>

      {modalMode === "view" && selectedPreset && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setModalMode(null)}><div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-lg p-5" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between mb-3"><h3 className="text-sm font-semibold text-[#dbdee1]">{selectedPreset.name}</h3><button onClick={() => setModalMode(null)}><X size={16} /></button></div><pre className="max-h-[65vh] overflow-auto bg-[#1e1f22] p-3 rounded text-xs text-[#dbdee1] whitespace-pre-wrap">{JSON.stringify(selectedPreset.data, null, 2)}</pre></div></div>}

      {overwritePresetId && (() => {
        const source = presets.find((preset) => preset.id === overwritePresetId);
        if (!source) return null;
        const candidates = presets.filter((preset) => preset.type === source.type);
        return <MasterOverwriteModal source={source} candidates={candidates} onCancel={() => setOverwritePresetId(null)} onConfirm={(id) => void handleOverwrite(id)} />;
      })()}

      {(modalMode === "rename" || modalMode === "create" || modalMode === "edit-master") && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setModalMode(null)}><div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-lg p-5" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between mb-4"><h3 className="text-sm font-semibold text-[#dbdee1]">{modalMode === "create" ? "Save preset" : modalMode === "edit-master" ? "Edit master preset" : "Rename preset"}</h3><button onClick={() => setModalMode(null)}><X size={16} /></button></div><label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Preset name</label><input autoFocus value={modalInput} onChange={(event) => setModalInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void handleConfirmModal(); }} placeholder="e.g. Stream setup" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1]" />{modalMode === "create" && <><label className="block mt-3 text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Preset type</label><select value={modalType} onChange={(event) => setModalType(event.target.value as PresetType)} className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1]"><option value="master">Master bundle</option><option value="llm">LLM</option><option value="tts">TTS</option><option value="avatar">Avatar</option><option value="stt">Whisper</option></select></>}{(modalMode === "edit-master" || (modalMode === "create" && modalType === "master")) && <div className="mt-3 space-y-2 rounded-lg border border-[#3f4147] bg-[#1e1f22] p-3"><div className="text-xs font-semibold text-[#dbdee1]">Choose settings for this master preset</div>{ENGINE_TYPES.map(({ type, label, key }) => <label key={type} className="flex items-center gap-2 text-xs text-[#949ba4]"><span className="w-16 text-[#dbdee1]">{label}</span><select value={masterReferences[key] ?? ""} onChange={(event) => setMasterReferences((prev) => ({ ...prev, [key]: event.target.value || undefined }))} className="flex-1 rounded bg-[#141517] border border-[#2b2d31] px-2 py-1.5 text-xs text-[#dbdee1]"><option value="">Keep current</option>{enginePresets(type).map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select></label>)}<label className="flex items-center gap-2 text-xs text-[#949ba4]"><span className="w-16 text-[#dbdee1]">Persona</span><select value={masterReferences.character_profile_id ?? ""} onChange={(event) => setMasterReferences((prev) => ({ ...prev, character_profile_id: event.target.value || undefined }))} className="flex-1 rounded bg-[#141517] border border-[#2b2d31] px-2 py-1.5 text-xs text-[#dbdee1]"><option value="">Keep current</option>{characterProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label></div>}
          <div className="flex justify-end gap-2 mt-5"><button onClick={() => setModalMode(null)} className="px-3 py-1.5 rounded text-xs text-[#949ba4]">Cancel</button><button onClick={() => void handleConfirmModal()} disabled={!modalInput.trim()} className="px-4 py-1.5 rounded bg-[#5865f2] text-white text-xs font-medium disabled:opacity-40">{modalMode === "create" ? "Save preset" : "Rename"}</button></div></div></div>}
    </div>
  );
}

function MasterOverwriteModal({ source, candidates, onConfirm, onCancel }: {
  source: Preset;
  candidates: Preset[];
  onConfirm: (id: string) => void;
  onCancel: () => void;
}) {
  const preferenceKey = `ai-vtuber:overwrite-picker:${source.type}`;
  const savedTargetId = readUiPreference<string | null>(`${preferenceKey}:target`, null);
  const [selectedId, setSelectedId] = useState(() => candidates.some((preset) => preset.id === savedTargetId) ? savedTargetId || source.id : source.id);
  const [search, setSearch] = useState(() => readUiPreference(`${preferenceKey}:search`, ""));
  const selected = candidates.find((preset) => preset.id === selectedId);
  const filteredCandidates = candidates.filter((preset) => preset.name.toLowerCase().includes(search.trim().toLowerCase()));
  const typeLabel = source.type === "stt" ? "Whisper" : source.type === "llm" ? "LLM" : source.type === "tts" ? "TTS" : source.type === "avatar" ? "Avatar" : "Master";

  useEffect(() => { writeUiPreference(`${preferenceKey}:target`, selectedId || null); }, [preferenceKey, selectedId]);
  useEffect(() => { writeUiPreference(`${preferenceKey}:search`, search); }, [preferenceKey, search]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-sm p-5" onClick={(event) => event.stopPropagation()}>
        <h3 className="text-sm font-semibold text-[#dbdee1] mb-2">Overwrite {typeLabel} preset</h3>
        <p className="text-xs leading-relaxed text-[#949ba4] mb-4">Choose which existing preset should receive the current active settings. The target name stays unchanged.</p>
        <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Preset to overwrite</label>
        <div className="relative mt-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
          <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search presets..." className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-8 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]" />
        </div>
        <div className="mt-2 max-h-56 overflow-y-auto rounded border border-[#1f2023] bg-[#1e1f22] p-1" role="listbox" aria-label={`${typeLabel} presets`}>
          {filteredCandidates.length === 0 ? <p className="px-2.5 py-3 text-xs text-[#6d6f78]">No matching presets.</p> : filteredCandidates.map((preset) => <button key={preset.id} type="button" role="option" aria-selected={preset.id === selectedId} onClick={() => setSelectedId(preset.id)} className={`w-full rounded px-2.5 py-2 text-left text-xs transition-colors ${preset.id === selectedId ? "bg-[#5865f2]/25 text-white" : "text-[#dbdee1] hover:bg-[#2b2d31]"}`}><span className="block truncate">{preset.name}</span>{preset.id === selectedId && <span className="mt-0.5 block text-[10px] text-[#aeb8ff]">Selected target</span>}</button>)}
        </div>
        <p className="mt-1 text-[10px] text-[#6d6f78]">Showing {filteredCandidates.length} of {candidates.length} presets · Scroll for more</p>
        {selected && <p className="mt-2 text-[11px] text-[#6d6f78]">Target: {selected.name}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-3 py-1.5 rounded text-xs text-[#949ba4] hover:text-[#dbdee1]">Cancel</button>
          <button onClick={() => selectedId && onConfirm(selectedId)} disabled={!selectedId} className="px-4 py-1.5 rounded bg-[#f0ad4e] hover:bg-[#d99635] text-[#1e1f22] text-xs font-semibold disabled:opacity-40">Confirm overwrite</button>
        </div>
      </div>
    </div>
  );
}
