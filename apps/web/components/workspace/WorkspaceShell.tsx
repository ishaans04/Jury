import Link from "next/link";

import { Logo } from "@/components/brand/Logo";

/** Frame for every signed-in screen: a floating glass top bar and a
 * full-height canvas the boardroom stage fills. */
export function WorkspaceShell({
  title,
  actions,
  children,
}: {
  title?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-3 z-40 px-3 sm:px-4">
        <nav
          aria-label="Workspace"
          className="glass mx-auto flex max-w-7xl items-center justify-between gap-3 rounded-full py-2 pl-4 pr-2"
        >
          <div className="flex min-w-0 items-center gap-3">
            <Logo href="/projects" />
            {title && (
              <>
                <span className="hidden h-5 w-px bg-[#E2D8C6] sm:block" aria-hidden />
                <span className="hidden truncate text-sm font-medium text-[#5A5348] sm:block">{title}</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-1">
            {actions}
            <Link href="/projects" className="rounded-full px-3 py-2 text-sm text-[#5A5348] hover:bg-white/70">
              Projects
            </Link>
          </div>
        </nav>
      </header>
      <main id="main" className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-3 pb-8 pt-6 sm:px-4">
        {children}
      </main>
    </div>
  );
}
