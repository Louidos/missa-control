import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { ABGEMELDET_EREIGNIS, api } from "../api";

export interface AuthStatus {
  eingerichtet: boolean;
  /** Nach dem Notfall-Reset: Die Zwei-Faktor-Anmeldung wird mit dem bisherigen Passwort neu eingerichtet. */
  zwei_faktor_neu?: boolean;
  angemeldet: boolean;
  version: string;
}

export const AUTH_STATUS = ["auth-status"] as const;

export function useAuthStatus() {
  const queryClient = useQueryClient();

  // Meldet das Backend "nicht angemeldet" (z. B. Sitzung abgelaufen), wird der Login wieder angezeigt.
  useEffect(() => {
    const neuLaden = () => void queryClient.invalidateQueries({ queryKey: AUTH_STATUS });
    window.addEventListener(ABGEMELDET_EREIGNIS, neuLaden);
    return () => window.removeEventListener(ABGEMELDET_EREIGNIS, neuLaden);
  }, [queryClient]);

  return useQuery({
    queryKey: AUTH_STATUS,
    queryFn: () => api.get<AuthStatus>("/api/auth/status"),
    staleTime: 60_000,
  });
}
