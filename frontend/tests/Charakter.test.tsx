import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Charakter } from "../src/charakter/Charakter";
import type { Profil, ProfilAntwort, Version, VersionDetail } from "../src/charakter/profil";
import { backend, TestFehler, zeige } from "./hilfen";

const PROFIL: Profil = {
  name: "Missa",
  aussprache: "Mi-ssa",
  wesen: "Aufmerksam und warmherzig.",
  sprechweise: "Kurz und natürlich.",
  darf: ["Termine nachschlagen"],
  darf_nicht: ["Etwas ohne Auftrag löschen"],
  fremde: "Höflich, aber zurückhaltend.",
  systemprompt: "",
};

const V1: Version = { id: 1, erstellt: "2026-01-15T12:00:00+00:00", kommentar: "Erste Fassung" };
const V2: Version = { id: 2, erstellt: "2026-01-15T12:05:00+00:00", kommentar: "Frecher" };

function antwort(profil: Profil, version: Version | null, mehr: Partial<ProfilAntwort> = {}): ProfilAntwort {
  return { profil, version, systemprompt: `Du bist ${profil.name}.`, ...mehr };
}

const MODELLE = {
  modelle: [],
  rollen: [
    { id: 1, kennung: "schnell", modellname: "missa-schnell", name: "Schnell", beschreibung: "", haupt_modell_id: 1, ersatz_modell_id: null, fest: true },
    { id: 2, kennung: "stark", modellname: "missa-stark", name: "Stark", beschreibung: "", haupt_modell_id: 2, ersatz_modell_id: null, fest: true },
    { id: 3, kennung: "leer", modellname: "missa-leer", name: "Leer", beschreibung: "", haupt_modell_id: null, ersatz_modell_id: null, fest: false },
  ],
};

test("bearbeiten und speichern: neue Version mit Kommentar", async () => {
  const aufrufe = backend({
    "GET /api/profil": antwort(PROFIL, V1),
    "GET /api/modelle": MODELLE,
    "PUT /api/profil": (koerper) => antwort((koerper as { profil: Profil }).profil, V2, { unveraendert: false }),
    "GET /api/profil/versionen": [V2, V1],
  });
  const nutzer = userEvent.setup();
  zeige(<Charakter />);

  const wesen = await screen.findByLabelText("Wesen");
  expect(wesen).toHaveValue("Aufmerksam und warmherzig.");
  expect(screen.getByLabelText("Regeln: Das darf Missa")).toHaveValue("Termine nachschlagen");
  const speichern = screen.getByRole("button", { name: "Speichern" });
  expect(speichern).toBeDisabled(); // noch nichts geändert

  await nutzer.type(wesen, " Und frech.");
  await nutzer.type(screen.getByLabelText("Regeln: Das darf Missa"), "{Enter}Rückfragen stellen");
  expect(screen.getByText("ungespeichert")).toBeInTheDocument();
  await nutzer.type(screen.getByLabelText("Kommentar zur Version"), "Frecher");
  await nutzer.click(speichern);

  expect(await screen.findByText("Gespeichert als neue Version.")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "PUT")?.koerper).toEqual({
    profil: { ...PROFIL, wesen: "Aufmerksam und warmherzig. Und frech.", darf: ["Termine nachschlagen", "Rückfragen stellen"] },
    kommentar: "Frecher",
  });
  expect(screen.queryByText("ungespeichert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Kommentar zur Version")).toHaveValue("");
});

