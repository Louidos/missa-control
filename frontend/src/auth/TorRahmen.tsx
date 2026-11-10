import type { ReactNode } from "react";

/** Gemeinsamer Rahmen für Login und Einrichtung. */
export function TorRahmen({ titel, untertitel, children }: { titel: string; untertitel: string; children: ReactNode }) {
  return (
    <main className="tor">
      <div className="karte tor-karte stapel">
        <div>
          <div className="tor-kopf">
            <img src="/favicon.svg" alt="" />
            <div>
              <div className="gedaempft klein">Missa Control</div>
              <h1>{titel}</h1>
            </div>
          </div>
          <p className="gedaempft">{untertitel}</p>
        </div>
        {children}
      </div>
    </main>
  );
}
