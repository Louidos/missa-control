import { useId } from "react";

import { Feld } from "../ui/ui";

interface Schema {
  properties?: Record<string, Record<string, unknown>>;
  required?: string[];
}

interface Props {
  /** Die Parameter einer Funktion (JSON-Schema, so wie sie die Integration beschreibt). */
  schema: Schema;
  werte: Record<string, unknown>;
  onAendern: (werte: Record<string, unknown>) => void;
}

/** Der eigentliche Typ eines Parameters – auch bei „Text oder leer“ (anyOf mit null). */
function typVon(angabe: Record<string, unknown>): { typ: string; auswahl?: unknown[] } {
  const varianten = (angabe.anyOf as Record<string, unknown>[] | undefined)?.filter((variante) => variante.type !== "null");
  const kern = varianten?.length === 1 ? varianten[0] : angabe;
  return { typ: String(kern.type ?? "string"), auswahl: kern.enum as unknown[] | undefined };
}

/** Formularfelder für die Parameter einer Funktion: Text, Zahl, Ja/Nein oder Auswahl – je nach Typ. */
export function ParameterFelder({ schema, werte, onAendern }: Props) {
  const id = useId();
  const eigenschaften = Object.entries(schema.properties ?? {});
  if (eigenschaften.length === 0) return <p className="gedaempft klein">Diese Funktion braucht keine Parameter.</p>;

  const setze = (name: string, wert: unknown) => {
    const neu = { ...werte };
    if (wert === undefined || wert === "") delete neu[name];
    else neu[name] = wert;
    onAendern(neu);
  };

  return (
    <>
      {eigenschaften.map(([name, angabe]) => {
        const feldId = `${id}-${name}`;
        const pflicht = schema.required?.includes(name) ?? false;
        const { typ, auswahl } = typVon(angabe);
        const wert = werte[name];
        let eingabe;
        if (auswahl) {
          eingabe = (
            <select id={feldId} value={wert === undefined ? "" : String(wert)} onChange={(e) => setze(name, auswahl.find((option) => String(option) === e.target.value))}>
              <option value="">{pflicht ? "Bitte wählen …" : "(keine Angabe)"}</option>
              {auswahl.map((option) => (
                <option key={String(option)} value={String(option)}>
                  {String(option)}
                </option>
              ))}
            </select>
          );
        } else if (typ === "boolean") {
          eingabe = (
            <select id={feldId} value={wert === undefined ? "" : wert ? "ja" : "nein"} onChange={(e) => setze(name, e.target.value === "" ? undefined : e.target.value === "ja")}>
              <option value="">{pflicht ? "Bitte wählen …" : "(keine Angabe)"}</option>
              <option value="ja">Ja</option>
              <option value="nein">Nein</option>
            </select>
          );
        } else if (typ === "integer" || typ === "number") {
          eingabe = (
            <input
              id={feldId}
              type="number"
              step={typ === "integer" ? 1 : "any"}
              value={wert === undefined ? "" : String(wert)}
              onChange={(e) => setze(name, e.target.value === "" ? undefined : Number(e.target.value))}
            />
          );
        } else if (typ === "string") {
          eingabe = <input id={feldId} type="text" value={typeof wert === "string" ? wert : ""} onChange={(e) => setze(name, e.target.value)} />;
        } else {
          // Listen und Verschachteltes: als JSON eingeben.
          eingabe = (
            <input
              id={feldId}
              type="text"
              className="mono"
              placeholder='JSON, z. B. ["a", "b"]'
              defaultValue={wert === undefined ? "" : JSON.stringify(wert)}
              onChange={(e) => {
                try {
                  setze(name, e.target.value.trim() === "" ? undefined : JSON.parse(e.target.value));
                } catch {
                  setze(name, e.target.value);
                }
              }}
            />
          );
        }
        return (
          <Feld key={name} titel={name} fuer={feldId} pflicht={pflicht} hilfe={typeof angabe.description === "string" ? angabe.description : undefined}>
            {eingabe}
          </Feld>
        );
      })}
    </>
  );
}
