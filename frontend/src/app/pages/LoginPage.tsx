import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const { login, demoLogin } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err: any) {
      setError(err?.message?.includes("401") ? "Incorrect email or password." : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const tryDemo = async () => {
    if (demoBusy) return;
    setDemoBusy(true);
    setError(null);
    try {
      await demoLogin();
      navigate("/dashboard", { replace: true });
    } catch {
      setError("Couldn't start the demo. Please try again.");
      setDemoBusy(false);
    }
  };

  return (
    <div style={styles.page}>
      <form onSubmit={submit} style={styles.card}>
        <h1 style={styles.title}>Welcome back</h1>
        <p style={styles.subtitle}>Log in to your TaskPilot account</p>

        <label style={styles.label}>Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={styles.input}
          placeholder="you@company.com"
        />

        <label style={styles.label}>Password</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={styles.input}
          placeholder="••••••••"
        />

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={busy} style={styles.button}>
          {busy ? "Logging in…" : "Log in"}
        </button>

        <button type="button" onClick={tryDemo} disabled={demoBusy} style={styles.demoButton}>
          {demoBusy ? "Loading demo…" : "Try the demo instead"}
        </button>

        <p style={styles.footerText}>
          Don't have an account? <Link to="/signup" style={styles.link}>Sign up</Link>
        </p>
      </form>
    </div>
  );
}

export const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#FAF7EF",
    fontFamily: "inherit",
  },
  card: {
    width: 380,
    background: "#FFFFFF",
    border: "1px solid #E9E4D8",
    borderRadius: 20,
    padding: "36px 32px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.06)",
    display: "flex",
    flexDirection: "column",
  },
  title: { margin: 0, fontSize: 24, fontWeight: 700, color: "#0D0D0D" },
  subtitle: { margin: "6px 0 24px", fontSize: 14, color: "#7A7A7A" },
  label: { fontSize: 13, fontWeight: 600, color: "#3A3A3A", marginBottom: 6, marginTop: 14 },
  input: {
    padding: "11px 14px",
    borderRadius: 12,
    border: "1px solid #E9E4D8",
    fontSize: 14,
    outline: "none",
    background: "#FCFAF4",
  },
  button: {
    marginTop: 22,
    padding: "12px 16px",
    borderRadius: 12,
    border: "none",
    background: "#0D0D0D",
    color: "#FFF",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
  },
  demoButton: {
    marginTop: 10,
    padding: "12px 16px",
    borderRadius: 12,
    border: "1px solid #E9E4D8",
    background: "#FFFFFF",
    color: "#0D0D0D",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
  },
  error: {
    marginTop: 14,
    padding: "10px 12px",
    borderRadius: 10,
    background: "#FBE4E4",
    color: "#B23B3B",
    fontSize: 13,
  },
  footerText: { marginTop: 20, fontSize: 13, color: "#7A7A7A", textAlign: "center" },
  link: { color: "#0D0D0D", fontWeight: 600, textDecoration: "underline" },
};
