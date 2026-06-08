import { ReactNode } from "react";
import { Loader2 } from "lucide-react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
type ButtonSize = "sm" | "md";

type ButtonProps = {
  children?: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Optional leading icon (lucide element). */
  icon?: ReactNode;
  /** Shows a spinner and disables the button. */
  loading?: boolean;
  disabled?: boolean;
  /** Render as a square icon-only button. */
  iconOnly?: boolean;
  className?: string;
  title?: string;
  onMouseEnter?: () => void;
};

const VARIANTS: Record<ButtonVariant, string> = {
  // Accent gradient — main actions.
  primary:
    "bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] text-white shadow-[0_0_18px_var(--purple-dark)] hover:brightness-110",
  // Neutral surface — supporting actions.
  secondary:
    "bg-white/5 border border-white/10 text-[var(--text-secondary)] hover:bg-white/10 hover:text-white",
  // Transparent — tertiary / inline.
  ghost:
    "bg-transparent text-[var(--text-muted)] hover:bg-white/5 hover:text-white",
  // Destructive.
  danger:
    "bg-[var(--danger)]/15 border border-[var(--danger)]/30 text-[var(--danger)] hover:bg-[var(--danger)]/25",
  // Confirmation / positive.
  success:
    "bg-[var(--success)]/15 border border-[var(--success)]/30 text-[var(--success)] hover:bg-[var(--success)]/25",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-[10px]",
  md: "px-5 py-2.5 text-sm",
};

/**
 * Standard button for the Hana Control Panel.
 *
 * One consistent shape, radius and interaction across variants/sizes — replaces
 * the scattered hand-rolled pills. Uses brand tokens so it follows the theme.
 */
export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  size = "md",
  icon,
  loading = false,
  disabled = false,
  iconOnly = false,
  className = "",
  title,
  onMouseEnter,
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <button
      type={type}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      disabled={isDisabled}
      title={title}
      className={[
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)]",
        "font-black uppercase tracking-wider transition-all active:scale-95",
        "disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100",
        iconOnly ? (size === "sm" ? "p-1.5" : "p-2.5") : SIZES[size],
        VARIANTS[variant],
        className,
      ].join(" ")}
    >
      {loading ? <Loader2 size={size === "sm" ? 14 : 16} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}
