import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu } from "lucide-react";
import { type ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router";

import { api } from "../api";
import { AUTH_STATUS, useAuthStatus } from "../auth/authStatus";
import { Knopf } from "../ui/ui";
import { ALLE_EINTRAEGE, NAVIGATION } from "./navigation";

/** Grundgerüst des Panels: Navigation links, Seitentitel oben, Inhalt in der Mitte. */
export function Rahmen({ children }: { children: ReactNode }) {
  const [offen, setOffen] = useState(false);
  const ort = useLocation();
  const queryClient = useQueryClient();
  const status = useAuthStatus();

  const abmelden = useMutation({
    mutationFn: () => api.post("/api/auth/abmelden"),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: AUTH_STATUS });
      // Nach dem Abmelden bleibt nichts aus dem Panel im Speicher des Browsers.
      queryClient.removeQueries({ predicate: (abfrage) => abfrage.queryKey[0] !== AUTH_STATUS[0] });
    },
  });

  const aktuell = ALLE_EINTRAEGE.find((eintrag) =>
    eintrag.pfad === "/" ? ort.pathname === "/" : ort.pathname.startsWith(eintrag.pfad),
  );

  return (
    <div className="rahmen">
      {offen && <div className="leiste-schleier" onClick={() => setOffen(false)} aria-hidden />}
      <nav className={`leiste${offen ? " offen" : ""}`} aria-label="Hauptnavigation">
        <NavLink to="/" className="marke" onClick={() => setOffen(false)}>
          <img src="/favicon.svg" alt="" />
          Missa Control
        </NavLink>
        {NAVIGATION.map((gruppe, index) => (
          <div className="nav-gruppe" key={gruppe.titel ?? index}>
            {gruppe.titel && <div className="nav-gruppe-titel">{gruppe.titel}</div>}
            {gruppe.eintraege.map((eintrag) => (
              <NavLink
                key={eintrag.pfad}
                to={eintrag.pfad}
                end={eintrag.pfad === "/"}
                className="nav-link"
                onClick={() => setOffen(false)}
              >
                <eintrag.symbol aria-hidden />
                <span>{eintrag.titel}</span>
              </NavLink>
            ))}
          </div>
        ))}
        <div className="leiste-fuss">
          <Knopf art="still" klein onClick={() => abmelden.mutate()} disabled={abmelden.isPending}>
            <LogOut aria-hidden />
            Abmelden
          </Knopf>
          <div style={{ marginTop: "0.5rem" }}>Version {status.data?.version ?? "–"}</div>
        </div>
      </nav>

      <div className="inhalt">
        <header className="kopf">
          <Knopf art="still" className="menue-knopf" aria-label="Navigation öffnen" onClick={() => setOffen(true)}>
            <Menu aria-hidden />
          </Knopf>
          <h1>{aktuell?.titel ?? "Nicht gefunden"}</h1>
        </header>
        <main className="seite">{children}</main>
      </div>
    </div>
  );
}
