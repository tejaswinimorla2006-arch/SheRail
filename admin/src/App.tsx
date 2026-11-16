import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ApiError,
  clearToken,
  dateLabel,
  display,
  errorMessage,
  fetchImage,
  getToken,
  isSessionError,
  request,
  rowsFrom,
  setToken,
} from "./api";
import type { Row } from "./api";

type View = "overview" | "users" | "sos-alerts" | "community-reports" | "assistance-points" | "railway-assistance";
type Field = {
  name: string;
  label: string;
  type?: "text" | "number" | "email" | "tel" | "url" | "textarea" | "select" | "checkbox";
  required?: boolean;
  options?: string[];
  maxLength?: number;
  min?: number;
  max?: number;
  pattern?: string;
};

const navigation: { id: View; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "◫" },
  { id: "users", label: "Users", icon: "♙" },
  { id: "sos-alerts", label: "SOS alerts", icon: "!" },
  { id: "community-reports", label: "Community reports", icon: "◉" },
  { id: "assistance-points", label: "Assistance points", icon: "⌖" },
  { id: "railway-assistance", label: "Railway assistance", icon: "↗" },
];

const assistanceFields: Field[] = [
  { name: "name", label: "Name", required: true, maxLength: 160 },
  { name: "category", label: "Category", type: "select", options: ["police", "hospital", "clinic", "shelter", "crisis_center", "assistance_point", "railway_assistance"], required: true },
  { name: "description", label: "Description", type: "textarea", maxLength: 500 },
  { name: "address", label: "Address", maxLength: 300 },
  { name: "latitude", label: "Latitude", type: "number", required: true, min: -90, max: 90 },
  { name: "longitude", label: "Longitude", type: "number", required: true, min: -180, max: 180 },
  { name: "phone", label: "Phone", type: "tel", maxLength: 32 },
  { name: "is_active", label: "Active", type: "checkbox" },
];

const railwayFields: Field[] = [
  { name: "category", label: "Category", type: "select", options: ["emergency", "station_help", "accessibility", "security", "other"], required: true },
  { name: "title", label: "Title", required: true, maxLength: 160 },
  { name: "description", label: "Description", type: "textarea", required: true, maxLength: 1000 },
  { name: "station_name", label: "Station name", maxLength: 160 },
  { name: "phone", label: "Phone", type: "tel", maxLength: 32 },
  { name: "contact_url", label: "Contact URL", type: "url", maxLength: 500 },
  { name: "availability", label: "Availability", maxLength: 160 },
  { name: "is_active", label: "Active", type: "checkbox" },
];

const sosStatusChoices = ["open", "investigating", "resolved", "dismissed"];
const reportStatusChoices = ["pending", "under_review", "verified", "rejected", "duplicate"];

