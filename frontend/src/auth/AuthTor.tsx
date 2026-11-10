import type { ReactNode } from "react";

import { FehlerMeldung, Knopf, Lade } from "../ui/ui";
import { Anmeldung } from "./Anmeldung";
import { useAuthStatus } from "./authStatus";
import { Einrichtung } from "./Einrichtung";

/** Lässt nur angemeldete Besucher zum Panel; sonst erscheint Einrichtung oder Login. */
export function AuthTor({ children }: { children: ReactNode }) {
  const status = useAuthStatus();

  if (status.isPending) return <Lade text="Verbinde mit dem Panel …" />;
  if (status.isError) {
    return (
      <main className="tor">
        <div className="tor-karte stapel">
          <FehlerMeldung fehler={status.error} />
          <Knopf onClick={() => void status.refetch()}>Erneut versuchen</Knopf>
        </div>
      </main>
    );
  }
  if (!status.data.eingerichtet) return <Einrichtung />;
  if (!status.data.angemeldet) return <Anmeldung />;
  return <>{children}</>;
}
