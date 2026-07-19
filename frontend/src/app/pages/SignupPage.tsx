import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useAuth } from "../context/AuthContext";
import { styles } from "./LoginPage";

export function SignupPage() {
  const { signup, demoLogin } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await signup(email, password, name);
      navigate("/dashboard", { replace: true });
    } catch (err: any) {
      setError(
        err?.message?.includes("409")
          ? "An account with this email already exists."
          : "Something went wrong. Please try again."
      );
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
        <h1 style={styles.title}>Create your account</h1>
        <p style={styles.subtitle}>Start letting TaskPilot triage your work</p>

        <label style={styles.label}>Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={styles.input}
          placeholder="Ada Lovelace"
        />

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
          placeholder="At least 8 characters"
        />

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={busy} style={styles.button}>
          {busy ? "Creating account…" : "Create account"}
        </button>

        <button type="button" onClick={tryDemo} disabled={demoBusy} style={styles.demoButton}>
          {demoBusy ? "Loading demo…" : "Try the demo instead"}
        </button>

        <p style={styles.footerText}>
          Already have an account? <Link to="/login" style={styles.link}>Log in</Link>
        </p>
      </form>
    </div>
  );
}