function App() {
  const [token, setCurrentToken] = useState<string | null>(() => getToken());
  const [phase, setPhase] = useState<"checking" | "signed-out" | "ready">(() => getToken() ? "checking" : "signed-out");
  const [authMessage, setAuthMessage] = useState("");
  const [overview, setOverview] = useState<Row | null>(null);
  const [activeView, setActiveView] = useState<View>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const verifySession = useCallback(async (accessToken: string) => {
    setPhase("checking");
    try {
      const result = await request<Row>("/admin/overview", {}, accessToken);
      setOverview(result && typeof result === "object" ? result : {});
      setCurrentToken(accessToken);
      setPhase("ready");
      setAuthMessage("");
    } catch (error) {
      if (isSessionError(error)) {
        clearToken();
        setCurrentToken(null);
        setPhase("signed-out");
        setAuthMessage(error instanceof ApiError && error.status === 403
          ? "This account is not authorized to access the admin dashboard."
          : "Your session has expired. Please sign in again.");
      } else {
        setPhase("signed-out");
        setAuthMessage(`${errorMessage(error)} Sign in again when the API is available.`);
      }
    }
  }, []);

  useEffect(() => {
    const savedToken = getToken();
    if (savedToken) void verifySession(savedToken);
  }, [verifySession]);

  const signOut = useCallback((message = "") => {
    clearToken();
    setCurrentToken(null);
    setOverview(null);
    setPhase("signed-out");
    setAuthMessage(message);
  }, []);

  async function handleLogin(email: string, password: string) {
    clearToken();
    setAuthMessage("");
    try {
      const result = await request<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }, null);
      if (!result?.access_token) throw new Error("The login response did not contain an access token.");
      setToken(result.access_token);
      setCurrentToken(result.access_token);
      await verifySession(result.access_token);
    } catch (error) {
      setAuthMessage(errorMessage(error));
      setPhase("signed-out");
    }
  }

  if (phase !== "ready" || !token) {
    return (
      <LoginScreen
        busy={phase === "checking"}
        message={authMessage}
        onSubmit={handleLogin}
        onRetry={() => {
          const savedToken = getToken();
          if (savedToken) void verifySession(savedToken);
        }}
      />
    );
  }

  const currentLabel = navigation.find((item) => item.id === activeView)?.label ?? "Overview";
  return (
    <div className="app-shell">
      {mobileNavOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`} aria-label="Main navigation">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">S</div>
          <div><strong>SheRail</strong><span>ADMIN CONSOLE</span></div>
          <button className="icon-button mobile-close" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">×</button>
        </div>
        <p className="nav-caption">WORKSPACE</p>
        <nav>
          {navigation.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? "nav-item-active" : ""}`}
              onClick={() => { setActiveView(item.id); setMobileNavOpen(false); }}
              aria-current={activeView === item.id ? "page" : undefined}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}
              {item.id === "railway-assistance" && <span className="nav-optional">OPTIONAL</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="secure-note"><span className="secure-dot" /> Server-verified session</div>
          <button className="signout-button" onClick={() => signOut()}><span aria-hidden="true">↪</span> Sign out</button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="icon-button menu-toggle" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>☰</button>
          <div className="breadcrumbs"><span>Admin</span><span className="crumb-separator">/</span><strong>{currentLabel}</strong></div>
          <div className="topbar-right"><span className="live-indicator" /> Secure workspace</div>
        </header>
        <main className="page-content">
          {activeView === "overview" && <OverviewPage token={token} initialData={overview} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} />}
          {activeView === "users" && <UsersPage token={token} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} />}
          {activeView === "sos-alerts" && <SosPage token={token} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} />}
          {activeView === "community-reports" && <ReportsPage token={token} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} />}
          {activeView === "assistance-points" && <CrudPage token={token} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} title="Verified assistance points" description="Manage trusted assistance locations shown to SheRail users." endpoint="/admin/assistance-points" fields={assistanceFields} columns={["name", "category", "address", "is_active"]} />}
          {activeView === "railway-assistance" && <CrudPage token={token} onSessionExpired={() => signOut("Your admin session is no longer authorized. Please sign in again.")} title="Railway assistance" description="Manage railway-specific help desks, contacts, and support records." endpoint="/admin/railway-assistance" fields={railwayFields} columns={["station_name", "title", "category", "phone", "is_active"]} />}
        </main>
      </div>
    </div>
  );
}

