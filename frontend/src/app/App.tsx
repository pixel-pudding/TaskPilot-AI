import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { DashboardLayout } from "./components/shared/DashboardLayout";
import { Screen0 } from "./components/screens/Screen0";
import { Dashboard } from "./components/screens/Dashboard";
import { Inbox } from "./components/screens/Inbox";
import { HiddenTasks } from "./components/screens/HiddenTasks";
import { DedupGroups } from "./components/screens/DedupGroups";
import { Planner } from "./components/screens/Planner";
import { Timeline } from "./components/screens/Timeline";
import { Priorities } from "./components/screens/Priorities";
import { Dependencies } from "./components/screens/Dependencies";
import { Reports } from "./components/screens/Reports";
import { Integrations } from "./components/screens/Integrations";
import { Notifications } from "./components/screens/Notifications";
import { Settings } from "./components/screens/Settings";
import { Screen6 } from "./components/screens/Screen6";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { AuthProvider, useAuth } from "./context/AuthContext";

function DL({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <DashboardLayout>{children}</DashboardLayout>
    </ErrorBoundary>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "#7A7A7A" }}>
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function Landing() {
  const { user, loading, demoLogin } = useAuth();
  const navigate = useNavigate();
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  if (loading) return null;
  if (user) return <Navigate to="/dashboard" replace />;

  const handleDemo = async () => {
    if (demoBusy) return;
    setDemoBusy(true);
    setDemoError(null);
    try {
      await demoLogin();
      navigate("/dashboard", { replace: true });
    } catch (err: any) {
      // Swallowing this silently used to mean the button just looked
      // broken — no navigation, no error, nothing — when e.g. the backend
      // URL wasn't reachable. Surface exactly what happened instead.
      setDemoError(
        err?.message
          ? `Couldn't start the demo: ${err.message}`
          : "Couldn't start the demo. Please try again."
      );
      setDemoBusy(false);
    }
  };

  return (
    <>
      {demoError && (
        <div style={{
          position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
          zIndex: 1000, background: "#FBE4E4", color: "#B23B3B",
          border: "1px solid #F0A8D6", borderRadius: 12, padding: "10px 18px",
          fontSize: 13, boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
        }}>
          {demoError}
        </div>
      )}
      <Screen0
        onStart={() => navigate("/signup")}
        onDemo={handleDemo}
      />
    </>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/dashboard" element={<RequireAuth><DL><Dashboard /></DL></RequireAuth>} />
      <Route path="/inbox" element={<RequireAuth><DL><Inbox /></DL></RequireAuth>} />
      <Route path="/hidden" element={<RequireAuth><DL><HiddenTasks /></DL></RequireAuth>} />
      <Route path="/dedup-groups" element={<RequireAuth><DL><DedupGroups /></DL></RequireAuth>} />
      <Route path="/planner" element={<RequireAuth><DL><Planner /></DL></RequireAuth>} />
      <Route path="/timeline" element={<RequireAuth><DL><Timeline /></DL></RequireAuth>} />
      <Route path="/priorities" element={<RequireAuth><DL><Priorities /></DL></RequireAuth>} />
      <Route path="/dependencies" element={<RequireAuth><DL><Dependencies /></DL></RequireAuth>} />
      <Route path="/reports" element={<RequireAuth><DL><Reports /></DL></RequireAuth>} />
      <Route path="/integrations" element={<RequireAuth><DL><Integrations /></DL></RequireAuth>} />
      <Route path="/notifications" element={<RequireAuth><DL><Notifications /></DL></RequireAuth>} />
      <Route path="/settings" element={<RequireAuth><DL><Settings /></DL></RequireAuth>} />
      <Route path="/chat" element={<RequireAuth><DL><ChatPage /></DL></RequireAuth>} />
      <Route path="/traces" element={<RequireAuth><DL><Screen6 /></DL></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
