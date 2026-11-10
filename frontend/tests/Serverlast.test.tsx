import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Serverlast } from "../src/serverlast/Serverlast";
import type { Aktuell, Messpunkt, Uebersicht } from "../src/serverlast/serverlast";
import { backend, zeige } from "./hilfen";

const MESSWERTE: Uebersicht["messwerte"] = [
  { kennung: "cpu", titel: "CPU-Auslastung", einheit: "%" },
  { kennung: "ram", titel: "Arbeitsspeicher", einheit: "%" },
  { kennung: "speicher", titel: "Speicherplatz", einheit: "%" },
  { kennung: "last", titel: "Systemlast (1 Minute)", einheit: "" },
  { kennung: "cpu_temp", titel: "CPU-Temperatur", einheit: "°C" },
  { kennung: "gpu", titel: "GPU-Auslastung", einheit: "%" },
  { kennung: "gpu_speicher", titel: "GPU-Speicher", einheit: "%" },
  { kennung: "gpu_temp", titel: "GPU-Temperatur", einheit: "°C" },
];

function aktuell(teil: Partial<Aktuell> = {}): Aktuell {
  return {
    cpu: 42,
    ram: 61.4,
    speicher: 55,
    last: 1.52,
    cpu_temp: null,
    gpu: null,
    gpu_speicher: null,
    gpu_temp: null,
    cpu_kerne: 8,
    ram_gesamt_gb: 32,
    ram_belegt_gb: 19.6,
    speicher_gesamt_gb: 500,
    speicher_frei_gb: 225,
    gpus: [],
    gpu_vorhanden: false,
    ...teil,
  };
}

function verlauf(werte: number[], mitGpu = false): Messpunkt[] {
  const start = Date.now() - werte.length * 30_000;
  return werte.map((cpu, index) => ({
    zeit: new Date(start + index * 30_000).toISOString(),
    cpu,
    ram: 60,
    speicher: 55,
    last: 1.5,
    cpu_temp: null,
    gpu: mitGpu ? 30 : null,
    gpu_speicher: mitGpu ? 25 : null,
    gpu_temp: mitGpu ? 61 : null,
  }));
}

function antwort(teil: Partial<Uebersicht> = {}): Uebersicht {
  return { aktuell: aktuell(), verlauf: verlauf([20, 40, 60, 80]), zeitraum: "1h", intervall_sekunden: 30, messwerte: MESSWERTE, ...teil };
}

const KATALOG_AKTIV = { eintraege: [{ id: "serverlast", name: "Serverlast", eingerichtet: 1 }], probleme: [] };

