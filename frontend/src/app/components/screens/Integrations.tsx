import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Link2, Plug, CheckCircle, XCircle, RefreshCw, AlertCircle, Trash2 } from "lucide-react";
import { Card } from "../shared/Card";
import { ConnectFormModal } from "../shared/ConnectFormModal";
import {
  getSources,
  getHealth,
  syncNow,
  getConnections,
  disconnectProvider,
  startOAuthConnect,
  Source,
  ConnectorStatus,
  ConnectionProvider,
} from "../../api/taskpilot";

const INTEGRATION_LOGOS: Record<string, string> = {
  jira: "🔷", github: "🐙", slack: "💬", outlook: "📧", servicenow: "🔧",
};

const NAME_TO_PROVIDER: Record<string, ConnectionProvider> = {
  Jira: "jira",
  GitHub: "github",
  Slack: "slack",
  Outlook: "outlook",
  ServiceNow: "servicenow",
};

const TOKEN_PASTE_PROVIDERS: ConnectionProvider[] = ["jira", "servicenow", "outlook"];

export function Integrations() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sources, setSources] = useState<Source[]>([]);
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [connectedProviders, setConnectedProviders] = useState<Set<ConnectionProvider>>(new Set());
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [modalProvider, setModalProvider] = useState<ConnectionProvider | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [s, h, c] = await Promise.all([
        getSources().catch(() => ({ sources: [], total_tasks: 0 })),
        getHealth().catch(() => null),
        getConnections().catch(() => ({ connections: [], providers: [] })),
      ]);
      setSources(s.sources || []);
      setConnectors(h?.connectors || []);
      setHealth(h);
      setConnectedProviders(new Set(c.providers.filter((p) => p.connected).map((p) => p.provider)));
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  useEffect(() => {
    const connected = searchParams.get("connected");
    const connectError = searchParams.get("connect_error");
    const reason = searchParams.get("reason");
    if (connected) {
      setBanner(`${connected[0].toUpperCase()}${connected.slice(1)} connected successfully.`);
      fetchData();
      setSearchParams({}, { replace: true });
    } else if (connectError) {
      const name = `${connectError[0].toUpperCase()}${connectError.slice(1)}`;
      const message =
        reason === "not_configured"
          ? `${name} isn't set up yet — ask your admin to add ${connectError.toUpperCase()}_OAUTH_CLIENT_ID/SECRET on the server.`
          : reason === "session_expired"
            ? "Your session expired — please log in again and retry connecting."
            : `Couldn't connect ${name} — please try again.`;
      setBanner(message);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams]);

  const handleSync = async (name?: string) => {
    setSyncing(name || "all");
    try { await syncNow(name?.toLowerCase() === "all" ? undefined : name?.toLowerCase()); }
    catch (err) { console.error(err); }
    finally { setSyncing(null); fetchData(); }
  };

  const handleConnectClick = (provider: ConnectionProvider) => {
    if (provider === "github" || provider === "slack") {
      startOAuthConnect(provider);
    } else {
      setModalProvider(provider);
    }
  };

  const handleDisconnect = async (provider: ConnectionProvider) => {
    await disconnectProvider(provider);
    fetchData();
  };

  const uniqueConnectors = new Map<string, ConnectorStatus>();
  [...connectors, ...(sources.map(s => ({ name: s.name, connected: s.status === "connected" || s.status === "Synced", last_sync: s.last_sync || null, error: s.error || null })) as ConnectorStatus[])]
    .forEach(c => uniqueConnectors.set(c.name, c));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ margin: 0 }}>Integrations</h2>
          <p style={{ color: "#7A7A7A", fontSize: 13, marginTop: 4 }}>
            {loading ? "Loading..." : `${uniqueConnectors.size} sources`}
          </p>
        </div>
        <button onClick={() => handleSync()} disabled={!!syncing}
          style={{ background: "#0D0D0D", color: "#FFFFFF", border: "none", padding: "10px 20px", borderRadius: 12, fontSize: 12, cursor: syncing ? "wait" : "pointer", display: "flex", alignItems: "center", gap: 6, fontFamily: "'IBM Plex Mono', monospace" }}>
          <RefreshCw size={13} /> {syncing === "all" ? "Syncing..." : "Sync All"}
        </button>
      </div>

      {banner && (
        <Card variant="blue" shadow style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 13 }}>{banner}</span>
          <button onClick={() => setBanner(null)} style={{ border: "none", background: "none", cursor: "pointer", color: "#7A7A7A" }}>✕</button>
        </Card>
      )}

      {health && (
        <Card variant="green" shadow>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
            <Plug size={14} /> <span style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Space Grotesk', sans-serif" }}>System Health</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
            {[
              { label: "API", ok: health.status === "healthy" || health.status === "ok" },
              { label: "Jira", ok: health.jira_connected },
              { label: "GitHub", ok: health.github_connected },
              { label: "Redis", ok: health.redis_connected },
              { label: "Database", ok: health.database_connected },
            ].map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, background: "#F6F2E9", padding: "8px 12px", borderRadius: 10 }}>
                {item.ok ? <CheckCircle size={13} color="#BFD78D" /> : <XCircle size={13} color="#F7C5E6" />}
                <span style={{ fontSize: 12, color: "#111111" }}>{item.label}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {Array.from(uniqueConnectors.values()).length === 0 && !loading && (
          <Card style={{ textAlign: "center", padding: 40 }}>
            <Link2 size={24} style={{ margin: "0 auto 12px", opacity: 0.4 }} />
            <p style={{ color: "#7A7A7A", fontSize: 13, margin: 0 }}>No integrations configured yet.</p>
          </Card>
        )}
        {Array.from(uniqueConnectors.values()).map((c: ConnectorStatus) => {
          const provider = NAME_TO_PROVIDER[c.name];
          const isOwnConnection = provider && connectedProviders.has(provider);
          return (
          <Card key={c.name} shadow>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ fontSize: 24, lineHeight: 1 }}>{INTEGRATION_LOGOS[c.name.toLowerCase()] || "🔌"}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#111111" }}>{c.name}</div>
                <div style={{ display: "flex", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
                  {isOwnConnection ? (
                    <span style={{ fontSize: 11, color: "#4A8F3C", fontFamily: "'IBM Plex Mono', monospace" }}>Connected (your account)</span>
                  ) : c.connected ? (
                    <span style={{ fontSize: 11, color: "#BFD78D", fontFamily: "'IBM Plex Mono', monospace" }}>Connected (demo data)</span>
                  ) : (
                    <span style={{ fontSize: 11, color: "#F7C5E6", fontFamily: "'IBM Plex Mono', monospace" }}>Not connected — using sample data</span>
                  )}
                  {c.last_sync && (
                    <span style={{ fontSize: 11, color: "#7A7A7A", fontFamily: "'IBM Plex Mono', monospace" }}>
                      Last sync: {new Date(c.last_sync).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                </div>
                {c.error && (
                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 4, fontSize: 11, color: "#F7C5E6" }}>
                    <AlertCircle size={11} /> {c.error}
                  </div>
                )}
              </div>
              {provider && (
                isOwnConnection ? (
                  <button onClick={() => handleDisconnect(provider)}
                    style={{ background: "none", border: "1px solid #E9E4D8", padding: "8px 14px", borderRadius: 10, fontSize: 12, cursor: "pointer", color: "#B23B3B", fontFamily: "'IBM Plex Mono', monospace", display: "flex", alignItems: "center", gap: 6 }}>
                    <Trash2 size={12} /> Disconnect
                  </button>
                ) : (
                  <button onClick={() => handleConnectClick(provider)}
                    style={{ background: "#0D0D0D", border: "none", padding: "8px 16px", borderRadius: 10, fontSize: 12, cursor: "pointer", color: "#FFF", fontFamily: "'IBM Plex Mono', monospace" }}>
                    Connect
                  </button>
                )
              )}
              <button onClick={() => handleSync(c.name)}
                disabled={!!syncing}
                style={{ background: "none", border: "1px solid #E9E4D8", padding: "8px 16px", borderRadius: 10, fontSize: 12, cursor: syncing ? "wait" : "pointer", color: "#7A7A7A", fontFamily: "'IBM Plex Mono', monospace" }}>
                {syncing === c.name ? "..." : "Sync"}
              </button>
            </div>
          </Card>
        );})}
      </div>

      {modalProvider && TOKEN_PASTE_PROVIDERS.includes(modalProvider) && (
        <ConnectFormModal
          provider={modalProvider as "jira" | "servicenow" | "outlook"}
          onClose={() => setModalProvider(null)}
          onConnected={() => {
            setBanner(`${modalProvider[0].toUpperCase()}${modalProvider.slice(1)} connected successfully.`);
            fetchData();
          }}
        />
      )}
    </div>
  );
}
