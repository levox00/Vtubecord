import { Wrench } from "lucide-react";

interface ToolCallIndicatorsProps {
  tools?: string[] | null;
  className?: string;
}

/** A compact, shared indicator for every tool executed during a response. */
export function ToolCallIndicators({ tools, className = "" }: ToolCallIndicatorsProps) {
  const names = Array.from(new Set((tools || []).filter((tool): tool is string => Boolean(tool))));
  if (names.length === 0) return null;

  return (
    <div
      className={`flex min-w-0 flex-wrap items-center gap-1.5 ${className}`}
      role="status"
      aria-label={`AI used ${names.length === 1 ? "tool" : "tools"}: ${names.join(", ")}`}
    >
      {names.map((tool) => (
        <span
          key={tool}
          title={`AI used tool: ${tool}`}
          className="inline-flex min-w-0 items-center gap-1 rounded bg-[#5865f2]/20 px-1.5 py-0.5 text-[10px] font-mono text-[#aeb8ff]"
        >
          <Wrench size={10} className="shrink-0" aria-hidden="true" />
          <span className="truncate">{tool}</span>
        </span>
      ))}
    </div>
  );
}