function LoginScreen({ busy, message, onSubmit, onRetry }: {
  busy: boolean;
  message: string;
  onSubmit: (email: string, password: string) => Promise<void>;
  onRetry: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try { await onSubmit(email.trim(), password); } finally { setSubmitting(false); }
  }

  return (
    <main className="login-layout">
      <section className="login-brand-panel">
        <div className="brand-lockup brand-lockup-light">
          <div className="brand-mark" aria-hidden="true">S</div>
          <div><strong>SheRail</strong><span>ADMIN CONSOLE</span></div>
        </div>
        <div className="login-message">
          <div className="eyebrow"><span className="live-indicator" /> OPERATIONS &amp; SAFETY</div>
          <h1>Safer journeys.<br /><em>Stronger oversight.</em></h1>
          <p>Manage safety operations and trusted resources from one secure workspace.</p>
        </div>
        <div className="login-panel-footer">Protected access · Authorized administrators only</div>
      </section>
      <section className="login-form-panel">
        <div className="login-form-wrap">
          <div className="mobile-login-brand"><div className="brand-mark">S</div><strong>SheRail Admin</strong></div>
          <div className="login-heading"><span className="eyebrow">WELCOME BACK</span><h2>Sign in to your account</h2><p>Use your administrator credentials to continue.</p></div>
          {busy ? (
            <div className="verify-state" role="status"><span className="spinner" />Verifying your session with the server…</div>
          ) : (
            <form className="login-form" onSubmit={submit}>
              {message && <div className="alert alert-error" role="alert">{message}{message.includes("Could not reach") && <button type="button" className="inline-link" onClick={onRetry}>Retry session check</button>}</div>}
              <label htmlFor="login-email">Email address</label>
              <input id="login-email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" required />
              <label htmlFor="login-password">Password</label>
              <input id="login-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required />
              <button className="primary-button login-submit" type="submit" disabled={submitting}>
                {submitting ? <><span className="spinner spinner-light" /> Signing in…</> : <>Sign in securely <span aria-hidden="true">→</span></>}
              </button>
              <p className="form-security"><span aria-hidden="true">⌑</span> Your session is scoped to this browser tab.</p>
            </form>
          )}
        </div>
        <footer className="login-mobile-footer">Protected access · SheRail administration</footer>
      </section>
    </main>
  );
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="state-card state-error" role="alert"><div className="state-icon">!</div><div><strong>We couldn’t load this data</strong><p>{message}</p><button className="text-button" onClick={onRetry}>Try again</button></div></div>;
}

function EmptyState({ title, message }: { title: string; message: string }) {
  return <div className="empty-state"><div className="empty-symbol" aria-hidden="true">◇</div><strong>{title}</strong><p>{message}</p></div>;
}

function OverviewPage({ token, initialData, onSessionExpired }: { token: string; initialData: Row | null; onSessionExpired: () => void }) {
  const [data, setData] = useState<Row | null>(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setData(await request<Row>("/admin/overview", {}, token)); }
    catch (err) {
      setError(errorMessage(err));
      if (isSessionError(err)) onSessionExpired();
    } finally { setLoading(false); }
  }, [token, onSessionExpired]);

  useEffect(() => { if (!initialData) void load(); }, [initialData, load]);
  const cards = useMemo(() => {
    if (!data) return [];
    const source = data.counts && typeof data.counts === "object" ? data.counts as Row : data;
    return Object.entries(source).filter(([, value]) => typeof value === "number" || typeof value === "string" || typeof value === "boolean");
  }, [data]);

  return (
    <>
      <PageHeading eyebrow="ADMINISTRATION" title="Overview" description="A live snapshot of activity across the SheRail platform." action={<button className="secondary-button" onClick={() => void load()} disabled={loading}><span aria-hidden="true">↻</span> Refresh</button>} />
      {loading && <div className="loading-state" role="status"><span className="spinner" />Loading platform overview…</div>}
      {!loading && error && <ErrorState message={error} onRetry={() => void load()} />}
      {!loading && !error && (
        <>
          {cards.length > 0 ? (
            <div className="stats-grid">
              {cards.map(([key, value]) => (
                <article className="stat-card" key={key}>
                  <span className="stat-label">{humanize(key)}</span>
                  <strong className="stat-value">{display(value)}</strong>
                  <span className="stat-footnote">Current server-reported total</span>
                </article>
              ))}
            </div>
          ) : <EmptyState title="Overview is available" message="The server returned no summary metrics." />}
          <section className="content-card overview-note">
            <div className="overview-note-icon" aria-hidden="true">✓</div>
            <div><strong>Admin access verified</strong><p>Dashboard access is provided by the API. Client-side role information is not used to authorize requests.</p></div>
            <span className="verified-tag">SERVER VERIFIED</span>
          </section>
        </>
      )}
    </>
  );
}

