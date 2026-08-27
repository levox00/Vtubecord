import { useEffect, useState } from "react";
import { fetchSkills, createSkill, updateSkill, deleteSkill } from "../lib/api";
import type { Skill } from "../types";
import { Trash2, ArrowUp, Zap } from "lucide-react";

interface SkillsPanelProps {
  channel?: string;
}

export function SkillsPanel({ channel }: SkillsPanelProps) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const data = await fetchSkills();
      setSkills(data);
    } catch (e) {
      console.error("Failed to load skills", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    if (!newName.trim()) return;
    try {
      const s = await createSkill({ name: newName.trim(), description: newDesc.trim() });
      setSkills((prev) => [...prev, s]);
      setNewName("");
      setNewDesc("");
    } catch (e) {
      console.error("Failed to create skill", e);
    }
  };

  const handleLevelUp = async (id: string, current: number) => {
    const newProf = Math.min(1.0, current + 0.1);
    try {
      const updated = await updateSkill(id, { proficiency: newProf });
      setSkills((prev) => prev.map((s) => (s.id === id ? updated : s)));
    } catch (e) {
      console.error("Failed to update skill", e);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteSkill(id);
      setSkills((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      console.error("Failed to delete skill", e);
    }
  };

  // Create form view
  if (channel === "new-skill") {
    return (
      <div className="flex flex-col h-full p-5 bg-[#313338]">
        <div className="mb-5"><p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">Skills</p><h3 className="text-lg font-semibold text-[#f2f3f5] mt-1">Add New Skill</h3><p className="text-xs text-[#949ba4] mt-1">Track learned capabilities and proficiency over time.</p></div>
        <div className="space-y-3 max-w-md p-4 rounded-xl bg-[#2b2d31] border border-[#3a3d43]">
          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Name</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Skill name..."
              className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
            />
          </div>
          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Description</label>
            <input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
            />
          </div>
          <button
            onClick={handleAdd}
            className="px-4 py-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-sm font-medium transition-colors"
          >
            Add Skill
          </button>
        </div>
      </div>
    );
  }

  // Proficiency overview
  if (channel === "proficiency") {
    const sorted = [...skills].sort((a, b) => b.proficiency - a.proficiency);
    return (
      <div className="flex flex-col h-full p-4 overflow-hidden">
        <h3 className="text-sm font-semibold text-white mb-3">Skill Proficiency</h3>
        <div className="flex-1 overflow-y-auto space-y-2">
          {sorted.map((s) => {
            const pct = Math.round(s.proficiency * 100);
            return (
              <div key={s.id} className="p-3 rounded bg-[#2b2d31]">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm text-[#dbdee1] font-medium">{s.name}</span>
                  <span className="text-xs text-[#949ba4]">{pct}%</span>
                </div>
                <div className="w-full h-2 bg-[#1e1f22] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${pct}%`,
                      backgroundColor:
                        pct >= 80 ? "#57f287" : pct >= 50 ? "#5865f2" : pct >= 25 ? "#fee75c" : "#f23f43",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Default: all skills list
  return (
    <div className="flex flex-col h-full p-5 overflow-hidden bg-[#313338]">
      <div className="flex-1 overflow-y-auto space-y-1">
        {loading && <p className="text-[#949ba4] text-xs">Loading...</p>}
        {!loading && skills.length === 0 && (
          <p className="text-[#949ba4] text-xs">No skills yet.</p>
        )}
        {skills.map((s) => {
          const pct = Math.round(s.proficiency * 100);
          return (
            <div key={s.id} className="flex items-start gap-3 p-2.5 rounded hover:bg-[#2e3035] group">
              <div className="shrink-0 w-8 h-8 rounded flex items-center justify-center bg-[#2b2d31] text-[#57f287]">
                <Zap size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-sm text-[#dbdee1] font-medium">{s.name}</span>
                  <span className="text-[10px] text-[#949ba4]">Lv.{Math.round(s.proficiency * 10)}</span>
                </div>
                {s.description && (
                  <p className="text-xs text-[#949ba4] mb-1">{s.description}</p>
                )}
                <div className="w-full h-1 bg-[#1e1f22] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${pct}%`,
                      backgroundColor:
                        pct >= 80 ? "#57f287" : pct >= 50 ? "#5865f2" : pct >= 25 ? "#fee75c" : "#f23f43",
                    }}
                  />
                </div>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-[9px] text-[#6d6f78]">{pct}%</span>
                  <span className="text-[9px] text-[#6d6f78]">{s.experience} XP</span>
                </div>
              </div>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                <button
                  onClick={() => handleLevelUp(s.id, s.proficiency)}
                  className="p-1 rounded text-[#949ba4] hover:text-[#5865f2] transition-colors"
                  title="Level up"
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  onClick={() => handleDelete(s.id)}
                  className="p-1 rounded text-[#949ba4] hover:text-[#f23f43] transition-colors"
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
