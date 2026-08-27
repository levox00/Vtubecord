import { useEffect, useState } from "react";
import { fetchGoals, createGoal, updateGoal, deleteGoal } from "../lib/api";
import type { Goal } from "../types";
import { Trash2, CheckCircle2, XCircle, Target, Flag } from "lucide-react";

interface GoalsPanelProps {
  channel?: string;
}

export function GoalsPanel({ channel }: GoalsPanelProps) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [filter, setFilter] = useState<string>("active");
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (channel === "completed-goals") setFilter("completed");
    else if (channel === "active-goals") setFilter("active");
    else if (channel === "new-goal") setFilter("active");
    else setFilter("active");
  }, [channel]);

  const load = async () => {
    try {
      const data = await fetchGoals(filter || undefined);
      setGoals(data);
    } catch (e) {
      console.error("Failed to load goals", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filter]);

  const handleAdd = async () => {
    if (!newTitle.trim()) return;
    try {
      const g = await createGoal({ title: newTitle.trim(), description: newDesc.trim() });
      setGoals((prev) => [g, ...prev]);
      setNewTitle("");
      setNewDesc("");
    } catch (e) {
      console.error("Failed to create goal", e);
    }
  };

  const handleStatus = async (id: string, status: string) => {
    try {
      const updated = await updateGoal(id, status);
      setGoals((prev) => prev.map((g) => (g.id === id ? updated : g)));
    } catch (e) {
      console.error("Failed to update goal", e);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteGoal(id);
      setGoals((prev) => prev.filter((g) => g.id !== id));
    } catch (e) {
      console.error("Failed to delete goal", e);
    }
  };

  // Create form view
  if (channel === "new-goal") {
    return (
      <div className="flex flex-col h-full p-5 bg-[#313338]">
        <div className="mb-5"><p className="text-[10px] uppercase tracking-[0.14em] text-[#6d6f78]">Goals</p><h3 className="text-lg font-semibold text-[#f2f3f5] mt-1">Create New Goal</h3><p className="text-xs text-[#949ba4] mt-1">Capture something the character should work toward.</p></div>
        <div className="space-y-3 max-w-md p-4 rounded-xl bg-[#2b2d31] border border-[#3a3d43]">
          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Title</label>
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Goal title..."
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
            Create Goal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-5 overflow-hidden bg-[#313338]">
      <div className="flex-1 overflow-y-auto space-y-1">
        {loading && <p className="text-[#949ba4] text-xs">Loading...</p>}
        {!loading && goals.length === 0 && (
          <p className="text-[#949ba4] text-xs">No goals in this category.</p>
        )}
        {goals.map((g) => {
          const isCompleted = g.status === "completed";
          const isAbandoned = g.status === "abandoned";
          return (
            <div key={g.id} className="flex items-start gap-3 p-2.5 rounded hover:bg-[#2e3035] group">
              <div className={`shrink-0 w-8 h-8 rounded flex items-center justify-center bg-[#2b2d31] ${
                isCompleted ? "text-[#57f287]" : isAbandoned ? "text-[#949ba4]" : "text-[#fee75c]"
              }`}>
                {isCompleted ? <CheckCircle2 size={16} /> : isAbandoned ? <XCircle size={16} /> : <Target size={16} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-[10px] font-semibold uppercase tracking-wider ${
                    isCompleted ? "text-[#57f287]" : isAbandoned ? "text-[#949ba4]" : "text-[#fee75c]"
                  }`}>
                    {g.status}
                  </span>
                  {g.priority > 0 && (
                    <span className="flex items-center gap-0.5 text-[9px] text-[#fee75c]/60">
                      <Flag size={8} /> P{g.priority}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[#dbdee1] font-medium">{g.title}</p>
                {g.description && (
                  <p className="text-xs text-[#949ba4] mt-0.5">{g.description}</p>
                )}
              </div>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                {g.status === "active" && (
                  <>
                    <button
                      onClick={() => handleStatus(g.id, "completed")}
                      className="p-1 rounded text-[#949ba4] hover:text-[#57f287] transition-colors"
                      title="Complete"
                    >
                      <CheckCircle2 size={14} />
                    </button>
                    <button
                      onClick={() => handleStatus(g.id, "abandoned")}
                      className="p-1 rounded text-[#949ba4] hover:text-[#fee75c] transition-colors"
                      title="Abandon"
                    >
                      <XCircle size={14} />
                    </button>
                  </>
                )}
                <button
                  onClick={() => handleDelete(g.id)}
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
