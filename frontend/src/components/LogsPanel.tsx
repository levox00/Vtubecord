import { useEffect, useState, useCallback } from "react";
import { fetchLogs, clearLogs, type LogEntry } from "../lib/api";
import { Bell, Trash2, Loader2, RefreshCw, Filter } from "lucide-react";

const LEVEL_COLORS: Record<string, string> = {
  info: "text-[#5865f2]",
  warning: "text-[#fee75c]",
  error: "text-[#f23f43]",
  debug: "text-[#949ba4]",
};

const LEVEL_BG: Record<string, string> = {
  info: "bg-[#5865f2]/10",
  warning: "bg-[#fee75c]/10",
  error: "bg-[#f23f43]/10",
  debug: "bg-[#949ba4]/10",
};

export function LogsPanel() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const load = useCallback(async () => {
    try {
      const data = await fetchLogs(
        200,
        filter === "all" ? undefined : filter,
        sourceFilter === "all" ? undefined : sourceFilter,
      );
      setLogs(data);
    } catch (e) {
      console.error("Failed to fetch logs", e);
    } finally {
      setLoading(false);
    }
  }, [filter, sourceFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(load, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, load]);

  async function handleClear() {
    if (!confirm("Clear all logs?")) return;
    await clearLogs();
    setLogs([]);
  }

  function formatTime(ts: string) {
    const d = new Date(ts);
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-[#313338]">
      {/* Header bar */}
      <div className="sticky top-0 z-10 bg-[#2b2d31] border-b border-[#3a3d43] px-5 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell size={16} className="text-[#fee75c]" />
            <span className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">
              System Logs
            </span>
            <span className="text-[10px] text-[#949ba4]">
              ({logs.length} {logs.length === 1 ? "entry" : "entries"})
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <Filter size={12} className="text-[#949ba4]" />
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="bg-[#1e1f22] border border-[#1f2023] rounded px-2 py-1 text-[10px] text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
              >
                <option value="all">All Levels</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="error">Error</option>
                <option value="debug">Debug</option>
              </select>
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                className="bg-[#1e1f22] border border-[#1f2023] rounded px-2 py-1 text-[10px] text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
                title="Filter by subsystem"
              >
                <option value="all">All Sources</option>
                <option value="discord_bridge">Discord Bridge</option>
                <option value="discord_voice">Discord Voice</option>
                <option value="discord_integration">Discord Settings</option>
              </select>
            </div>
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] transition-colors ${
                autoRefresh
                  ? "bg-[#23a55a]/20 text-[#23a55a]"
                  : "bg-[#3f4147] text-[#949ba4]"
              }`}
              title={autoRefresh ? "Auto-refresh on" : "Auto-refresh off"}
            >
              <RefreshCw size={10} className={autoRefresh ? "animate-spin" : ""} />
              {autoRefresh ? "Live" : "Paused"}
            </button>
            <button
              onClick={load}
              className="p-1.5 rounded hover:bg-[#3f4147] text-[#949ba4] hover:text-[#dbdee1] transition-colors"
              title="Refresh now"
            >
              <RefreshCw size={12} />
            </button>
            <button
              onClick={handleClear}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-[#3f4147] hover:bg-[#f23f43]/20 text-[#949ba4] hover:text-[#f23f43] transition-colors"
              title="Clear all logs"
            >
              <Trash2 size={10} /> Clear
            </button>
          </div>
        </div>
      </div>

      {/* Logs list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={20} className="text-[#5865f2] animate-spin" />
          </div>
        ) : logs.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Bell size={32} className="text-[#3f4147] mx-auto mb-2" />
              <p className="text-sm text-[#949ba4]">No log entries yet</p>
              <p className="text-[10px] text-[#6d6f78] mt-1">
                System events will appear here as you use the app
              </p>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-[#1f2023]">
            {logs.map((log, i) => (
              <div
                key={i}
                className="px-4 py-2 hover:bg-[#2b2d31] transition-colors group"
              >
                <div className="flex items-start gap-3">
                  <span className="text-[10px] text-[#6d6f78] font-mono shrink-0 mt-0.5 w-16">
                    {formatTime(log.timestamp)}
                  </span>
                  <span
                    className={`text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded shrink-0 ${
                      LEVEL_BG[log.level] || "bg-[#3f4147]"
                    } ${LEVEL_COLORS[log.level] || "text-[#949ba4]"}`}
                  >
                    {log.level}
                  </span>
                  <span className="text-[10px] text-[#b5bac1] font-medium shrink-0 min-w-[60px]">
                    {log.source}
                  </span>
                  <span className="text-[11px] text-[#dbdee1] flex-1 break-all">
                    {log.message}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
