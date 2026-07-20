import { useEffect, useState } from "react";

// Matches common tablet/mobile breakpoint. Below this, the sidebar and AI
// panel switch from permanent layout columns to slide-in overlays, and
// pages with fixed multi-column grids collapse to fewer/one column.
export const MOBILE_BREAKPOINT = 768;

function getIsMobile(): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth < MOBILE_BREAKPOINT;
}

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(getIsMobile);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const handler = () => setIsMobile(mql.matches);
    handler();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}
