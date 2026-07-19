import { useState } from "react";
import { X } from "lucide-react";
import {
  connectJira,
  connectServiceNow,
  connectOutlook,
  type ConnectionProvider,
} from "../../api/taskpilot";

type Field = { key: string; label: string; placeholder: string; type?: string };

const FORM_CONFIG: Record<string, { title: string; help: string; fields: Field[] }> = {
  jira: {
    title: "Connect Jira",
    help: "Create an API token at id.atlassian.com/manage-profile/security/api-tokens",
    fields: [
      { key: "url", label: "Jira URL", placeholder: "https://yourcompany.atlassian.net" },
      { key: "email", label: "Email", placeholder: "you@company.com" },
      { key: "api_token", label: "API Token", placeholder: "••••••••••••", type: "password" },
    ],
  },
  servicenow: {
    title: "Connect ServiceNow",
    help: "Use your ServiceNow instance credentials",
    fields: [
      { key: "url", label: "Instance URL", placeholder: "https://yourinstance.service-now.com" },
      { key: "username", label: "Username", placeholder: "admin" },
      { key: "password", label: "Password", placeholder: "••••••••••••", type: "password" },
    ],
  },
  outlook: {
    title: "Connect Outlook",
    help: "Register an app at portal.azure.com — App registrations — and paste its details below",
    fields: [
      { key: "client_id", label: "Client ID", placeholder: "Azure app client ID" },
      { key: "client_secret", label: "Client Secret", placeholder: "••••••••••••", type: "password" },
      { key: "tenant_id", label: "Tenant ID", placeholder: "Azure AD tenant ID" },
    ],
  },
};

export function ConnectFormModal({
  provider,
  onClose,
  onConnected,
}: {
  provider: Extract<ConnectionProvider, "jira" | "servicenow" | "outlook">;
  onClose: () => void;
  onConnected: () => void;
}) {
  const config = FORM_CONFIG[provider];
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (provider === "jira") {
        await connectJira(values.url || "", values.email || "", values.api_token || "");
      } else if (provider === "servicenow") {
        await connectServiceNow(values.url || "", values.username || "", values.password || "");
      } else {
        await connectOutlook(values.client_id || "", values.client_secret || "", values.tenant_id || "");
      }
      onConnected();
      onClose();
    } catch (err: any) {
      const msg = String(err?.message || "");
      const match = msg.match(/detail["\s:]+(.+)$/i);
      setError(match ? match[1].replace(/["}]+$/, "") : "Could not connect — please check your credentials.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(13,13,13,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        style={{
          width: 380, background: "#FFFFFF", borderRadius: 18, padding: 24,
          border: "1px solid #E9E4D8", boxShadow: "0 12px 40px rgba(0,0,0,0.12)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>{config.title}</h3>
          <button type="button" onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer" }}>
            <X size={18} color="#7A7A7A" />
          </button>
        </div>
        <p style={{ fontSize: 12, color: "#7A7A7A", margin: "4px 0 16px" }}>{config.help}</p>

        {config.fields.map((f) => (
          <div key={f.key} style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#3A3A3A" }}>
              {f.label}
            </label>
            <input
              type={f.type || "text"}
              required
              placeholder={f.placeholder}
              value={values[f.key] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              style={{
                width: "100%", boxSizing: "border-box", padding: "9px 12px",
                borderRadius: 10, border: "1px solid #E9E4D8", fontSize: 13,
                background: "#FCFAF4", outline: "none",
              }}
            />
          </div>
        ))}

        {error && (
          <div style={{ background: "#FBE4E4", color: "#B23B3B", fontSize: 12, padding: "8px 10px", borderRadius: 8, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%", padding: "11px 16px", borderRadius: 12, border: "none",
            background: "#0D0D0D", color: "#FFF", fontSize: 14, fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "Connecting…" : "Connect"}
        </button>
      </form>
    </div>
  );
}
