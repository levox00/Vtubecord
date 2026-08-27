import { useEffect, useState } from "react";
import { fetchMemories, createMemory, deleteMemory } from "../lib/api";
import type { Memory } from "../types";
import { Trash2, Pin, Brain, Heart, Users, Zap, Clock, GraduationCap } from "lucide-react";

const TYPE_CONFIG: Record<string, { color: string; icon: React.ElementType }> = {
  short_term: { color: "text-[#b5bac1]", icon: Clock },
  episodic: { color: "text-[#b5bac1]", icon: Brain },
  semantic: { color: "text-[#b5bac1]", icon: GraduationCap },
  relationship: { color: "text-[#b5bac1]", icon: Users },
  skill: { color: "text-[#b5bac1]", icon: Zap },
  experience: { color: "text-[#b5bac1]", icon: Heart },
};

interface MemoryPanelProps {
  filter?: string;
}

export function MemoryPanel({ filter: channelFilter }: MemoryPanelProps) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [newContent, setNewContent] = useState("");
  const [newType, setNewType] = useState("episodic");
  const [loading, setLoading] = useState(true);

  // Sync filter from channel
  useEffect(() => {
    if (channelFilter === "episodic") setFilter("episodic");
    else if (channelFilter === "semantic") setFilter("semantic");
    else if (channelFilter === "relationships") setFilter("relationship");
    else setFilter("");
  }, [channelFilter]);

  const load = async () => {
    try {
      const data = await fetchMemories(filter || undefined);
      setMemories(data);
    } catch (e) {
      console.error("Failed to load memories", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filter]);

  const handleAdd = async () => {
    if (!newContent.trim()) return;
    try {
      const m = await createMemory({ memory_type: newType, content: newContent.trim() });
      setMemories((prev) => [m, ...prev]);
      setNewContent("");
    } catch (e) {
      console.error("Failed to create memory", e);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch (e) {
      console.error("Failed to delete memory", e);
    }
  };

  return (
    <div className="memory-quiet flex flex-col h-full min-w-0 p-5 overflow-hidden bg-[#313338]">
      {/* Add form */}
      <div className="flex gap-2 mb-4 p-3 rounded-xl bg-[#2b2d31] border border-[#3a3d43]">
        <select
          value={newType}
          onChange={(e) => setNewType(e.target.value)}
            className="bg-[#1e1f22] border border-[#3a3d43] rounded-md px-2.5 py-1.5 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
        >
          <option value="episodic">Episodic</option>
          <option value="semantic">Semantic</option>
          <option value="relationship">Relationship</option>
          <option value="skill">Skill</option>
          <option value="experience">Experience</option>
        </select>
        <input
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Add a memory..."
          className="flex-1 bg-[#1e1f22] border border-[#3a3d43] rounded-md px-3 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
        />
        <button
          onClick={handleAdd}
          className="px-3 py-1.5 rounded-md bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors"
        >
          Add
        </button>
      </div>

      {/* Memory list */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {loading && <p className="text-[#949ba4] text-xs">Loading...</p>}
        {!loading && memories.length === 0 && (
          <p className="text-[#949ba4] text-xs">No memories yet.</p>
        )}
        {memories.map((m) => {
          const cfg = TYPE_CONFIG[m.memory_type] ?? { color: "text-[#949ba4]", icon: Brain };
          const Icon = cfg.icon;
          return (
            <div key={m.id} className="flex items-start gap-3 p-2.5 rounded hover:bg-[#2e3035] group">
              <div className={`shrink-0 w-8 h-8 rounded flex items-center justify-center bg-[#2b2d31] ${cfg.color}`}>
                <Icon size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-[10px] font-semibold uppercase tracking-wider ${cfg.color}`}>
                    {m.memory_type}
                  </span>
                  {m.pinned && <Pin size={9} className="text-[#fee75c]" />}
                  <span className="text-[9px] text-[#6d6f78]">{(m.importance * 100).toFixed(0)}%</span>
                </div>
                <p className="text-xs text-[#dbdee1] break-words">{m.content}</p>
                {m.tags.length > 0 && (
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {m.tags.map((tag) => (
                      <span key={tag} className="px-1.5 py-0.5 bg-[#2b2d31] rounded text-[9px] text-[#949ba4]">{tag}</span>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => handleDelete(m.id)}
                className="shrink-0 opacity-0 group-hover:opacity-100 p-1 rounded text-[#949ba4] hover:text-[#f23f43] transition-all"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