function UsersPage({ token, onSessionExpired }: { token: string; onSessionExpired: () => void }) {
  const [users, setUsers] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(""); setNotice("");
    try { setUsers(rowsFrom(await request("/admin/users", {}, token))); }
    catch (err) { setError(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setLoading(false); }
  }, [token, onSessionExpired]);
  useEffect(() => { void load(); }, [load]);

  async function saveUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    const form = new FormData(event.currentTarget);
    setSaving(true); setNotice("");
    try {
      await request(`/admin/users/${encodeURIComponent(String(editing.id))}`, {
        method: "PATCH",
        body: JSON.stringify({ role: form.get("role"), is_active: form.get("is_active") === "on" }),
      }, token);
      setEditing(null); setNotice("User access updated."); await load();
    } catch (err) { setNotice(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setSaving(false); }
  }

  return (
    <>
      <PageHeading eyebrow="ACCESS CONTROL" title="Users" description="Review accounts and manage roles and active access." action={<button className="secondary-button" onClick={() => void load()} disabled={loading}>↻ Refresh</button>} />
      {notice && <div className={`inline-notice ${notice.includes("updated") ? "" : "notice-error"}`} role="status">{notice}</div>}
      {loading ? <LoadingState label="Loading users…" /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : users.length === 0 ? <EmptyState title="No users found" message="No accounts were returned by the server." /> : (
        <section className="content-card table-card">
          <div className="table-card-header"><div><strong>Account directory</strong><span>{users.length} {users.length === 1 ? "account" : "accounts"}</span></div></div>
          <div className="table-scroll"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Joined</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
            {users.map((user) => <tr key={String(user.id)}>
              <td><div className="user-cell"><div className="avatar">{initials(user.name ?? user.email)}</div><div><strong>{display(user.name)}</strong><span>{display(user.email)}</span></div></div></td>
              <td><span className="role-pill">{display(user.role)}</span></td>
              <td><StatusPill value={user.is_active ? "active" : "inactive"} /></td>
              <td>{dateLabel(user.created_at)}</td>
              <td><button className="row-action" onClick={() => setEditing(user)}>Manage<span className="sr-only"> {display(user.email)}</span></button></td>
            </tr>)}
          </tbody></table></div>
        </section>
      )}
      {editing && <Modal title="Manage user access" onClose={() => setEditing(null)}>
        <form className="editor-form" onSubmit={saveUser}>
          <div className="record-summary"><strong>{display(editing.name)}</strong><span>{display(editing.email)}</span></div>
          <label htmlFor="user-role">Role</label>
          <select id="user-role" name="role" defaultValue={String(editing.role ?? "user")} required>
            {[...new Set(["user", "admin", String(editing.role ?? "")].filter(Boolean))].map((role) => <option key={role} value={role}>{humanize(role)}</option>)}
          </select>
          <label className="checkbox-field"><input type="checkbox" name="is_active" defaultChecked={Boolean(editing.is_active)} /> Account is active</label>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditing(null)}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button></div>
        </form>
      </Modal>}
    </>
  );
}

