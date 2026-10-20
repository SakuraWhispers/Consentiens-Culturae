/**
 * Logo — PLACEHOLDER while the human prepares the real SVG component.
 * Drawn to read like the raster lockup (interlocked knot + sans wordmark).
 * Replace the <svg> knot path with the supplied component; the layout props
 * stay identical.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 64" className={className} aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="3.2">
        <path d="M24 4 C15 14, 11 22, 11 30 C22 30, 26 22, 24 4 Z" />
        <path d="M24 4 C33 14, 37 22, 37 30 C26 30, 22 22, 24 4 Z" />
        <path d="M11 30 C7 38, 11 47, 17 52 C24 47, 22 36, 11 30 Z" />
        <path d="M37 30 C41 38, 37 47, 31 52 C24 47, 26 36, 37 30 Z" />
        <path d="M17 52 C22 57, 26 58, 24 60 C28 58, 32 57, 31 52" opacity="0" />
        <path d="M17 52 C20 58, 28 60, 24 60 C33 60, 31 52, 31 52" />
        <path d="M24 30 C19 36, 19 44, 24 50 C29 44, 29 36, 24 30 Z" />
      </g>
    </svg>
  );
}

export function Logo({
  className = "",
  markClass = "",
}: {
  className?: string;
  markClass?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark className={markClass || "h-10 w-8"} />
      <span className="font-sans font-semibold text-ink leading-[1.05]">
        Consentiens
        <br />
        Culturae
      </span>
    </span>
  );
}

export function LogoPlaceholderNotice() {
  return null;
}
