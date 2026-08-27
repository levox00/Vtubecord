import { useState, useCallback, useEffect } from "react";
import { useAppStore, SERVERS, type ServerId, type Channel, type ChannelCategory } from "../stores/appStore";
import { fetchPresets } from "../lib/api";
import type { Preset } from "../types";
import {
  ChevronDown, ChevronRight, Hash, Settings, User, Plus, Mic, MicOff, Headphones,
  HeadphoneOff, Bookmark, Bell, Sparkles, Brain, Volume2, Palette, Database, Music, FolderPlus, Video,
} from "lucide-react";
import { ContextMenu, type ContextMenuItem } from "./ContextMenu";
import { RenameModal } from "./RenameModal";
import { Pencil, Trash2, Copy } from "lucide-react";
import { sfxClick, sfxToggleOn, sfxToggleOff } from "../lib/sounds";

function getChannelIcon(ch: Channel) {
  switch (ch.id) {
    case "master-presets": return Bookmark;
    case "logs": return Bell;
    case "general-settings": return User;
    case "character-settings": return Sparkles;
    case "llm-settings": return Brain;
    case "tts-settings": return Volume2;
    case "stt-settings": return Mic;
    case "avatar-settings": return Palette;
    case "memory-settings": return Database;
    case "spotify-integration": return Music;
    case "obs-integration": return Video;
    default:
      return ch.kind === "voice" ? Volume2 : ch.type === "form" ? Settings : Hash;
  }
}

