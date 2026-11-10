import { useMutation, useQuery } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { datum } from "../ui/format";
import { FehlerMeldung, Knopf, Lade } from "../ui/ui";
import { type ProfilAntwort, PROFIL_VERSIONEN, type Version, type VersionDetail } from "./profil";

/** Versionsverlauf: jede Speicherung ist eine Version. Unterschiede ansehen, alte Version zurückholen. */
export function Versionen({ onWiederhergestellt }: { onWiederhergestellt: (antwort: ProfilAntwort) => void }) {
  const versionen = useQuery({ queryKey: PROFIL_VERSIONEN, queryFn: () => api.get<Version[]>("/api/profil/versionen") });
  const [offen, setOffen] = useState<number | null>(null);
  const detail = useQuery({
    queryKey: [...PROFIL_VERSIONEN, offen],
    queryFn: () => api.get<VersionDetail>(`/api/profil/versionen/${offen}`),
    enabled: offen !== null,
  });
  const wiederherstellen = useMutation({
    mutationFn: (id: number) => api.post<ProfilAntwort>(`/api/profil/versionen/${id}/wiederherstellen`),
    onSuccess: (antwort) => {
      setOffen(null);
      onWiederhergestellt(antwort);
    },
  });

  if (versionen.isPending) return <Lade />;
  if (versionen.isError) return <FehlerMeldung fehler={versionen.error} />;
  if (versionen.data.length === 0) {
    return <p className="gedaempft">Noch nichts gespeichert. Jede Speicherung erscheint hier als Version.</p>;
  }

  return (
    <div className="stapel eng">
      <FehlerMeldung fehler={wiederherstellen.error} />
      <ul className="versionen">
        {versionen.data.map((version, index) => (
          <li key={version.id}>
            <button type="button" className="version-kopf" aria-expanded={offen === version.id} onClick={() => setOffen(offen === version.id ? null : version.id)}>
              <span>
                <strong>{datum(version.erstellt)}</strong>
                {index === 0 && <span className="etikett aktiv" style={{ marginLeft: "0.4rem" }}>aktuell</span>}
              </span>
              <span className="gedaempft klein">{version.kommentar || "ohne Kommentar"}</span>
            </button>
            {offen === version.id && (
              <div className="version-inhalt stapel eng">
                {detail.isPending && <Lade />}
                <FehlerMeldung fehler={detail.error} />
                {detail.data && detail.data.id === version.id && (
                  <>
                    {detail.data.unterschiede.length === 0 ? (
                      <p className="gedaempft klein">{index === 0 ? "Das ist die aktuelle Version." : "Kein Unterschied zur aktuellen Version."}</p>
                    ) : (
                      <>
                        <p className="gedaempft klein">Unterschiede zur aktuellen Version (rot: nur hier, grün: nur in der aktuellen):</p>
                        {detail.data.unterschiede.map((unterschied) => (
                          <div key={unterschied.feld}>
                            <div className="feld-titel">{unterschied.titel}</div>
                            <pre className="diff">
                              {unterschied.zeilen.map((zeile, nummer) => (
                                <span key={nummer} className={zeile.art}>
                                  {zeile.art === "entfernt" ? "− " : zeile.art === "neu" ? "+ " : "  "}
                                  {zeile.text || " "}
                                  {"\n"}
                                </span>
                              ))}
                            </pre>
                          </div>
                        ))}
                      </>
                    )}
                    {index > 0 && (
                      <Knopf klein onClick={() => wiederherstellen.mutate(version.id)} disabled={wiederherstellen.isPending}>
                        <Undo2 aria-hidden />
                        Diese Version wiederherstellen
                      </Knopf>
                    )}
                  </>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
