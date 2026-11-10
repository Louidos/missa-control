import { useEffect, useState } from "react";

type Zustand = { art: "laedt" } | { art: "ok"; version: string } | { art: "fehler" };

export default function App() {
  const [zustand, setZustand] = useState<Zustand>({ art: "laedt" });

  useEffect(() => {
    let aktiv = true;
    fetch("/api/health")
      .then((antwort) => (antwort.ok ? antwort.json() : Promise.reject(new Error(String(antwort.status)))))
      .then((daten: { version: string }) => aktiv && setZustand({ art: "ok", version: daten.version }))
      .catch(() => aktiv && setZustand({ art: "fehler" }));
    return () => {
      aktiv = false;
    };
  }, []);

  return (
    <main className="start">
      <h1>Missa Control</h1>
      <p>Lokales Admin- und Integrations-Panel für Missa.</p>
      {zustand.art === "laedt" && <p role="status">Verbinde mit dem Panel …</p>}
      {zustand.art === "ok" && <p role="status">Grundgerüst läuft – Version {zustand.version}</p>}
      {zustand.art === "fehler" && <p role="alert">Das Panel antwortet nicht. Läuft der Container?</p>}
    </main>
  );
}