test("Test-Chat schickt das ungespeicherte Profil, den Verlauf und die gewählte Rolle", async () => {
  let runde = 0;
  const aufrufe = backend({
    "GET /api/profil": antwort(PROFIL, V1),
    "GET /api/modelle": MODELLE,
    "POST /api/profil/testchat": () => {
      runde += 1;
      return { antwort: runde === 1 ? "Ich bin Missa." : "Alles, was du mir erlaubst.", modell: "Gross (70B)", dauer_ms: 1840 };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Charakter />);

  await nutzer.type(await screen.findByLabelText("Wesen"), " Heute gut gelaunt.");
  const rollen = await screen.findByLabelText("Modell-Rolle");
  expect(within(rollen).getAllByRole("option").map((o) => o.textContent)).toEqual(["Schnell", "Stark"]); // nur Rollen mit Modell
  await nutzer.selectOptions(rollen, "stark");

  await nutzer.type(screen.getByLabelText("Nachricht an Missa"), "Wer bist du?{Enter}");
  const chat = screen.getByRole("log", { name: "Test-Chat" });
  expect(await within(chat).findByText("Ich bin Missa.")).toBeInTheDocument();
  expect(screen.getByText("Antwort von Gross (70B) · 1.8 s")).toBeInTheDocument();

  await nutzer.type(screen.getByLabelText("Nachricht an Missa"), "Was kannst du?");
  await nutzer.click(screen.getByRole("button", { name: "Senden" }));
  expect(await within(chat).findByText("Alles, was du mir erlaubst.")).toBeInTheDocument();

  const gesendet = aufrufe.filter((a) => a.pfad === "/api/profil/testchat").map((a) => a.koerper as { profil: Profil; rolle: string; nachrichten: unknown[] });
  expect(gesendet[0].profil.wesen).toBe("Aufmerksam und warmherzig. Heute gut gelaunt."); // ungespeichert
  expect(gesendet[0].rolle).toBe("stark");
  expect(gesendet[1].nachrichten).toEqual([
    { von: "nutzer", text: "Wer bist du?" },
    { von: "missa", text: "Ich bin Missa." },
    { von: "nutzer", text: "Was kannst du?" },
  ]);

  await nutzer.click(screen.getByRole("button", { name: /Neu beginnen/ }));
  expect(within(chat).queryByText("Ich bin Missa.")).not.toBeInTheDocument();
});

test("Test-Chat zeigt Zeitüberschreitung mit klarer Meldung; ohne Modell ein Hinweis auf „Modelle“", async () => {
  backend({
    "GET /api/profil": antwort(PROFIL, V1),
    "GET /api/modelle": MODELLE,
    "POST /api/profil/testchat": new TestFehler(504, "Das Modell hat nicht innerhalb von 120 Sekunden geantwortet.", "Mit der Rolle „schnell“ versuchen."),
  });
  const nutzer = userEvent.setup();
  const { unmount } = zeige(<Charakter />);
  await nutzer.type(await screen.findByLabelText("Nachricht an Missa"), "Hallo{Enter}");
  const fehler = await screen.findByRole("alert");
  expect(fehler).toHaveTextContent("nicht innerhalb von 120 Sekunden geantwortet");
  expect(fehler).toHaveTextContent("Mit der Rolle „schnell“ versuchen.");
  unmount();

  backend({ "GET /api/profil": antwort(PROFIL, V1), "GET /api/modelle": { modelle: [], rollen: [MODELLE.rollen[2]] } });
  zeige(<Charakter />);
  expect(await screen.findByText(/braucht mindestens eine Rolle ein Modell/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Modelle" })).toHaveAttribute("href", "/modelle");
});

test("Versionen: Unterschiede ansehen und alte Version wiederherstellen", async () => {
  const frech = { ...PROFIL, wesen: "Frech und direkt." };
  let aktuell = antwort(frech, V2);
  const detail: VersionDetail = {
    ...V1,
    profil: PROFIL,
    unterschiede: [
      { feld: "wesen", titel: "Wesen", zeilen: [{ art: "entfernt", text: "Aufmerksam und warmherzig." }, { art: "neu", text: "Frech und direkt." }] },
    ],
  };
  const V3: Version = { id: 3, erstellt: "2026-01-15T12:10:00+00:00", kommentar: "Wiederhergestellt: Version vom 15.01.2026 12:00 UTC" };
  const aufrufe = backend({
    "GET /api/profil": () => aktuell,
    "GET /api/modelle": MODELLE,
    "GET /api/profil/versionen": () => (aktuell.version?.id === 3 ? [V3, V2, V1] : [V2, V1]),
    "GET /api/profil/versionen/1": detail,
    "POST /api/profil/versionen/1/wiederherstellen": () => {
      aktuell = antwort(PROFIL, V3);
      return aktuell;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Charakter />);

  expect(await screen.findByLabelText("Wesen")).toHaveValue("Frech und direkt.");
  await nutzer.click(screen.getByRole("tab", { name: "Versionen" }));
  expect(await screen.findByText("Frecher")).toBeInTheDocument();
  expect(screen.getByText("aktuell")).toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: /Erste Fassung/ }));
  expect(await screen.findByText(/− Aufmerksam und warmherzig\./)).toBeInTheDocument();
  expect(screen.getByText(/\+ Frech und direkt\./)).toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: /Diese Version wiederherstellen/ }));
  // Der Editor zeigt danach wieder den alten Stand – als neue, aktuelle Version.
  await waitFor(() => expect(screen.getByLabelText("Wesen")).toHaveValue("Aufmerksam und warmherzig."));
  expect(aufrufe.some((a) => a.methode === "POST" && a.pfad.endsWith("/wiederherstellen"))).toBe(true);
});

test("Importieren und Beispiel laden füllen den Editor, speichern aber nicht von selbst", async () => {
  const aufrufe = backend({
    "GET /api/profil": antwort(PROFIL, null),
    "GET /api/modelle": MODELLE,
    "POST /api/profil/import": { profil: { ...PROFIL, name: "Mia" } },
    "GET /api/profil/beispiel": { profil: { ...PROFIL, name: "Beispiel-Missa" } },
  });
  const nutzer = userEvent.setup();
  zeige(<Charakter />);

  expect(await screen.findByText("Noch nicht gespeichert")).toBeInTheDocument();
  const datei = new File(["name: Mia\n"], "profil.yaml", { type: "application/yaml" });
  await nutzer.upload(screen.getByLabelText("YAML-Datei auswählen"), datei);
  await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("Mia"));
  expect(screen.getByText(/Gespeichert wird erst mit „Speichern“/)).toBeInTheDocument();
  expect(aufrufe.find((a) => a.pfad === "/api/profil/import")?.koerper).toEqual({ yaml: "name: Mia\n" });

  await nutzer.click(screen.getByRole("button", { name: "Beispiel laden" }));
  await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("Beispiel-Missa"));
  expect(aufrufe.some((a) => a.methode === "PUT")).toBe(false);
  expect(screen.getByRole("link", { name: /Exportieren/ })).toHaveAttribute("href", "/api/profil/export");
});

test("Reiter Systemprompt zeigt die Vorschau des ungespeicherten Profils", async () => {
  const aufrufe = backend({
    "GET /api/profil": antwort(PROFIL, V1),
    "GET /api/modelle": MODELLE,
    "POST /api/profil/vorschau": (koerper) => ({ systemprompt: `Du bist ${(koerper as Profil).name}.\n\nDein Wesen: …` }),
  });
  const nutzer = userEvent.setup();
  zeige(<Charakter />);
  await nutzer.clear(await screen.findByLabelText("Name"));
  await nutzer.type(screen.getByLabelText("Name"), "Mia");
  await nutzer.click(screen.getByRole("tab", { name: "Systemprompt" }));
  expect(await screen.findByText(/Du bist Mia\./)).toBeInTheDocument();
  expect(aufrufe.some((a) => a.pfad === "/api/profil/vorschau")).toBe(true);
});
