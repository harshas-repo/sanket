/**
 * One media query, read live.
 *
 * The layout breakpoints already live in `base.css`; this exists for the single decision CSS
 * cannot make - whether to render a component at all. The shell uses it for the mobile
 * "more sections" bar, so `NAV_BREAKPOINT` below is the same number the stylesheet uses for
 * `.tabbar` / `.header .nav`. Two copies of one number is a smell; it is the cheaper of the
 * two options here, because the alternative is driving layout from JS entirely.
 */

import { useEffect, useState } from "react";

export const NAV_BREAKPOINT = 960;

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

export function useIsNarrow(): boolean {
  return useMediaQuery(`(max-width: ${NAV_BREAKPOINT - 1}px)`);
}
