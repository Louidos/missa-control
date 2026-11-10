import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { INTEGRATIONEN, KATALOG, useKatalog } from "../integrationen/typen";
import { FehlerMeldung, Knopf, Meldung } from "./ui";

interface Props {
  /** id der eingebauten Integration, z. B. „serverlast“. */
  manifestId: string;
  /** Was Missa erst mit der Integration kann – als Satzteil, z. B. „die Serverlast erst abfragen“. */
  wasFehlt: string;
}

/**
 * Hinweis auf Seiten wie „Serverlast“ oder „Gedächtnis“: Solange die passende Integration nicht
 * aktiv ist, kann Missa den Bereich nicht nutzen. Ein Klick aktiviert sie (ohne Formular).
 */
export function IntegrationsHinweis({ manifestId, wasFehlt }: Props) {
  const queryClient = useQueryClient();
  const katalog = useKatalog();
  const eintrag = katalog.data?.eintraege.find((kandidat) => kandidat.id === manifestId);
  const aktivieren = useMutation({
    mutationFn: () => api.post("/api/integrationen", { manifest_id: manifestId, konfig: {} }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: KATALOG }),
        queryClient.invalidateQueries({ queryKey: INTEGRATIONEN }),
      ]),
  });

  if (!eintrag || eintrag.eingerichtet > 0) return null;
  return (
    <>
      <Meldung art="info">
        <div className="reihe zwischen">
          <span>
            Missa kann {wasFehlt}, wenn die Integration „{eintrag.name}“ aktiv ist.
          </span>
          <Knopf klein onClick={() => aktivieren.mutate()} disabled={aktivieren.isPending}>
            {aktivieren.isPending ? "Aktiviere …" : "Für Missa aktivieren"}
          </Knopf>
        </div>
      </Meldung>
      <FehlerMeldung fehler={aktivieren.error} />
    </>
  );
}