function CategoryHeader({
  label,
  collapsed,
  onToggle,
  onContextMenu,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      onClick={onToggle}
      onContextMenu={onContextMenu}
      className="flex items-center gap-1 w-full px-1 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#6d6f78] hover:text-[#dbdee1] transition-colors"
    >
      {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
      <span>{label}</span>
    </button>
  );
}

export function ChannelSidebar() {
  const activeServer = useAppStore((s) => s.activeServer);
  const activeChannel = useAppStore((s) => s.activeChannel);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const collapsedCategories = useAppStore((s) => s.collapsedCategories);
  const toggleCategory = useAppStore((s) => s.toggleCategory);
  const channels = useAppStore((s) => s.channels);
  const categoriesState = useAppStore((s) => s.categories);
  const renameChannel = useAppStore((s) => s.renameChannel);
  const deleteChannel = useAppStore((s) => s.deleteChannel);
  const addChannel = useAppStore((s) => s.addChannel);
  const updateChannel = useAppStore((s) => s.updateChannel);
  const addCategory = useAppStore((s) => s.addCategory);
  const renameCategory = useAppStore((s) => s.renameCategory);
  const deleteCategory = useAppStore((s) => s.deleteCategory);
  const isDefaultChannel = useAppStore((s) => s.isDefaultChannel);
  const isMuted = useAppStore((s) => s.isMuted);
  const isDeafened = useAppStore((s) => s.isDeafened);
  const setIsMuted = useAppStore((s) => s.setIsMuted);
  const setIsDeafened = useAppStore((s) => s.setIsDeafened);
  const setActiveServer = useAppStore((s) => s.setActiveServer);
  const setLiveMode = useAppStore((s) => s.setLiveMode);
  const isConnected = useAppStore((s) => s.isConnected);

  const server = SERVERS.find((s) => s.id === activeServer);
  const serverChannels = channels.filter((c) => c.server === activeServer);
  const categories = getCategoryGroups(activeServer, serverChannels, categoriesState);
  const groupedIds = new Set(categories.flatMap((c) => c.channelIds));
  const uncategorizedChannels = serverChannels.filter((c) => !groupedIds.has(c.id));

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; items: ContextMenuItem[] } | null>(null);
  const [renameTarget, setRenameTarget] = useState<Channel | null>(null);
  const [channelEditor, setChannelEditor] = useState<{ mode: "create" | "edit"; channel?: Channel; categoryId?: string; kind?: "text" | "voice" } | null>(null);
  const [categoryEditor, setCategoryEditor] = useState<{ mode: "create" | "edit"; category?: ChannelCategory } | null>(null);
  const [presetOptions, setPresetOptions] = useState<Preset[]>([]);

  useEffect(() => {
    if (activeServer !== "chat") return;
    fetchPresets().then((presets) => setPresetOptions(presets.filter((preset) => preset.type === "master"))).catch(() => setPresetOptions([]));
  }, [activeServer]);

  const handleContextMenu = useCallback((e: React.MouseEvent, ch: Channel) => {
    e.preventDefault();
    e.stopPropagation();

    const isDefault = isDefaultChannel(ch.id);

    const items: ContextMenuItem[] = [];
    if (activeServer === "chat") items.push({
      label: "Channel settings",
      icon: Settings,
      onClick: () => setChannelEditor({ mode: "edit", channel: ch }),
    });
    items.push(
      {
        label: "Rename",
        icon: Pencil,
        onClick: () => setRenameTarget(ch),
        disabled: false,
      },
      {
        label: "Copy Channel ID",
        icon: Copy,
        onClick: () => navigator.clipboard.writeText(ch.id),
      },
      { label: "", icon: Hash, onClick: () => {}, separator: true },
    );

    if (isDefault) {
      items.push({
        label: "Delete",
        icon: Trash2,
        onClick: () => {},
        disabled: true,
      });
    } else {
      items.push({
        label: "Delete Channel",
        icon: Trash2,
        onClick: () => deleteChannel(ch.id),
        danger: true,
      });
    }

    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [activeServer, isDefaultChannel, deleteChannel]);

  const handleCategoryContextMenu = useCallback((e: React.MouseEvent, category: CategoryGroup) => {
    if (activeServer !== "chat") return;
    e.preventDefault();
    e.stopPropagation();
    const categoryState = categoriesState.find((item) => item.id === category.id);
    const items: ContextMenuItem[] = [
      { label: "Create channel here", icon: Plus, onClick: () => setChannelEditor({ mode: "create", categoryId: category.id, kind: category.id === "voice" ? "voice" : "text" }) },
      { label: "", icon: Hash, onClick: () => {}, separator: true },
    ];
    if (categoryState?.custom) {
      items.push(
        { label: "Rename category", icon: Pencil, onClick: () => setCategoryEditor({ mode: "edit", category: categoryState }) },
        { label: "Delete category", icon: Trash2, onClick: () => { if (window.confirm(`Delete category \"${category.name}\"? Its channels will be moved to the default category.`)) deleteCategory(category.id); }, danger: true },
      );
    } else {
      items.push({ label: "Delete category", icon: Trash2, onClick: () => {}, disabled: true });
    }
    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [activeServer, categoriesState, deleteCategory]);

  const saveChannel = useCallback((draft: { label: string; kind: "text" | "voice"; categoryId: string; masterPresetId?: string }) => {
    const normalizedLabel = draft.label.trim().toLowerCase().replace(/[^a-z0-9-_]/g, "-").replace(/-+/g, "-");
    if (!normalizedLabel) return;
    if (channelEditor?.mode === "edit" && channelEditor.channel) {
      updateChannel(channelEditor.channel.id, {
        label: normalizedLabel,
        kind: draft.kind,
        categoryId: draft.categoryId,
        masterPresetId: draft.masterPresetId || null,
      });
      return;
    }
    const id = `${activeServer}-custom-${Date.now()}`;
    addChannel({ id, label: normalizedLabel, type: "chat", kind: draft.kind, categoryId: draft.categoryId, masterPresetId: draft.masterPresetId || null, server: activeServer, icon: draft.kind === "voice" ? "voice" : "#" });
    setActiveChannel(id);
    if (draft.kind === "voice") setLiveMode(true);
  }, [activeServer, addChannel, channelEditor, setActiveChannel, setLiveMode, updateChannel]);

  const handleEmptySpaceContextMenu = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (activeServer !== "chat" || e.target !== e.currentTarget) return;
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: "Create Channel", icon: Plus, onClick: () => setChannelEditor({ mode: "create" }) },
        { label: "Create Category", icon: FolderPlus, onClick: () => setCategoryEditor({ mode: "create" }) },
      ],
    });
  }, [activeServer]);

  const handleChannelClick = useCallback((channelId: string) => {
    sfxClick();
    setActiveChannel(channelId);
    const channel = channels.find((item) => item.id === channelId);
    if (channel?.kind === "voice" || channelId === "live") setLiveMode(true);
    else setLiveMode(false);
  }, [channels, setActiveChannel, setLiveMode]);

  return (
    <div className="w-full h-full bg-[#232428] flex flex-col shrink-0 border-r border-[#2b2d31]">
      {/* Server header */}
      <div className="h-14 px-4 flex items-center border-b border-[#2b2d31] shadow-sm">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">Workspace</p>
          <h2 className="text-sm font-semibold text-[#f2f3f5] truncate">{server?.label ?? "Server"}</h2>
        </div>
      </div>

      {/* Channel list */}
      <div
        className="flex-1 overflow-y-auto px-2.5 py-3 space-y-0.5"
        onContextMenu={handleEmptySpaceContextMenu}
      >
        {categories.map((cat) => {
          const collapsed = collapsedCategories[cat.id] ?? cat.defaultCollapsed;
          const catChannels = serverChannels.filter((ch) => cat.channelIds.includes(ch.id));

          return (
            <div key={cat.id} className="mb-2">
              <CategoryHeader
                label={cat.name}
                collapsed={collapsedCategories[cat.id] ?? cat.defaultCollapsed}
                onToggle={() => toggleCategory(cat.id)}
                onContextMenu={(event) => handleCategoryContextMenu(event, cat)}
              />
              {!collapsed &&
                catChannels.map((ch) => {
                  const active = activeChannel === ch.id;
                  const Icon = getChannelIcon(ch);
                  return (
                    <button
                      key={ch.id}
                      onClick={() => handleChannelClick(ch.id)}
                      onContextMenu={(e) => handleContextMenu(e, ch)}
                      className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-sm transition-colors group ${
                        active
                          ? "bg-[#3f4147] text-[#f2f3f5] font-medium shadow-sm ring-1 ring-[#4e5058]"
                          : "text-[#949ba4] hover:bg-[#2b2d31] hover:text-[#dbdee1]"
                      }`}
                    >
                      <Icon size={16} className="shrink-0 opacity-70" />
                      <span className="truncate">{ch.label}</span>
                      {ch.masterPresetId && <Bookmark size={11} className="ml-auto shrink-0 text-[#aeb8ff]" />}
                      {ch.custom && (
                        <span className="ml-auto text-[9px] text-[#6d6f78] opacity-0 group-hover:opacity-100">
                          custom
                        </span>
                      )}
                    </button>
                  );
                })}

              {/* Add channel button in category */}
              {cat.addable && !collapsed && (
                <button
                  onClick={() => setChannelEditor({ mode: "create", categoryId: cat.id, kind: cat.id === "voice" ? "voice" : "text" })}
                  className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-sm text-[#6d6f78] hover:bg-[#2b2d31] hover:text-[#b5bac1] transition-colors"
                >
                  <Plus size={16} className="shrink-0 opacity-60" />
                    <span className="text-xs">Add {cat.id === "voice" ? "Voice" : "Text"} Channel</span>
                </button>
              )}
            </div>
          );
        })}

        {/* Uncategorized Channels */}
        {uncategorizedChannels.length > 0 && (
          <div className="mb-2">
            <CategoryHeader
              label="Other Channels"
              collapsed={collapsedCategories["Other Channels"] ?? false}
              onToggle={() => toggleCategory("Other Channels")}
            />
            {!(collapsedCategories["Other Channels"] ?? false) &&
              uncategorizedChannels.map((ch) => {
                const active = activeChannel === ch.id;
                const Icon = getChannelIcon(ch);
                return (
                  <button
                    key={ch.id}
                    onClick={() => handleChannelClick(ch.id)}
                    onContextMenu={(e) => handleContextMenu(e, ch)}
                    className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-sm transition-colors group ${
                      active
                        ? "bg-[#3f4147] text-[#f2f3f5] font-medium shadow-sm ring-1 ring-[#4e5058]"
                        : "text-[#949ba4] hover:bg-[#2b2d31] hover:text-[#dbdee1]"
                    }`}
                  >
                    <Icon size={16} className="shrink-0 opacity-70" />
                    <span className="truncate">{ch.label}</span>
                    {ch.masterPresetId && <Bookmark size={11} className="ml-auto shrink-0 text-[#aeb8ff]" />}
                    {ch.custom && (
                      <span className="ml-auto text-[9px] text-[#6d6f78] opacity-0 group-hover:opacity-100">
                        custom
                      </span>
                    )}
                  </button>
                );
              })}
          </div>
        )}
      </div>

      {/* User panel (bottom) */}
      <div className="h-[58px] bg-[#1e1f22] border-t border-[#2b2d31] px-2 flex items-center gap-2 mt-auto shrink-0">
        <div className="w-8 h-8 rounded-lg bg-[#3f4147] flex items-center justify-center">
          <User size={16} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-white truncate">You</p>
          <p className="text-[10px] text-[#6d6f78] truncate">{isConnected ? "Connected" : "Offline"}</p>
        </div>
        <div className="flex gap-0.5">
          <button
            onClick={() => { isMuted ? sfxToggleOn() : sfxToggleOff(); setIsMuted(!isMuted); }}
            title={isMuted ? "Unmute microphone" : "Mute microphone"}
            className={`p-1.5 rounded transition-colors ${isMuted ? "text-[#f23f43] hover:bg-[#f23f43]/10" : "text-[#b5bac1] hover:bg-[#35373c]"}`}
          >
            {isMuted ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          <button
            onClick={() => { isDeafened ? sfxToggleOn() : sfxToggleOff(); setIsDeafened(!isDeafened); }}
            title={isDeafened ? "Undeafen" : "Deafen"}
            className={`p-1.5 rounded transition-colors ${isDeafened ? "text-[#f23f43] hover:bg-[#f23f43]/10" : "text-[#b5bac1] hover:bg-[#35373c]"}`}
          >
            {isDeafened ? <HeadphoneOff size={16} /> : <Headphones size={16} />}
          </button>
          <button
            onClick={() => { sfxClick(); setActiveServer("settings"); setActiveChannel("general-settings"); }}
            title="User Settings"
            className="p-1.5 rounded hover:bg-[#35373c] text-[#b5bac1] transition-colors"
          >
            <Settings size={16} />
          </button>
        </div>
      </div>

      {/* Context menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Rename modal */}
      {renameTarget && (
        <RenameModal
          title={`Rename #${renameTarget.label}`}
          currentValue={renameTarget.label}
          onRename={(newLabel) => {
            renameChannel(renameTarget.id, newLabel);
            setRenameTarget(null);
          }}
          onClose={() => setRenameTarget(null)}
        />
      )}

      {channelEditor && (
        <ChannelEditorModal
          mode={channelEditor.mode}
          channel={channelEditor.channel}
          initialCategoryId={channelEditor.categoryId}
          initialKind={channelEditor.kind}
          categories={categoriesState.filter((category) => category.server === "chat")}
          masterPresets={presetOptions}
          onSave={(draft) => { saveChannel(draft); setChannelEditor(null); }}
          onClose={() => setChannelEditor(null)}
        />
      )}

      {categoryEditor && (
        <CategoryEditorModal
          mode={categoryEditor.mode}
          category={categoryEditor.category}
          onSave={(label) => {
            const normalized = label.trim().replace(/\s+/g, " ");
            if (!normalized) return;
            if (categoryEditor.mode === "edit" && categoryEditor.category) {
              renameCategory(categoryEditor.category.id, normalized);
            } else {
              addCategory({ id: `chat-category-${Date.now()}`, label: normalized, server: "chat" });
            }
            setCategoryEditor(null);
          }}
          onClose={() => setCategoryEditor(null)}
        />
      )}
    </div>
  );
}

interface CategoryGroup {
  id: string;
  name: string;
  channelIds: string[];
  defaultCollapsed: boolean;
  addable?: boolean;
}

function getCategoryGroups(server: ServerId, serverChannels: Channel[], savedCategories: ChannelCategory[]): CategoryGroup[] {
  switch (server) {
    case "chat": {
      const chatCategories = savedCategories.filter((category) => category.server === "chat");
      return chatCategories.map((category) => ({
        id: category.id,
        name: category.label,
        channelIds: serverChannels.filter((channel) => channel.categoryId === category.id).map((channel) => channel.id),
        defaultCollapsed: false,
        addable: true,
      }));
    }
    case "memory":
      return [
        { id: "memory-overview", name: "Overview", channelIds: ["memories"], defaultCollapsed: false },
        { id: "memory-types", name: "By Type", channelIds: ["episodic", "semantic", "relationships"], defaultCollapsed: false },
      ];
    case "goals":
      return [
        { id: "goals-active", name: "Active", channelIds: ["active-goals"], defaultCollapsed: false },
        { id: "goals-completed", name: "Completed", channelIds: ["completed-goals"], defaultCollapsed: true },
        { id: "goals-create", name: "Create", channelIds: ["new-goal"], defaultCollapsed: false },
      ];
    case "skills":
      return [
        { id: "skills-main", name: "Skills", channelIds: ["all-skills", "proficiency"], defaultCollapsed: false },
        { id: "skills-create", name: "Create", channelIds: ["new-skill"], defaultCollapsed: false },
      ];
    case "games":
      return [
        { id: "games-main", name: "Games", channelIds: serverChannels.filter((c) => c.server === "games").map((c) => c.id), defaultCollapsed: false, addable: true },
      ];
    case "settings":
      return [
        { id: "settings-profiles", name: "Profiles", channelIds: ["general-settings", "character-settings"], defaultCollapsed: false },
        { id: "settings-models", name: "Models & Audio", channelIds: ["llm-settings", "tts-settings", "stt-settings", "avatar-settings"], defaultCollapsed: false },
        { id: "settings-integrations", name: "Integrations", channelIds: ["spotify-integration", "obs-integration"], defaultCollapsed: false },
        { id: "settings-presets", name: "Presets", channelIds: ["master-presets"], defaultCollapsed: false },
        { id: "settings-tools", name: "Tools", channelIds: ["logs", "memory-settings"], defaultCollapsed: false },
      ];
    case "discord":
      return [
        { id: "discord-config", name: "Bot Config", channelIds: ["discord-settings", "discord-status"], defaultCollapsed: false },
      ];
    default:
      return [];
  }
}

function ChannelEditorModal({
  mode,
  channel,
  initialCategoryId,
  initialKind,
  categories,
  masterPresets,
  onSave,
  onClose,
}: {
  mode: "create" | "edit";
  channel?: Channel;
  initialCategoryId?: string;
  initialKind?: "text" | "voice";
  categories: ChannelCategory[];
  masterPresets: Preset[];
  onSave: (draft: { label: string; kind: "text" | "voice"; categoryId: string; masterPresetId?: string }) => void;
  onClose: () => void;
}) {
  const [label, setLabel] = useState(channel?.label ?? "new-channel");
  const [kind, setKind] = useState<"text" | "voice">(channel?.kind ?? initialKind ?? "text");
  const [categoryId, setCategoryId] = useState(channel?.categoryId ?? initialCategoryId ?? (kind === "voice" ? "voice" : "text"));
  const [masterPresetId, setMasterPresetId] = useState(channel?.masterPresetId ?? "");

  useEffect(() => {
    if (!categoryId || !categories.some((category) => category.id === categoryId)) {
      setCategoryId(categories.find((category) => category.id === (kind === "voice" ? "voice" : "text"))?.id ?? categories[0]?.id ?? "");
    }
  }, [categoryId, categories, kind]);

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border border-[#3f4147] bg-[#2b2d31] p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-[#f2f3f5]">{mode === "create" ? "Create channel" : "Channel settings"}</h3>
            <p className="mt-1 text-[11px] text-[#949ba4]">Choose a channel type, category, and optional master preset.</p>
          </div>
          <button onClick={onClose} className="text-[#949ba4] hover:text-white">×</button>
        </div>

        <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#949ba4]">Channel name</label>
        <input autoFocus value={label} onChange={(event) => setLabel(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") onSave({ label, kind, categoryId, masterPresetId: masterPresetId || undefined }); }} className="mt-1 w-full rounded border border-[#1f2023] bg-[#1e1f22] px-3 py-2 text-sm text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />

        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#949ba4]">
            Channel type
            <select value={kind} onChange={(event) => setKind(event.target.value as "text" | "voice")} className="mt-1 w-full rounded border border-[#1f2023] bg-[#1e1f22] px-2 py-2 text-xs text-[#dbdee1]">
              <option value="text">Text channel</option>
              <option value="voice">Voice channel</option>
            </select>
          </label>
          <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#949ba4]">
            Category
            <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} className="mt-1 w-full rounded border border-[#1f2023] bg-[#1e1f22] px-2 py-2 text-xs text-[#dbdee1]">
              {categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
            </select>
          </label>
        </div>

        <label className="mt-3 block text-[10px] font-semibold uppercase tracking-wider text-[#949ba4]">
          Master preset
          <select value={masterPresetId} onChange={(event) => setMasterPresetId(event.target.value)} className="mt-1 w-full rounded border border-[#1f2023] bg-[#1e1f22] px-2 py-2 text-xs text-[#dbdee1]">
            <option value="">Use current settings</option>
            {masterPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
          </select>
        </label>
          <p className="mt-2 text-[10px] leading-relaxed text-[#6d6f78]">A selected bundle is used only for this channel&apos;s messages and avatar display. It does not replace your global settings draft.</p>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-xs text-[#949ba4] hover:bg-[#35373c]">Cancel</button>
          <button onClick={() => onSave({ label, kind, categoryId, masterPresetId: masterPresetId || undefined })} disabled={!label.trim() || !categoryId} className="rounded bg-[#5865f2] px-4 py-1.5 text-xs font-medium text-white hover:bg-[#4752c4] disabled:opacity-40">{mode === "create" ? "Create channel" : "Save channel"}</button>
        </div>
      </div>
    </div>
  );
}

function CategoryEditorModal({
  mode,
  category,
  onSave,
  onClose,
}: {
  mode: "create" | "edit";
  category?: ChannelCategory;
  onSave: (label: string) => void;
  onClose: () => void;
}) {
  const [label, setLabel] = useState(category?.label ?? "New Category");
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-[#3f4147] bg-[#2b2d31] p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <h3 className="text-sm font-semibold text-[#f2f3f5]">{mode === "create" ? "Create category" : "Rename category"}</h3>
        <input autoFocus value={label} onChange={(event) => setLabel(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") onSave(label); }} className="mt-3 w-full rounded border border-[#1f2023] bg-[#1e1f22] px-3 py-2 text-sm text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-xs text-[#949ba4] hover:bg-[#35373c]">Cancel</button>
          <button onClick={() => onSave(label)} disabled={!label.trim()} className="rounded bg-[#5865f2] px-4 py-1.5 text-xs font-medium text-white hover:bg-[#4752c4] disabled:opacity-40">Save</button>
        </div>
      </div>
    </div>
  );
}
