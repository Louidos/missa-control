import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, type Edge, Handle, type Node, type NodeChange, type NodeProps, Panel, Position, ReactFlow } from "@xyflow/react";
import {
  BellRing,
  Bot,
  Box,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleMinus,
  Cpu,
  KeyRound,
  LayoutList,
  type LucideIcon,
  MonitorSmartphone,
  Network,
  Plug,
  Plus,
  RefreshCw,
  Route,
  TriangleAlert,
  Wand2,
  Wrench,
  X,
} from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { Link } from "react-router";

import "@xyflow/react/dist/style.css";

import { api } from "../api";
import { datum } from "../ui/format";
import { FehlerMeldung, Knopf, Lade, Meldung, type Status, StatusMarke } from "../ui/ui";
import {
  anordnen,
  ART_NAME,
  FILTER,
  type Gezeichnet,
  type Knoten,
  type KnotenArt,
  type Ort,
  STATUS,
  STATUS_NAME,
  type Uebersicht as Daten,
  useStatus,
} from "./uebersicht";

const ART_SYMBOL: Record<Gezeichnet["art"], LucideIcon> = {
  missa: Bot,
  client: MonitorSmartphone,
  rolle: Route,
  modell: Box,
  integration: Plug,
  geraet: Cpu,
  zugang: KeyRound,
  regel: BellRing,
  funktion: Wrench,
};
const STATUS_SYMBOL: Record<Status, LucideIcon> = { ok: CircleCheck, warn: TriangleAlert, fehler: CircleAlert, grau: CircleMinus };
const REIHENFOLGE: KnotenArt[] = ["missa", "client", "rolle", "modell", "integration", "geraet", "zugang", "regel"];

type FlowKnoten = Node<{ eintrag: Gezeichnet }, "knoten">;

/** Was die Knoten im Graphen ausser ihren eigenen Daten wissen müssen. */
const Bedienung = createContext<{ aufgeklappt: ReadonlySet<string>; umklappen: (id: string) => void }>({
  aufgeklappt: new Set(),
  umklappen: () => undefined,
});

function StatusZeichen({ status }: { status: Status }) {
  const Symbol = STATUS_SYMBOL[status];
  return (
    <span className={`status-zeichen ${status}`} role="img" aria-label={STATUS_NAME[status]} title={STATUS_NAME[status]}>
      <Symbol aria-hidden />
    </span>
  );
}

