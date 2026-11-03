import React, { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { api } from "./api/client";
import { useMeta, useReporte } from "./api/hooks";
import type { User } from "./api/types";
import { BrandSplash, resetSplash, shouldShowSplash } from "./components/BrandSplash";
import { TopBar } from "./components/TopBar";
import { Banner, Button } from "./components/ui";
import { Login } from "./pages/Login";
import { Reporte } from "./pages/Reporte";

function Loading() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <Loader2 className="spin" color="var(--text-4)" />
    </div>
  );
}

export function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ authenticated: boolean; user: User | null }>("/api/auth/me") });
  const authed = !!me.data?.authenticated;
  const meta = useMeta(authed);
  const reporte = useReporte(authed);
  // Animación de marca: al iniciar sesión (una vez por sesión), mientras se cargan los datos del reporte.
  const [splash, setSplash] = useState(shouldShowSplash);
  const endSplash = useCallback(() => setSplash(false), []);

  useEffect(() => {
    const onUnauth = () => qc.invalidateQueries({ queryKey: ["me"] });
    window.addEventListener("tva:unauthorized", onUnauth);
    return () => window.removeEventListener("tva:unauthorized", onUnauth);
  }, [qc]);

  if (me.isLoading) return splash ? <div className="splash" aria-hidden /> : <Loading />;
  if (!authed) return <Login onLogin={() => qc.invalidateQueries()} />;

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    resetSplash();
    qc.clear();
    window.location.href = `${import.meta.env.BASE_URL}`;
  };

  let content: React.ReactNode;
  if (meta.isError) {
    content = (
      <div className="page" style={{ maxWidth: 560, paddingTop: 80 }}>
        <Banner tone="danger">No fue posible cargar la plataforma: {(meta.error as Error).message}</Banner>
        <Button onClick={() => meta.refetch()}>Reintentar</Button>
      </div>
    );
  } else if (!meta.data) {
    content = splash ? null : <Loading />;
  } else {
    content = (
      <>
        <TopBar meta={meta.data} onLogout={logout} />
        <main id="contenido">
          <Routes>
            <Route path="/" element={<Reporte meta={meta.data} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </>
    );
  }

  // La plataforma se monta debajo de la animación, que se retira cuando los datos están listos.
  const ready = meta.isError || (!!meta.data && !reporte.isPending);
  return (
    <>
      {content}
      {splash ? <BrandSplash ready={ready} onDone={endSplash} /> : null}
    </>
  );
}