function SosPage({ token, onSessionExpired }: { token: string; onSessionExpired: () => void }) {
  const [items, setItems] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(rowsFrom(await request("/admin/sos-alerts", {}, token))); }
    catch (err) { setError(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setLoading(false); }
  }, [token, onSessionExpired]);
  useEffect(() => { void load(); }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return;
    const form = new FormData(event.currentTarget);
    setSaving(true); setNotice("");
    try {
      await request(`/admin/sos-alerts/${encodeURIComponent(String(editing.id))}`, {
        method: "PATCH",
        body: JSON.stringify({ admin_status: form.get("admin_status"), admin_note: form.get("admin_note") || null }),
      }, token);
      setEditing(null); setNotice("SOS review saved."); await load();
    } catch (err) { setNotice(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setSaving(false); }
  }

  return (
    <>
      <PageHeading eyebrow="URGENT RESPONSE" title="SOS alerts" description="Review emergency alerts and record resolution notes." action={<button className="secondary-button" onClick={() => void load()} disabled={loading}>↻ Refresh</button>} />
      {notice && <div className={`inline-notice ${notice.includes("saved") ? "" : "notice-error"}`} role="status">{notice}</div>}
      {loading ? <LoadingState label="Loading SOS alerts…" /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : items.length === 0 ? <EmptyState title="No SOS alerts" message="There are no alerts to review." /> : (
        <section className="content-card table-card"><div className="table-card-header"><div><strong>Emergency alert queue</strong><span>{items.length} {items.length === 1 ? "alert" : "alerts"}</span></div></div>
          <div className="table-scroll"><table><thead><tr><th>Alert</th><th>Person</th><th>Reported</th><th>Review status</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
            {items.map((item) => <tr key={String(item.id)}>
              <td><span className="alert-id">#{shortId(item.id)}</span><span className="sub-cell">{display(item.alert_type ?? item.description)}</span></td>
              <td>{display(item.user_name ?? item.name ?? item.user_email ?? item.email)}</td>
              <td>{dateLabel(item.created_at)}</td><td><StatusPill value={item.admin_status ?? item.status} /></td>
              <td><button className="row-action" onClick={() => setEditing(item)}>Review<span className="sr-only"> alert {shortId(item.id)}</span></button></td>
            </tr>)}
          </tbody></table></div>
        </section>
      )}
      {editing && <Modal title="Review SOS alert" onClose={() => setEditing(null)}>
        <form className="editor-form" onSubmit={save}>
          <div className="record-summary"><strong>{display(editing.alert_type ?? editing.description ?? "SOS alert")}</strong><span>{display(editing.user_name ?? editing.name ?? editing.user_email ?? editing.email)} · {dateLabel(editing.created_at)}</span></div>
          <label htmlFor="sos-status">Review status</label><select id="sos-status" name="admin_status" defaultValue={String(editing.admin_status ?? "open")} required>
            {[...new Set([...sosStatusChoices, String(editing.admin_status ?? "")].filter(Boolean))].map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
          </select>
          <label htmlFor="sos-note">Admin note</label><textarea id="sos-note" name="admin_note" maxLength={500} defaultValue={String(editing.admin_note ?? "")} rows={4} placeholder="Add a concise internal review note" />
          {editing.latitude != null && editing.longitude != null && <p className="location-note">Location: {display(editing.latitude)}, {display(editing.longitude)}</p>}
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditing(null)}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save review"}</button></div>
        </form>
      </Modal>}
    </>
  );
}