/** Ein Knoten im Graphen: Symbol, Name, Untertitel und rechts der Status (Farbe und Zeichen). */
function KnotenKarte({ data, selected }: NodeProps<FlowKnoten>) {
  const { eintrag } = data;
  const { aufgeklappt, umklappen } = useContext(Bedienung);
  const Symbol = ART_SYMBOL[eintrag.art];
  if (eintrag.art === "funktion" && eintrag.funktion) {
    return (
      <div className={`graph-knoten funktion${selected ? " gewaehlt" : ""}`}>
        <Handle type="target" position={Position.Left} isConnectable={false} />
        <code className="fuellen">{eintrag.funktion.name}</code>
        <span className={`etikett ${eintrag.funktion.recht === "gesperrt" ? "" : eintrag.funktion.schreibend ? "schreibend" : "lesend"}`}>
          {eintrag.funktion.recht_name}
        </span>
      </div>
    );
  }
  const knoten = eintrag.knoten;
  if (!knoten) return null;
  const funktionen = knoten.funktionen?.length ?? 0;
  const offen = aufgeklappt.has(knoten.id);
  return (
    <div className={`graph-knoten ${knoten.art} ${knoten.status}${selected ? " gewaehlt" : ""}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="graph-symbol" aria-hidden>
        {knoten.symbol || <Symbol />}
      </span>
      <div className="graph-text">
        <div className="graph-name">{knoten.name}</div>
        <div className="graph-untertitel">{knoten.untertitel}</div>
        {funktionen > 0 && (
          <button
            type="button"
            className="graph-aufklapper nodrag"
            aria-expanded={offen}
            onClick={(ereignis) => {
              ereignis.stopPropagation();
              umklappen(knoten.id);
            }}
          >
            {offen ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
            {funktionen} Funktion{funktionen === 1 ? "" : "en"}
          </button>
        )}
      </div>
      <StatusZeichen status={knoten.status} />
      <Handle type="source" position={Position.Right} isConnectable={false} />
      {/* Für Querverbindungen zwischen Knoten, die übereinander liegen. */}
      <Handle id="quelle-oben" type="source" position={Position.Top} isConnectable={false} />
      <Handle id="quelle-unten" type="source" position={Position.Bottom} isConnectable={false} />
      <Handle id="ziel-oben" type="target" position={Position.Top} isConnectable={false} />
      <Handle id="ziel-unten" type="target" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

const KNOTEN_ARTEN = { knoten: KnotenKarte };

/** Startseite: alles Eingerichtete als Verbindungsbaum mit Live-Status. */
export function Uebersicht() {
  const queryClient = useQueryClient();
  const daten = useStatus();
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);
  const [aufgeklappt, setAufgeklappt] = useState<ReadonlySet<string>>(new Set());
  const [ausgeblendet, setAusgeblendet] = useState<ReadonlySet<string>>(new Set());
  // Auf schmalen Bildschirmen (Handy) beginnt die Seite mit der Liste: Dort ist alles ohne Zoomen lesbar.
  const [schmal] = useState(() => typeof window.matchMedia === "function" && window.matchMedia("(max-width: 700px)").matches);
  const [liste, setListe] = useState(schmal);
  // Beim Ziehen: Positionen, die der Server noch nicht kennt.
  const [gezogen, setGezogen] = useState<Record<string, Ort>>({});

  const pruefen = useMutation({
    mutationFn: () => api.post<Daten>("/api/status/pruefen"),
    onSuccess: (neu) => queryClient.setQueryData(STATUS, neu),
  });
  const merken = useMutation({
    mutationFn: (positionen: Record<string, Ort>) => api.put("/api/status/positionen", { positionen }),
  });
  const zuruecksetzen = useMutation({
    mutationFn: () => api.del("/api/status/positionen"),
    onSuccess: async () => {
      setGezogen({});
      await queryClient.invalidateQueries({ queryKey: STATUS });
    },
  });

  const umklappen = useCallback(
    (id: string) =>
      setAufgeklappt((vorher) => {
        const neu = new Set(vorher);
        if (!neu.delete(id)) neu.add(id);
        return neu;
      }),
    [],
  );
  const bedienung = useMemo(() => ({ aufgeklappt, umklappen }), [aufgeklappt, umklappen]);

  const uebersicht = daten.data;
  const anordnung = useMemo(() => {
    if (!uebersicht) return { knoten: [], kanten: [] };
    const arten = new Set(FILTER.filter((filter) => ausgeblendet.has(filter.wert)).flatMap((filter) => filter.arten));
    return anordnen(uebersicht, { ausgeblendet: arten, aufgeklappt, positionen: { ...uebersicht.positionen, ...gezogen } });
  }, [uebersicht, ausgeblendet, aufgeklappt, gezogen]);

  const knoten: FlowKnoten[] = useMemo(
    () =>
      anordnung.knoten.map((eintrag) => ({
        id: eintrag.id,
        type: "knoten",
        position: eintrag.ort,
        width: eintrag.breite,
        height: eintrag.hoehe,
        data: { eintrag },
        selected: eintrag.id === gewaehlt,
        draggable: eintrag.art !== "funktion",
        ariaLabel: eintrag.knoten ? `${eintrag.knoten.name}, ${eintrag.knoten.untertitel}: ${STATUS_NAME[eintrag.knoten.status]}` : eintrag.funktion?.name,
      })),
    [anordnung.knoten, gewaehlt],
  );
  const kanten: Edge[] = useMemo(() => {
    const orte = new Map(anordnung.knoten.map((eintrag) => [eintrag.id, eintrag.ort]));
    return anordnung.kanten.map((kante) => {
      // Querverbindungen (Regel → Integration) laufen senkrecht – beide Knoten stehen meist in derselben Spalte.
      const abwaerts = (orte.get(kante.von)?.y ?? 0) <= (orte.get(kante.nach)?.y ?? 0);
      const quer = kante.art === "aktion" ? { sourceHandle: abwaerts ? "quelle-unten" : "quelle-oben", targetHandle: abwaerts ? "ziel-oben" : "ziel-unten" } : {};
      return { id: kante.id, source: kante.von, target: kante.nach, className: `graph-kante ${kante.art}`, focusable: false, selectable: false, ...quer };
    });
  }, [anordnung]);

  const beiAenderung = (aenderungen: NodeChange<FlowKnoten>[]) => {
    for (const aenderung of aenderungen) {
      if (aenderung.type === "select" && aenderung.selected) setGewaehlt(aenderung.id);
      if (aenderung.type === "position" && aenderung.position) {
        const ort = { x: Math.round(aenderung.position.x), y: Math.round(aenderung.position.y) };
        setGezogen((vorher) => ({ ...vorher, [aenderung.id]: ort }));
        if (aenderung.dragging === false) merken.mutate({ [aenderung.id]: ort });
      }
    }
  };

  if (daten.isPending) return <Lade />;
  if (daten.isError || !uebersicht) return <FehlerMeldung fehler={daten.error} />;

  const auswahl = anordnung.knoten.find((eintrag) => eintrag.id === gewaehlt) ?? null;
  const verschoben = Object.keys(uebersicht.positionen).length + Object.keys(gezogen).length > 0;
  const nurGrundgeruest = uebersicht.knoten.every((eintrag) => eintrag.art === "missa" || eintrag.art === "rolle");
  const { zusammenfassung } = uebersicht;

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <div className="reihe" role="status" aria-label="Zusammenfassung">
          {(["fehler", "warn", "ok", "grau"] as Status[]).map(
            (status) =>
              zusammenfassung[status] > 0 && (
                <StatusMarke key={status} status={status}>
                  {zusammenfassung[status]} {STATUS_NAME[status]}
                </StatusMarke>
              ),
          )}
        </div>
        <div className="reihe">
          <Knopf klein onClick={() => pruefen.mutate()} disabled={pruefen.isPending}>
            <RefreshCw aria-hidden />
            {pruefen.isPending ? "Prüfe …" : "Jetzt prüfen"}
          </Knopf>
          {verschoben && !liste && (
            <Knopf klein onClick={() => zuruecksetzen.mutate()} disabled={zuruecksetzen.isPending}>
              <Wand2 aria-hidden />
              Automatisch anordnen
            </Knopf>
          )}
          <Knopf klein aria-pressed={liste} onClick={() => setListe(!liste)}>
            {liste ? <Network aria-hidden /> : <LayoutList aria-hidden />}
            {liste ? "Als Graph anzeigen" : "Als Liste anzeigen"}
          </Knopf>
        </div>
      </div>

      <div className="reihe" role="group" aria-label="Anzeigen">
        {FILTER.map((filter) => {
          const anzahl = uebersicht.knoten.filter((eintrag) => filter.arten.includes(eintrag.art)).length;
          const an = !ausgeblendet.has(filter.wert);
          return (
            <button
              key={filter.wert}
              type="button"
              className="filter-knopf"
              aria-pressed={an}
              onClick={() =>
                setAusgeblendet((vorher) => {
                  const neu = new Set(vorher);
                  if (!neu.delete(filter.wert)) neu.add(filter.wert);
                  return neu;
                })
              }
            >
              {filter.titel} <span className="gedaempft">{anzahl}</span>
            </button>
          );
        })}
      </div>

      <FehlerMeldung fehler={pruefen.error ?? merken.error ?? zuruecksetzen.error} />
      {nurGrundgeruest && (
        <Meldung art="info">
          <div className="reihe zwischen">
            <span>Noch ist nichts eingerichtet. Im Katalog kommt die erste Integration in 3 Schritten dazu.</span>
            <Link className="knopf klein" to="/katalog">
              Zum Katalog
            </Link>
          </div>
        </Meldung>
      )}

      <div className={`uebersicht${auswahl ? " mit-details" : ""}`}>
        {liste ? (
          <ListenAnsicht knoten={anordnung.knoten} gewaehlt={gewaehlt} onWaehlen={setGewaehlt} />
        ) : (
          <div className="karte ohne-rand graph" aria-label="Verbindungsbaum">
            <Bedienung.Provider value={bedienung}>
              <ReactFlow
                nodes={knoten}
                edges={kanten}
                nodeTypes={KNOTEN_ARTEN}
                onNodesChange={beiAenderung}
                onPaneClick={() => setGewaehlt(null)}
                nodesConnectable={false}
                edgesFocusable={false}
                deleteKeyCode={null}
                minZoom={0.2}
                maxZoom={1.5}
                colorMode="system"
                fitView
                fitViewOptions={{ padding: 0.12, maxZoom: 1, minZoom: schmal ? 0.6 : 0.2 }}
              >
                <Background gap={22} />
                <Controls showInteractive={false} />
                <Panel position="top-right">
                  <Link className="knopf haupt plus-knopf" to="/katalog" aria-label="Integration hinzufügen (Katalog öffnen)" title="Integration hinzufügen">
                    <Plus aria-hidden />
                  </Link>
                </Panel>
              </ReactFlow>
            </Bedienung.Provider>
          </div>
        )}
        {auswahl && <Seitenleiste eintrag={auswahl} elternteil={uebersicht.knoten.find((k) => k.id === auswahl.elternteil)} onSchliessen={() => setGewaehlt(null)} />}
      </div>
      <p className="gedaempft klein">
        Die Übersicht aktualisiert sich alle 30 Sekunden. Das Panel prüft missa-core (nur lesend) und die Integrationen alle 20
        Sekunden von selbst. Knoten lassen sich verschieben – die Anordnung bleibt gespeichert.
      </p>
    </div>
  );
}

function ListenAnsicht({ knoten, gewaehlt, onWaehlen }: { knoten: Gezeichnet[]; gewaehlt: string | null; onWaehlen: (id: string) => void }) {
  const echte = knoten.flatMap((eintrag) => (eintrag.knoten ? [eintrag.knoten] : []));
  return (
    <div className="stapel">
      {REIHENFOLGE.map((art) => {
        const gruppe = echte.filter((eintrag) => eintrag.art === art);
        if (gruppe.length === 0) return null;
        return (
          <section key={art} className="karte stapel eng" aria-label={ART_NAME[art]}>
            <h2>{ART_NAME[art]}</h2>
            <ul className="knoten-liste">
              {gruppe.map((eintrag) => (
                <li key={eintrag.id}>
                  <button type="button" aria-current={gewaehlt === eintrag.id} onClick={() => onWaehlen(eintrag.id)}>
                    <StatusZeichen status={eintrag.status} />
                    <span className="fuellen">
                      <strong>{eintrag.name}</strong> <span className="gedaempft klein">{eintrag.untertitel}</span>
                      <span className="gedaempft klein knoten-liste-text">{eintrag.status_text}</span>
                    </span>
                    <ChevronRight aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function Seitenleiste({ eintrag, elternteil, onSchliessen }: { eintrag: Gezeichnet; elternteil?: Knoten; onSchliessen: () => void }) {
  if (eintrag.art === "funktion" && eintrag.funktion) {
    const funktion = eintrag.funktion;
    return (
      <aside className="karte stapel eng seitenleiste" aria-label="Details">
        <div className="dialog-kopf">
          <h2 className="mono">{funktion.name}</h2>
          <Knopf art="still" klein aria-label="Details schliessen" onClick={onSchliessen}>
            <X aria-hidden />
          </Knopf>
        </div>
        <div className="gedaempft klein">Funktion{elternteil ? ` von „${elternteil.name}“` : ""}</div>
        <p>{funktion.beschreibung || "Ohne Beschreibung."}</p>
        <dl className="details">
          <dt>Recht für Missa</dt>
          <dd>{funktion.recht_name}</dd>
          <dt>Art</dt>
          <dd>{funktion.schreibend ? "verändert etwas" : "liest nur"}</dd>
        </dl>
        <div>
          <Link className="knopf" to="/integrationen">
            Rechte ändern
          </Link>
        </div>
      </aside>
    );
  }
  const knoten = eintrag.knoten;
  if (!knoten) return null;
  const details = knoten.details.filter((detail) => detail.wert !== null && detail.wert !== "");
  return (
    <aside className="karte stapel eng seitenleiste" aria-label="Details">
      <div className="dialog-kopf">
        <h2>
          {knoten.symbol ? `${knoten.symbol} ` : ""}
          {knoten.name}
        </h2>
        <Knopf art="still" klein aria-label="Details schliessen" onClick={onSchliessen}>
          <X aria-hidden />
        </Knopf>
      </div>
      <div className="gedaempft klein">{knoten.untertitel}</div>
      <div>
        <StatusMarke status={knoten.status}>{STATUS_NAME[knoten.status]}</StatusMarke>
      </div>
      {knoten.status_text && <p>{knoten.status_text}</p>}
      {knoten.hinweis && <p className="gedaempft klein">{knoten.hinweis}</p>}
      {details.length > 0 && (
        <dl className="details">
          {details.map((detail) => (
            <div key={detail.titel}>
              <dt>{detail.titel}</dt>
              <dd>{detail.zeit ? datum(String(detail.wert)) : detail.wert}</dd>
            </div>
          ))}
        </dl>
      )}
      {(knoten.funktionen?.length ?? 0) > 0 && (
        <div className="stapel eng">
          <h3>Funktionen</h3>
          <ul className="funktions-liste">
            {knoten.funktionen?.map((funktion) => (
              <li key={funktion.name}>
                <code>{funktion.name}</code>
                <span className="gedaempft klein">{funktion.recht_name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {knoten.link && (
        <div>
          <Link className="knopf haupt" to={knoten.link.pfad}>
            {knoten.link.titel}
          </Link>
        </div>
      )}
    </aside>
  );
}
