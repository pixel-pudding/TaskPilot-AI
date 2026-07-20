import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useIsMobile } from "../../hooks/useIsMobile";

type LayoutContextType = {
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  toggleSidebar: () => void;
  panelOpen: boolean;
  setPanelOpen: (v: boolean) => void;
  togglePanel: () => void;
  isMobile: boolean;
};

const LayoutContext = createContext<LayoutContextType | null>(null);

export function LayoutProvider({ children }: { children: ReactNode }) {
  const isMobile = useIsMobile();
  // Desktop: both open by default (existing behavior, unchanged). Mobile:
  // both closed by default — on a phone-width screen the sidebar (240px)
  // and AI panel (340px) alone add up to more than the viewport, so they
  // start as hidden overlays instead of permanent layout columns.
  const [sidebarOpen, setSidebarOpen] = useState(!isMobile);
  const [panelOpen, setPanelOpen] = useState(!isMobile);

  // If the viewport crosses the breakpoint (resize, or rotating a device),
  // snap to that mode's default rather than leaving e.g. a desktop-opened
  // overlay stuck open after shrinking to mobile width.
  useEffect(() => {
    setSidebarOpen(!isMobile);
    setPanelOpen(!isMobile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile]);

  return (
    <LayoutContext.Provider value={{
      sidebarOpen,
      setSidebarOpen,
      toggleSidebar: () => setSidebarOpen(v => !v),
      panelOpen,
      setPanelOpen,
      togglePanel: () => setPanelOpen(v => !v),
      isMobile,
    }}>
      {children}
    </LayoutContext.Provider>
  );
}

export function useLayout() {
  const ctx = useContext(LayoutContext);
  if (!ctx) throw new Error("useLayout must be used inside LayoutProvider");
  return ctx;
}