function ReportsPage({ token, onSessionExpired }: { token: string; onSessionExpired: () => void }) {
  const [reports, setReports] = useState<Row[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    const query = filter === "all" ? "" : `?status=${encodeURIComponent(filter)}`;
    try { setReports(rowsFrom(await request(`/admin/community-reports${query}`, {}, token))); }
    catch (err) { setError(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setLoading(false); }
  }, [filter, token, onSessionExpired]);
  useEffect(() => { void load(); }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return;
    const form = new FormData(event.currentTarget);
    setSaving(true); setNotice("");
    const duplicateValue = String(form.get("duplicate_of_id") ?? "").trim();
    const reportStatus = String(form.get("status") ?? "");
    try {
      await request(`/admin/community-reports/${encodeURIComponent(String(editing.id))}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: reportStatus,
          moderator_note: form.get("moderator_note") || null,
          duplicate_of_id: reportStatus === "duplicate" ? duplicateValue || null : null,
        }),
      }, token);
      setEditing(null); setNotice("Report moderation saved."); await load();
    } catch (err) { setNotice(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setSaving(false); }
  }

  return (
    <>
      <PageHeading eyebrow="COMMUNITY SAFETY" title="Community reports" description="Moderate user reports, review images, and associate duplicates." action={<button className="secondary-button" onClick={() => void load()} disabled={loading}>↻ Refresh</button>} />
      <div className="toolbar">
        <label htmlFor="report-filter">Report status</label>
        <select id="report-filter" value={filter} onChange={(event) => setFilter(event.target.value)}>
          <option value="all">All reports</option>{reportStatusChoices.map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
        </select>
      </div>
      {notice && <div className={`inline-notice ${notice.includes("saved") ? "" : "notice-error"}`} role="status">{notice}</div>}
      {loading ? <LoadingState label="Loading community reports…" /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : reports.length === 0 ? <EmptyState title="No reports in this view" message="The server returned no community reports for this filter." /> : (
        <section className="content-card table-card"><div className="table-card-header"><div><strong>Moderation queue</strong><span>{reports.length} {reports.length === 1 ? "report" : "reports"}</span></div></div>
          <div className="table-scroll"><table><thead><tr><th>Report</th><th>Reporter</th><th>Submitted</th><th>Status</th><th>Images</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
            {reports.map((report) => <tr key={String(report.id)}>
              <td><span className="report-type">{humanize(String(report.report_type ?? "community report"))}</span><span className="sub-cell report-description">{display(report.description)}</span><span className="sub-cell">ID: {display(report.id)}</span></td>
              <td>{display(report.user_name ?? report.reporter_name ?? report.user_email ?? report.email)}</td><td>{dateLabel(report.created_at)}</td>
              <td><StatusPill value={report.status} /></td><td>{imageReferences(report).length ? `${imageReferences(report).length} attached` : "—"}</td>
              <td><button className="row-action" onClick={() => setEditing(report)}>Moderate<span className="sr-only"> report {shortId(report.id)}</span></button></td>
            </tr>)}
          </tbody></table></div>
        </section>
      )}
      {editing && <ReportModal report={editing} token={token} saving={saving} onClose={() => setEditing(null)} onSave={save} onSessionExpired={onSessionExpired} />}
    </>
  );
}

function ReportModal({ report, token, saving, onClose, onSave, onSessionExpired }: {
  report: Row; token: string; saving: boolean; onClose: () => void; onSave: (event: FormEvent<HTMLFormElement>) => void; onSessionExpired: () => void;
}) {
  const images = imageReferences(report);
  const [status, setStatus] = useState(String(report.status ?? "pending"));
  return <Modal title="Moderate community report" onClose={onClose}>
    <form className="editor-form" onSubmit={onSave}>
      <div className="record-summary"><strong>{humanize(String(report.report_type ?? "Community report"))}</strong><span>{display(report.description)}</span><span>{dateLabel(report.created_at)} · {display(report.user_name ?? report.reporter_name ?? report.user_email ?? report.email)}</span></div>
      {images.length > 0 && <div><span className="field-label">Submitted images</span><div className="image-grid">{images.map((image) => <AuthenticatedImage key={image.id} reportId={String(report.id)} imageId={image.id} token={token} onSessionExpired={onSessionExpired} />)}</div></div>}
      <label htmlFor="report-status">Moderation status</label><select id="report-status" name="status" value={status} onChange={(event) => setStatus(event.target.value)} required>
        {[...new Set([...reportStatusChoices, String(report.status ?? "")].filter(Boolean))].map((choice) => <option key={choice} value={choice}>{humanize(choice)}</option>)}
      </select>
      <label htmlFor="report-note">Moderator note</label><textarea id="report-note" name="moderator_note" maxLength={300} defaultValue={String(report.moderator_note ?? "")} rows={3} placeholder="Add a moderation note" />
      <label htmlFor="duplicate-id">Duplicate of report ID{status === "duplicate" ? <span className="required-mark"> *</span> : <span className="optional-label"> Optional</span>}</label>
      <input id="duplicate-id" name="duplicate_of_id" required={status === "duplicate"} defaultValue={String(report.duplicate_of_id ?? "")} placeholder="Paste the original report ID" />
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save moderation"}</button></div>
    </form>
  </Modal>;
}

function AuthenticatedImage({ reportId, imageId, token, onSessionExpired }: { reportId: string; imageId: string; token: string; onSessionExpired: () => void }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    void fetchImage(`/admin/community-reports/${encodeURIComponent(reportId)}/images/${encodeURIComponent(imageId)}`, token)
      .then((result) => { objectUrl = result; if (active) setUrl(result); else URL.revokeObjectURL(result); })
      .catch((err) => {
        if (active) setError(errorMessage(err));
        if (isSessionError(err)) onSessionExpired();
      });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [reportId, imageId, token, onSessionExpired]);
  if (error) return <div className="image-fallback" role="status">Image unavailable</div>;
  if (!url) return <div className="image-fallback" role="status"><span className="spinner" />Loading image…</div>;
  return <a className="image-preview" href={url} target="_blank" rel="noreferrer" aria-label={`Open report image ${imageId}`}><img src={url} alt={`Community report ${reportId}`} /></a>;
}

function CrudPage({ token, onSessionExpired, title, description, endpoint, fields, columns }: {
  token: string; onSessionExpired: () => void; title: string; description: string; endpoint: string; fields: Field[]; columns: string[];
}) {
  const [records, setRecords] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setRecords(rowsFrom(await request(endpoint, {}, token))); }
    catch (err) { setError(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setLoading(false); }
  }, [endpoint, token, onSessionExpired]);
  useEffect(() => { void load(); }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const values: Row = {};
    for (const field of fields) {
      if (field.type === "checkbox") {
        values[field.name] = formData.get(field.name) === "on";
        continue;
      }
      const raw = String(formData.get(field.name) ?? "").trim();
      if (!raw) {
        if (!creating && !field.required) values[field.name] = null;
        continue;
      }
      values[field.name] = field.type === "number" ? Number(raw) : raw;
    }
    setSaving(true); setNotice("");
    try {
      await request(creating ? endpoint : `${endpoint}/${encodeURIComponent(String(editing?.id))}`, {
        method: creating ? "POST" : "PATCH",
        body: JSON.stringify(values),
      }, token);
      setCreating(false); setEditing(null); setNotice(creating ? "Record created." : "Record updated."); await load();
    } catch (err) { setNotice(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
    finally { setSaving(false); }
  }

  async function remove(record: Row) {
    if (!window.confirm(`Delete “${display(record.name ?? record.station_name ?? record.id)}”? This cannot be undone.`)) return;
    setNotice("");
    try {
      await request(`${endpoint}/${encodeURIComponent(String(record.id))}`, { method: "DELETE" }, token);
      setNotice("Record deleted."); await load();
    } catch (err) { setNotice(errorMessage(err)); if (isSessionError(err)) onSessionExpired(); }
  }

  return (
    <>
      <PageHeading eyebrow="TRUSTED RESOURCES" title={title} description={description} action={<button className="primary-button" onClick={() => { setEditing(null); setCreating(true); }}>＋ Add record</button>} />
      {notice && <div className={`inline-notice ${notice.includes("created") || notice.includes("updated") || notice.includes("deleted") ? "" : "notice-error"}`} role="status">{notice}</div>}
      {loading ? <LoadingState label={`Loading ${title.toLowerCase()}…`} /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : records.length === 0 ? <EmptyState title="No records yet" message="No records were returned. Add a verified resource to get started." /> : (
        <section className="content-card table-card"><div className="table-card-header"><div><strong>Resource directory</strong><span>{records.length} {records.length === 1 ? "record" : "records"}</span></div><button className="text-button" onClick={() => void load()}>↻ Refresh</button></div>
          <div className="table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{humanize(column)}</th>)}<th><span className="sr-only">Actions</span></th></tr></thead><tbody>
            {records.map((record) => <tr key={String(record.id)}>{columns.map((column) => <td key={column}>{column === "is_active" ? <StatusPill value={record[column] ? "active" : "inactive"} /> : display(record[column])}</td>)}<td><div className="row-actions"><button className="row-action" onClick={() => { setCreating(false); setEditing(record); }}>Edit</button><button className="row-action row-action-danger" onClick={() => void remove(record)}>Delete</button></div></td></tr>)}
          </tbody></table></div>
        </section>
      )}
      {(creating || editing) && <Modal title={creating ? "Add resource" : "Edit resource"} onClose={() => { setCreating(false); setEditing(null); }}>
        <form className="editor-form" onSubmit={save}>
          <div className="form-grid">{fields.map((field) => <FieldControl key={field.name} field={field} value={editing?.[field.name]} />)}</div>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setCreating(false); setEditing(null); }}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Saving…" : creating ? "Create record" : "Save changes"}</button></div>
        </form>
      </Modal>}
    </>
  );
}

function FieldControl({ field, value }: { field: Field; value: unknown }) {
  const id = `record-${field.name}`;
  if (field.type === "checkbox") return <label className="checkbox-field field-span" htmlFor={id}><input id={id} type="checkbox" name={field.name} defaultChecked={typeof value === "boolean" ? value : field.name === "is_active"} />{field.label}</label>;
  const inputValue = value === null || value === undefined ? "" : String(value);
  return <div className={field.type === "textarea" ? "field-span" : ""}>
    <label htmlFor={id}>{field.label}{field.required && <span className="required-mark"> *</span>}</label>
    {field.type === "textarea" ? <textarea id={id} name={field.name} defaultValue={inputValue} required={field.required} rows={3} /> : field.type === "select" ? <select id={id} name={field.name} defaultValue={inputValue || field.options?.[0]} required={field.required}>{inputValue && !field.options?.includes(inputValue) && <option value={inputValue}>{humanize(inputValue)}</option>}{field.options?.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select> : <input id={id} name={field.name} type={field.type ?? "text"} step={field.type === "number" ? "any" : undefined} defaultValue={inputValue} required={field.required} /> }
  </div>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-heading">
      <header className="modal-header"><h2 id="modal-heading">{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}>×</button></header>
      <div className="modal-body">{children}</div>
    </section>
  </div>;
}

function StatusPill({ value }: { value: unknown }) {
  const text = String(value ?? "unknown").toLowerCase();
  const tone = ["active", "verified", "resolved", "complete", "completed"].includes(text) ? "success"
    : ["pending", "reviewed", "in_progress", "paused"].includes(text) ? "warning"
      : ["rejected", "dismissed", "inactive", "failed"].includes(text) ? "muted" : "neutral";
  return <span className={`status-pill status-${tone}`}><span className="status-dot" />{humanize(text)}</span>;
}

function LoadingState({ label }: { label: string }) {
  return <div className="loading-state" role="status"><span className="spinner" />{label}</div>;
}

function imageReferences(report: Row): { id: string }[] {
  const images = report.image_ids;
  if (!Array.isArray(images)) return [];
  return images.map((image) => {
    const id = typeof image === "object" && image !== null
      ? (image as Row).id ?? (image as Row).image_id
      : image;
    return id === null || id === undefined ? null : { id: String(id) };
  }).filter((image): image is { id: string } => image !== null);
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function initials(value: unknown) {
  return String(value ?? "?").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}

function shortId(value: unknown) {
  const text = String(value ?? "");
  return text.length > 10 ? text.slice(0, 8) : text || "—";
}

export default App;
