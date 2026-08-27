import { useEffect, useRef } from "react";

export interface ContextMenuItem {
  label: string;
  icon: React.ElementType;
  onClick: () => void;
  danger?: boolean;
  separator?: boolean;
  disabled?: boolean;
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  // Adjust position to stay within viewport
  useEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const menu = menuRef.current;
    if (rect.right > window.innerWidth) {
      menu.style.left = `${window.innerWidth - rect.width - 8}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menu.style.top = `${window.innerHeight - rect.height - 8}px`;
    }
  }, [x, y]);

  return (
    <div
      ref={menuRef}
      className="fixed z-[100] min-w-[180px] py-1.5 bg-[#111214] border border-[#1f2023] rounded-lg shadow-xl animate-in fade-in zoom-in-95 duration-75"
      style={{ left: x, top: y }}
    >
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="my-1 border-t border-[#1f2023]" />
        ) : (
          <button
            key={i}
            onClick={() => {
              item.onClick();
              onClose();
            }}
            disabled={item.disabled}
            className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 text-sm transition-colors ${
              item.danger
                ? "text-[#f23f43] hover:bg-[#f23f43] hover:text-white"
                : "text-[#b5bac1] hover:bg-[#5865f2] hover:text-white"
            } ${item.disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
          >
            <item.icon size={15} />
            <span>{item.label}</span>
          </button>
        )
      )}
    </div>
  );
}
