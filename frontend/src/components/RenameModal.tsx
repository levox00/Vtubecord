import { useState, useEffect, useRef } from "react";
import { X } from "lucide-react";

interface RenameModalProps {
  title: string;
  currentValue: string;
  onRename: (newValue: string) => void;
  onClose: () => void;
}

export function RenameModal({ title, currentValue, onRename, onClose }: RenameModalProps) {
  const [value, setValue] = useState(currentValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (trimmed && trimmed !== currentValue) {
      onRename(trimmed);
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-[#2b2d31] rounded-lg border border-[#1f2023] shadow-2xl w-[400px] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1f2023]">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="p-1 rounded text-[#949ba4] hover:text-[#dbdee1] hover:bg-[#35373c] transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">New Name</label>
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className="w-full mt-1.5 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2.5 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
          />
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#1f2023] bg-[#2b2d31]">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded text-sm text-[#b5bac1] hover:text-[#dbdee1] hover:bg-[#35373c] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!value.trim() || value.trim() === currentValue}
            className="px-4 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Rename
          </button>
        </div>
      </div>
    </div>
  );
}
