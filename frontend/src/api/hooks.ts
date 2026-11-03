import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Corte, Meta, Reporte } from "./types";

export function useMeta(enabled = true) {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/meta"),
    staleTime: 30_000,
    enabled,
    // Mientras hay un corte en curso, se consulta su avance cada 2 s.
    refetchInterval: (q) => (q.state.data?.en_curso ? 2000 : false),
  });
}

export function useReporte(enabled = true) {
  return useQuery({ queryKey: ["reporte"], queryFn: () => api<Reporte>("/api/reporte"), staleTime: 60_000, enabled });
}

export function useCortes(poll: boolean) {
  return useQuery({
    queryKey: ["cortes"],
    queryFn: () => api<{ cortes: Corte[] }>("/api/cortes"),
    refetchInterval: poll ? 2000 : false,
  });
}
