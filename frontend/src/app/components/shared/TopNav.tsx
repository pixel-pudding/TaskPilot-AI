import { useState } from "react";
import { Search, Bell, Settings, LogOut } from "lucide-react";
import { useNavigate } from "react-router";
import { useLayout } from "./LayoutContext";
import { useAuth } from "../../context/AuthContext";

export function TopNav() {
  const navigate = useNavigate();
  const { togglePanel } = useLayout();
  const { user, logout } = useAuth();
  const [searchVal, setSearchVal] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  const handleSearch = () => {
    const q = searchVal.trim();
    if (!q) return;
    navigate(`/inbox?search=${encodeURIComponent(q)}`);
  };

  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div style={{
      height: 60, flexShrink: 0,
      display: "flex", alignItems: "center",
      gap: 12, padding: "0 16px",
      borderBottom: "1px solid #E9E4D8",
      background: "#F6F2E9",
    }}>
      <div style={{
        flex: 1, display: "flex", alignItems: "center", gap: 8,
        background: "#FFFFFF", borderRadius: 14, padding: "8px 14px",
        border: "1px solid #E9E4D8", maxWidth: 480,
      }}>
        <Search size={15} color="#B0A8A0" />
        <input
          value={searchVal}
          onChange={(e) => setSearchVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Search tasks, emails, blockers..."
          style={{
            flex: 1, border: "none", outline: "none",
            background: "none", fontSize: 13, color: "#111111",
          }}
        />
      </div>

      {user?.id === "demo" && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            background: "#F5D66E", color: "#0D0D0D", fontSize: 11, fontWeight: 700,
            padding: "6px 12px", borderRadius: 10, fontFamily: "'IBM Plex Mono', monospace",
            textTransform: "uppercase", letterSpacing: "0.04em",
          }}>
            Demo Mode — shared showcase data
          </span>
          <button
            onClick={() => navigate("/signup")}
            style={{
              background: "#0D0D0D", color: "#FFFFFF", border: "none",
              padding: "8px 14px", borderRadius: 10, fontSize: 12, fontWeight: 600,
              cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace", whiteSpace: "nowrap",
            }}
          >
            Sign up for your own data
          </button>
        </div>
      )}

      <button
        onClick={() => navigate("/notifications")}
        style={{
          width: 36, height: 36, borderRadius: 10,
          border: "1px solid #E9E4D8", background: "#FFFFFF",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", position: "relative",
        }}
      >
        <Bell size={16} color="#7A7A7A" />
      </button>

      <button
        onClick={() => navigate("/settings")}
        style={{
          width: 36, height: 36, borderRadius: 10,
          border: "1px solid #E9E4D8", background: "#FFFFFF",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer",
        }}
      >
        <Settings size={16} color="#7A7A7A" />
      </button>

      <div style={{ position: "relative" }}>
        <div
          onClick={() => setMenuOpen((v) => !v)}
          style={{
            width: 36, height: 36, borderRadius: 10,
            background: "#0D0D0D",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#FFFFFF", fontSize: 13, fontWeight: 600,
            fontFamily: "'IBM Plex Mono', monospace", cursor: "pointer",
          }}
          title={user?.email}
        >
          {initial}
        </div>
        {menuOpen && (
          <div style={{
            position: "absolute", top: 44, right: 0, zIndex: 20,
            background: "#FFFFFF", border: "1px solid #E9E4D8", borderRadius: 12,
            boxShadow: "0 8px 24px rgba(0,0,0,0.08)", minWidth: 180, padding: 8,
          }}>
            <div style={{ padding: "6px 10px", fontSize: 12, color: "#7A7A7A" }}>
              {user?.email}
            </div>
            <button
              onClick={handleLogout}
              style={{
                width: "100%", display: "flex", alignItems: "center", gap: 8,
                padding: "8px 10px", borderRadius: 8, border: "none",
                background: "transparent", color: "#B23B3B", fontSize: 13,
                cursor: "pointer", textAlign: "left",
              }}
            >
              <LogOut size={14} /> Log out
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
