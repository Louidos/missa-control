import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router";

import { ApiFehler } from "./api";
import { AuthTor } from "./auth/AuthTor";
import { ALLE_EINTRAEGE } from "./layout/navigation";
import { Rahmen } from "./layout/Rahmen";
import { Platzhalter } from "./seiten/Platzhalter";

function neuerQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // Fehler mit klarer Ursache (4xx/5xx) nicht stur wiederholen, kurze Netzaussetzer einmal.
        retry: (anzahl, fehler) => !(fehler instanceof ApiFehler && fehler.status >= 400) && anzahl < 1,
        retryDelay: 600,
      },
    },
  });
}

export function Seiten() {
  return (
    <Rahmen>
      <Routes>
        {ALLE_EINTRAEGE.map((eintrag) => (
          <Route
            key={eintrag.pfad}
            path={eintrag.pfad === "/" ? "/" : `${eintrag.pfad}/*`}
            element={eintrag.seite ? <eintrag.seite /> : <Platzhalter eintrag={eintrag} />}
          />
        ))}
        <Route
          path="*"
          element={
            <div className="karte leer">
              <h2>Diese Seite gibt es nicht</h2>
              <p>
                <Link to="/">Zurück zur Übersicht</Link>
              </p>
            </div>
          }
        />
      </Routes>
    </Rahmen>
  );
}

export default function App() {
  const [queryClient] = useState(neuerQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthTor>
        <BrowserRouter>
          <Seiten />
        </BrowserRouter>
      </AuthTor>
    </QueryClientProvider>
  );
}
