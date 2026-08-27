import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Cpu,
  Gauge,
  HardDrive,
  MemoryStick,
  Monitor,
  RefreshCw,
  Server,
  Thermometer,
  Wifi,
  X,
  Zap,
} from "lucide-react";
import {
  fetchResourceMonitor,
  type ResourceMonitorData,
  type ResourceMonitorModel,
} from "../lib/api";

interface WebUiMetrics {
  usedHeapMb: number | null;
  heapLimitMb: number | null;
  resourceCount: number;
  domNodes: number;
  deviceMemoryGb: number | null;
  logicalCores: number | null;
  viewport: string;
  online: boolean;
}

interface PerformanceWithMemory extends Performance {
  memory?: {
    usedJSHeapSize: number;
    jsHeapSizeLimit: number;
  };
}

interface NavigatorWithMemory extends Navigator {
  deviceMemory?: number;
}

function collectWebUiMetrics(): WebUiMetrics {
  const performanceWithMemory = performance as PerformanceWithMemory;
  const memory = performanceWithMemory.memory;
  const navigatorWithMemory = navigator as NavigatorWithMemory;
  return {
    usedHeapMb: memory ? memory.usedJSHeapSize / (1024 * 1024) : null,
    heapLimitMb: memory ? memory.jsHeapSizeLimit / (1024 * 1024) : null,
    resourceCount: performance.getEntriesByType("resource").length,
    domNodes: document.getElementsByTagName("*").length,
    deviceMemoryGb: navigatorWithMemory.deviceMemory ?? null,
    logicalCores: navigator.hardwareConcurrency || null,
    viewport: `${window.innerWidth} × ${window.innerHeight}`,
    online: navigator.onLine,
  };
}

function formatMb(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${Math.round(value)} MB`;
}

function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}%`;
}

function formatLatency(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)} ms`;
}

function progressWidth(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "0%";
  return `${Math.min(100, Math.max(0, value))}%`;
}

function StatusDot({ status }: { status: string }) {
  const color = status === "online" || status === "active" ? "bg-emerald-400" : status === "configured" || status === "cloud" ? "bg-amber-400" : "bg-red-400";
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${color}`} />;
}