test("zeigt aktuelle Werte als Kacheln und je Messwert ein Diagramm – ohne GPU keine GPU-Anzeige", async () => {
  backend({ "GET /api/serverlast?zeitraum=1h": antwort(), "GET /api/katalog": KATALOG_AKTIV });
  zeige(<Serverlast />);

  const cpu = (await screen.findByRole("meter", { name: "CPU-Auslastung" })).closest(".kachel") as HTMLElement;
  expect(within(cpu).getByText("42 %")).toBeInTheDocument();
  expect(within(cpu).getByText("8 Kerne · Last 1.52")).toBeInTheDocument();
  expect(screen.getByRole("meter", { name: "CPU-Auslastung" })).toHaveAttribute("aria-valuenow", "42");
  expect(screen.getByText("19.6 GB von 32 GB")).toBeInTheDocument();
  expect(screen.getByText("225 GB frei von 500 GB")).toBeInTheDocument();

  // Diagramme: CPU, Arbeitsspeicher, Speicherplatz – nichts zur GPU, keine Fehlermeldung.
  const diagramme = screen.getAllByRole("img").map((bild) => bild.getAttribute("aria-label"));
  expect(diagramme).toHaveLength(3);
  expect(diagramme[0]).toContain("CPU-Auslastung: Verlauf, zuletzt 80 %");
  expect(screen.queryByText(/GPU/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("mit GPU erscheinen GPU-Kacheln und -Diagramme", async () => {
  backend({
    "GET /api/serverlast?zeitraum=1h": antwort({
      aktuell: aktuell({
        gpu: 35,
        gpu_speicher: 25,
        gpu_temp: 61,
        gpu_vorhanden: true,
        gpus: [{ name: "RTX 4090", auslastung: 35, speicher_belegt_mb: 6000, speicher_gesamt_mb: 24000, temperatur: 61 }],
      }),
      verlauf: verlauf([10, 20], true),
    }),
    "GET /api/katalog": KATALOG_AKTIV,
  });
  zeige(<Serverlast />);
  expect(await screen.findByRole("meter", { name: "GPU-Auslastung" })).toHaveAttribute("aria-valuenow", "35");
  expect(screen.getByText("RTX 4090")).toBeInTheDocument();
  expect(screen.getByText("61 °C")).toBeInTheDocument();
  expect(screen.getAllByRole("img")).toHaveLength(6); // CPU, RAM, Speicher, GPU, GPU-Speicher, GPU-Temperatur
});

test("hohe und kritische Werte bekommen Symbol und Wort – nicht nur Farbe", async () => {
  backend({
    "GET /api/serverlast?zeitraum=1h": antwort({ aktuell: aktuell({ cpu: 96, ram: 80 }) }),
    "GET /api/katalog": KATALOG_AKTIV,
  });
  zeige(<Serverlast />);
  const cpu = (await screen.findByRole("meter", { name: "CPU-Auslastung" })).closest(".kachel") as HTMLElement;
  expect(cpu).toHaveClass("kritisch");
  expect(within(cpu).getByText(/kritisch/)).toBeInTheDocument();
  const ram = screen.getByRole("meter", { name: "Arbeitsspeicher" }).closest(".kachel") as HTMLElement;
  expect(ram).toHaveClass("hoch");
  expect(within(ram).getByText(/hoch/)).toBeInTheDocument();
  expect(screen.getByRole("meter", { name: "Speicherplatz" }).closest(".kachel")).toHaveClass("normal");
});

test("Zeitraum wechseln lädt den Verlauf neu; die Tabelle zeigt dieselben Werte", async () => {
  const aufrufe = backend({
    "GET /api/serverlast?zeitraum=1h": antwort(),
    "GET /api/serverlast?zeitraum=24h": antwort({ zeitraum: "24h", verlauf: verlauf([33, 66]) }),
    "GET /api/katalog": KATALOG_AKTIV,
  });
  const nutzer = userEvent.setup();
  zeige(<Serverlast />);

  expect(await screen.findByRole("radio", { name: "1 Stunde" })).toBeChecked();
  await nutzer.click(screen.getByRole("radio", { name: "24 Stunden" }));
  await waitFor(() => expect(screen.getAllByRole("img")[0]).toHaveAttribute("aria-label", expect.stringContaining("zuletzt 66 %")));
  expect(aufrufe.some((a) => a.pfad === "/api/serverlast?zeitraum=24h")).toBe(true);

  await nutzer.click(screen.getByRole("button", { name: "Als Tabelle anzeigen" }));
  const tabelle = screen.getByRole("table");
  expect(within(tabelle).getAllByRole("columnheader").map((kopf) => kopf.textContent)).toEqual([
    "Zeit",
    "CPU-Auslastung",
    "Arbeitsspeicher",
    "Speicherplatz",
  ]);
  const zeilen = within(tabelle).getAllByRole("row").slice(1);
  expect(zeilen).toHaveLength(2);
  expect(within(zeilen[0]).getByText("66 %")).toBeInTheDocument(); // neueste zuerst
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Als Diagramme anzeigen" }));
  expect(screen.getAllByRole("img")).toHaveLength(3);
});

test("Diagramm lässt sich mit Maus und Pfeiltasten ablesen", async () => {
  backend({ "GET /api/serverlast?zeitraum=1h": antwort(), "GET /api/katalog": KATALOG_AKTIV });
  zeige(<Serverlast />);
  const diagramm = (await screen.findAllByRole("img"))[0];

  // Fokus zeigt den letzten Wert, Pfeil links den davor – in allen Diagrammen zum selben Zeitpunkt.
  const cpu = within(diagramm.closest(".diagramm-flaeche") as HTMLElement);
  fireEvent.focus(diagramm);
  expect(await cpu.findByText("80 %")).toBeInTheDocument();
  fireEvent.keyDown(diagramm, { key: "ArrowLeft" });
  expect(await cpu.findByText("60 %")).toBeInTheDocument();
  expect(screen.getAllByRole("status").length).toBeGreaterThanOrEqual(3);
  fireEvent.keyDown(diagramm, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
});

test("ohne Messwerte steht eine Erklärung statt eines leeren Diagramms", async () => {
  backend({ "GET /api/serverlast?zeitraum=1h": antwort({ verlauf: [] }), "GET /api/katalog": KATALOG_AKTIV });
  zeige(<Serverlast />);
  expect((await screen.findAllByText("Noch keine Messwerte in diesem Zeitraum.")).length).toBe(3);
  expect(screen.getAllByRole("img")[0]).toHaveAttribute("aria-label", "CPU-Auslastung: noch keine Messwerte.");
});

test("Hinweis mit einem Klick: Integration für Missa aktivieren", async () => {
  let eingerichtet = 0;
  const aufrufe = backend({
    "GET /api/serverlast?zeitraum=1h": antwort(),
    "GET /api/katalog": () => ({ eintraege: [{ id: "serverlast", name: "Serverlast", eingerichtet }], probleme: [] }),
    "POST /api/integrationen": () => {
      eingerichtet = 1;
      return { id: 1 };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Serverlast />);

  expect(await screen.findByText(/Missa kann die Serverlast erst abfragen, wenn die Integration „Serverlast“ aktiv ist/)).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Für Missa aktivieren" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Für Missa aktivieren" })).not.toBeInTheDocument());
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ manifest_id: "serverlast", konfig: {} });
});
