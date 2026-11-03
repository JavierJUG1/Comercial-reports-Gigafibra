import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";
import logo from "../assets/logo-giga.png";
import { api, BASE } from "../api/client";
import { Banner, Button } from "../components/ui";
import { useTitle } from "../lib/hooks";

interface AuthConfig {
  mode: "debug" | "erpnext";
  oauth_configured: boolean;
  allowed_domains: string[];
  env_label: string;
}

export function Login({ onLogin }: { onLogin: () => void }) {
  useTitle("Iniciar sesión");
  const cfg = useQuery({ queryKey: ["auth-config"], queryFn: () => api<AuthConfig>("/api/auth/config") });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(new URLSearchParams(window.location.search).get("error") || "");
  const domain = cfg.data?.allowed_domains[0] || "gigafibra.co";
  const next = new URLSearchParams(window.location.search).get("next") || "/";

  const devLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/dev-login", { method: "POST", body: JSON.stringify({ email }) });
      onLogin();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <aside className="login__brand">
        <img src={logo} alt="GIGA+ Fibra" width={104} height={33} />
        <div className="login__pitch">
          <span className="login__kicker">TV Analytics</span>
          <h1>El pulso mensual de las suscripciones de televisión.</h1>
          <p>Cortes automáticos desde ERPNext al cierre de cada mes, histórico comparable y exportación lista para analizar.</p>
        </div>
        <svg className="login__art" viewBox="0 0 480 160" aria-hidden>
          <path d="M0 120 L60 112 L120 116 L180 98 L240 104 L300 86 L360 80 L420 66 L480 58" fill="none" stroke="#ff6900" strokeWidth="2" />
          <path d="M0 120 L60 112 L120 116 L180 98 L240 104 L300 86 L360 80 L420 66 L480 58 L480 160 L0 160Z" fill="url(#lg)" />
          <defs><linearGradient id="lg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#ff6900" stopOpacity="0.18" /><stop offset="1" stopColor="#ff6900" stopOpacity="0" /></linearGradient></defs>
          {[60, 180, 300, 420].map((x) => <line key={x} x1={x} x2={x} y1={0} y2={160} stroke="rgba(255,255,255,0.06)" />)}
        </svg>
        <span className="login__foot">Gigafibra · uso interno</span>
      </aside>
      <main className="login__main">
        <div className="login__card">
          <img className="login__mlogo" src={logo} alt="GIGA+ Fibra" width={88} height={28} />
          <h2>Iniciar sesión</h2>
          <p className="muted">Accede con tu cuenta corporativa de Gigafibra.</p>
          {error && <Banner tone="danger">{error}</Banner>}
          {!cfg.data ? <Loader2 className="spin" color="var(--text-3)" /> : cfg.data.mode === "erpnext" ? (
            <>
              <a className="btn btn--primary btn--block" style={{ height: 42 }}
                href={`${BASE}/api/auth/login?next=${encodeURIComponent(next)}`}>
                Continuar con ERPNext · Office 365 <ArrowRight />
              </a>
              {!cfg.data.oauth_configured && <Banner tone="warning">El inicio de sesión con ERPNext no está configurado (OAUTH_CLIENT_ID).</Banner>}
            </>
          ) : (
            <form className="stack" style={{ gap: 12 }} onSubmit={devLogin}>
              <div className="field">
                <label htmlFor="email">Correo corporativo</label>
                <input id="email" className="input" type="email" autoComplete="email" required placeholder={`nombre@${domain}`}
                  value={email} onChange={(e) => setEmail(e.target.value)} style={{ height: 42 }} autoFocus />
              </div>
              <Button variant="primary" block type="submit" disabled={busy || !email} style={{ height: 42 }}
                icon={busy ? <Loader2 className="spin" /> : undefined}>
                Entrar {!busy && <ArrowRight />}
              </Button>
              <p className="note"><ShieldCheck />Modo desarrollo: en producción el acceso es con ERPNext y Office 365.</p>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