function ModelRow({ model }: { model: ResourceMonitorModel }) {
  return (
    <div className="rounded-md bg-[#1e1f22] px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <StatusDot status={model.status} />
          <span className="truncate text-xs font-semibold text-[#dbdee1]">{model.label}</span>
        </div>
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-[#949ba4]">{model.status}</span>
      </div>
      <div className="mt-1 truncate text-[10px] text-[#949ba4]" title={model.model}>
        {model.model} · {model.engine}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] text-[#b5bac1]">
        <Metric label="RAM" value={formatMb(model.ram_mb)} />
        <Metric label="VRAM" value={formatMb(model.vram_mb)} />
        <Metric label="CPU" value={formatPercent(model.cpu_percent)} />
      </div>
      {model.pid !== null && <div className="mt-1 text-[9px] text-[#6d7078]">PID {model.pid}</div>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="uppercase tracking-wide text-[#6d7078]">{label}</div>
      <div className="mt-0.5 text-[#dbdee1]">{value}</div>
    </div>
  );
}

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-[#949ba4]">
      {icon}
      {children}
    </div>
  );
}

export function ResourceMonitorPopover({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<ResourceMonitorData | null>(null);
  const [webUi, setWebUi] = useState<WebUiMetrics>(() => collectWebUiMetrics());
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!cancelled) setRefreshing(true);
      try {
        const next = await fetchResourceMonitor();
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Monitor unavailable");
      } finally {
        if (!cancelled) setRefreshing(false);
      }
    }

    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshVersion]);

  useEffect(() => {
    const sample = () => setWebUi(collectWebUiMetrics());
    sample();
    const timer = window.setInterval(sample, 2000);
    return () => window.clearInterval(timer);
  }, []);

  const ram = data?.host.ram;
  const gpu = data?.host.gpu;
  const heapPercent = webUi.usedHeapMb !== null && webUi.heapLimitMb ? (webUi.usedHeapMb / webUi.heapLimitMb) * 100 : null;

  return (
    <div className="absolute right-0 top-10 z-50 flex max-h-[min(80vh,680px)] w-[min(430px,calc(100vw-24px))] flex-col overflow-hidden rounded-lg border border-[#1f2023] bg-[#2b2d31] shadow-2xl shadow-black/40">
      <div className="flex items-center justify-between border-b border-[#1f2023] bg-[#313338] px-3.5 py-3">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-[#5865f2]" />
          <div>
            <div className="text-sm font-semibold text-white">Resource monitor</div>
            <div className="text-[10px] text-[#949ba4]">Live host, model, and Web UI usage</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setRefreshVersion((version) => version + 1)}
            className="rounded p-1.5 text-[#b5bac1] transition-colors hover:bg-[#35373c] hover:text-white"
            title="Refresh metrics now"
          >
            <RefreshCw size={14} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1.5 text-[#b5bac1] transition-colors hover:bg-[#35373c] hover:text-white"
            title="Close resource monitor"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="min-h-0 space-y-4 overflow-y-auto p-3.5">
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-red-400/20 bg-red-400/10 px-3 py-2 text-[11px] text-red-200">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>{error}. Backend metrics will retry automatically.</span>
          </div>
        )}

        <section>
          <SectionTitle icon={<Monitor size={12} />}>Host resources</SectionTitle>
          <div className="grid grid-cols-2 gap-2">
            <ResourceCard icon={<Cpu size={14} />} label="CPU" value={formatPercent(data?.host.cpu_percent ?? null)} detail="whole host" />
            <ResourceCard icon={<MemoryStick size={14} />} label="System RAM" value={formatMb(ram?.used_mb ?? null)} detail={ram ? `${formatPercent(ram.percent)} of ${formatMb(ram.total_mb)}` : "Unavailable"} />
            <ResourceCard icon={<HardDrive size={14} />} label="GPU VRAM" value={formatMb(gpu?.used_vram_mb ?? null)} detail={gpu?.available ? `${formatPercent(gpu.utilization_pct)} · ${gpu.name}` : "No NVIDIA GPU reported"} />
            <ResourceCard icon={<Thermometer size={14} />} label="GPU temp" value={gpu?.temperature_c !== null && gpu?.temperature_c !== undefined ? `${gpu.temperature_c}°C` : "—"} detail={gpu?.available ? "current" : "Unavailable"} />
          </div>
          {ram?.percent !== null && ram?.percent !== undefined && (
            <ProgressBar value={ram.percent} color="bg-[#5865f2]" />
          )}
        </section>

        <section>
          <SectionTitle icon={<Zap size={12} />}>Active models</SectionTitle>
          <div className="space-y-2">
            {data?.models.map((model) => <ModelRow key={model.id} model={model} />) ?? (
              <div className="rounded-md bg-[#1e1f22] px-3 py-3 text-xs text-[#949ba4]">Waiting for backend metrics…</div>
            )}
          </div>
        </section>

        {data && data.processes.length > 0 && (
          <section>
            <SectionTitle icon={<Server size={12} />}>Runtime processes</SectionTitle>
            <div className="space-y-1.5">
              {data.processes.map((process) => (
                <div key={`${process.role}-${process.pid}`} className="flex items-center justify-between gap-3 rounded-md bg-[#1e1f22] px-3 py-2 text-[10px]">
                  <div className="min-w-0">
                    <div className="truncate text-[#dbdee1]">{process.role} · {process.name}</div>
                    <div className="mt-0.5 text-[#6d7078]">PID {process.pid} · {process.status}</div>
                  </div>
                  <div className="shrink-0 text-right text-[#b5bac1]">
                    <div>{formatMb(process.ram_mb)} RAM</div>
                    <div className="mt-0.5 text-[#949ba4]">{formatMb(process.vram_mb)} VRAM · {formatPercent(process.cpu_percent)} CPU</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <SectionTitle icon={<Server size={12} />}>Local services</SectionTitle>
          <div className="space-y-1.5">
            {data?.services.map((service) => (
              <div key={service.name} className="flex items-center justify-between rounded-md bg-[#1e1f22] px-3 py-2 text-[11px]">
                <div className="flex min-w-0 items-center gap-2">
                  <StatusDot status={service.status} />
                  <span className="truncate text-[#dbdee1]">{service.name}</span>
                </div>
                <span className="shrink-0 text-[#949ba4]">{service.status === "online" ? formatLatency(service.latency_ms) : service.status}</span>
              </div>
            )) ?? <div className="text-xs text-[#949ba4]">Waiting for service checks…</div>}
          </div>
        </section>

        <section>
          <SectionTitle icon={<Gauge size={12} />}>Web UI</SectionTitle>
          <div className="grid grid-cols-2 gap-2 rounded-md bg-[#1e1f22] p-3">
            <Metric label="JS heap" value={formatMb(webUi.usedHeapMb)} />
            <Metric label="Heap limit" value={formatMb(webUi.heapLimitMb)} />
            <Metric label="DOM nodes" value={webUi.domNodes.toLocaleString()} />
            <Metric label="Resources" value={webUi.resourceCount.toLocaleString()} />
            <Metric label="Device RAM" value={webUi.deviceMemoryGb === null ? "—" : `${webUi.deviceMemoryGb} GB`} />
            <Metric label="Logical cores" value={webUi.logicalCores === null ? "—" : String(webUi.logicalCores)} />
            <Metric label="Viewport" value={webUi.viewport} />
            <Metric label="Network" value={webUi.online ? "Online" : "Offline"} />
          </div>
          {heapPercent !== null && <ProgressBar value={heapPercent} color="bg-[#57f287]" />}
        </section>

        <div className="flex items-center justify-between border-t border-[#3f4147] pt-2 text-[10px] text-[#6d7078]">
          <div className="flex items-center gap-1.5"><Wifi size={11} /> Updates every 3 seconds</div>
          <span>{data ? `Updated ${new Date(data.timestamp).toLocaleTimeString()}` : "Connecting…"}{refreshing ? " · syncing" : ""}</span>
        </div>
      </div>
    </div>
  );
}

function ResourceCard({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return (
    <div className="rounded-md bg-[#1e1f22] px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[#6d7078]">{icon}{label}</div>
      <div className="mt-1 text-sm font-semibold text-[#dbdee1]">{value}</div>
      <div className="mt-0.5 truncate text-[9px] text-[#949ba4]" title={detail}>{detail}</div>
    </div>
  );
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#1e1f22]">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: progressWidth(value) }} />
    </div>
  );
}
