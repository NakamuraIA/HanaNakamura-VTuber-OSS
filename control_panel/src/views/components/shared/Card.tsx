import { ReactNode } from "react";

type CardProps = {
  children: ReactNode;
  className?: string;
  /** Adds a subtle accent border + glow on hover (for interactive/clickable cards). */
  hover?: boolean;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  title?: string;
};

/**
 * Standard surface card for the Hana Control Panel.
 *
 * Uses the brand tokens (--surface-1, --border-strong, --radius-card, --elev-card)
 * so every card looks the same and reacts to the theme. Replaces the dozens of
 * copy-pasted `bg-[rgba(0,0,0,0.4)] backdrop-blur-md border rounded-2xl p-6` blocks.
 */
export function Card({ children, className = "", hover = false, onClick, onMouseEnter, onMouseLeave, title }: CardProps) {
  return (
    <div
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      title={title}
      className={[
        "relative overflow-hidden backdrop-blur-md",
        "bg-[var(--surface-1)] border border-[var(--border-strong)]",
        "rounded-[var(--radius-card)] p-[var(--space-card)] shadow-[var(--elev-card)]",
        hover ? "group transition-all hover:border-[var(--accent)]/50 hover:shadow-[0_0_30px_var(--purple-dark)] cursor-pointer" : "",
        className,
      ].join(" ")}
    >
      {children}
    </div>
  );
}
