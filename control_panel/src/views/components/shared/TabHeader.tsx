import { ReactNode } from "react";

type TabHeaderProps = {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  /** Optional content rendered on the right (tabs, buttons, badges). */
  actions?: ReactNode;
  className?: string;
};

/**
 * Standard tab header for the Hana Control Panel.
 *
 * One consistent look across every tab: an accent icon chip, a gradient title and
 * a muted subtitle. Replaces the ~10 hand-rolled headers. Uses brand tokens so the
 * theme drives the colors.
 */
export function TabHeader({ icon, title, subtitle, actions, className = "" }: TabHeaderProps) {
  return (
    <div className={`mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between ${className}`}>
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[var(--accent)]/40 bg-[var(--purple-dark)] text-[var(--accent)] shadow-[0_0_15px_var(--purple-dark)]">
          {icon}
        </div>
        <div className="min-w-0">
          <h2 className="bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] bg-clip-text text-2xl font-extrabold text-transparent transition-all duration-500">
            {title}
          </h2>
          {subtitle && (
            <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
