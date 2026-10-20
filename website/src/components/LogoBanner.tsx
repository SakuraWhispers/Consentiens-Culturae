import Image from "next/image";

/**
 * Logo banner: the human-supplied `logo+tagline.png` (knot + wordmark +
 * "Cultura ducit, Ratio iudicat", cream ground). Use as one asset and drop the
 * separately typeset tagline (human request, 2026-10-20).
 *
 * height  — rendered height in px (the asset is 728x324, aspect 2.25:1)
 * Renders at 2x density for crispness on retina screens.
 */
export function LogoBanner({
  height,
  className = "",
  priority = false,
}: {
  height: number;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src="/logo-tagline.png"
      alt="Consentiens Culturae — Cultura ducit, Ratio iudicat"
      width={height * 2.25}
      height={height}
      priority={priority}
      className={`object-contain ${className}`}
    />
  );
}
