import {
  Activity,
  BellRing,
  Brain,
  Cpu,
  KeyRound,
  LayoutGrid,
  type LucideIcon,
  MonitorSmartphone,
  Network,
  NotebookPen,
  Phone,
  Plug,
  ScrollText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ComponentType } from "react";

import { Charakter } from "../charakter/Charakter";
import { Clients } from "../gateway/Clients";
import { Freigaben } from "../gateway/Freigaben";
import { Protokoll } from "../gateway/Protokoll";
import { Gedaechtnis } from "../gedaechtnis/Gedaechtnis";
import { Integrationen } from "../integrationen/Integrationen";
import { Katalog } from "../integrationen/Katalog";
import { Modelle } from "../modelle/Modelle";
import { Regeln } from "../regeln/Regeln";
import { Serverlast } from "../serverlast/Serverlast";
import { Zugaenge } from "../zugaenge/Zugaenge";

export interface NavEintrag {
  pfad: string;
  titel: string;
  symbol: LucideIcon;
  /** Kurz erklärt, was es in diesem Bereich gibt (auch Text der Platzhalter-Seite). */
  beschreibung: string;
  /** Die fertige Seite. Fehlt sie, erscheint ein Platzhalter. */
  seite?: ComponentType;
}

export interface NavGruppe {
  titel: string | null;
  eintraege: NavEintrag[];
}

export const NAVIGATION: NavGruppe[] = [
  {
    titel: null,
    eintraege: [
      {
        pfad: "/",
        titel: "Übersicht",
        symbol: Network,
        beschreibung: "Alles Eingerichtete als Verbindungsbaum mit Live-Status.",
      },
    ],
  },
  {
    titel: "Integrationen",
    eintraege: [
      {
        pfad: "/katalog",
        titel: "Katalog",
        symbol: LayoutGrid,
        beschreibung: "Neue Fähigkeiten für Missa in 3 Schritten hinzufügen: MCP-Server, REST-APIs, Vorlagen.",
        seite: Katalog,
      },
      {
        pfad: "/integrationen",
        titel: "Integrationen",
        symbol: Plug,
        beschreibung: "Eingerichtete Integrationen verwalten, testen, Rechte pro Funktion festlegen.",
        seite: Integrationen,
      },
      {
        pfad: "/zugaenge",
        titel: "Zugänge",
        symbol: KeyRound,
        beschreibung: "API-Keys, Tokens und Passwörter verschlüsselt speichern.",
        seite: Zugaenge,
      },
      {
        pfad: "/geraete",
        titel: "Geräte",
        symbol: Cpu,
        beschreibung: "Mikrocontroller (ESP32, Raspberry Pi Pico) als Sensoren und Knöpfe anbinden.",
      },
    ],
  },
  {
    titel: "Missa",
    eintraege: [
      {
        pfad: "/charakter",
        titel: "Charakter",
        symbol: Sparkles,
        beschreibung: "Missas Charakterprofil bearbeiten, mit Versionsverlauf und Test-Chat.",
        seite: Charakter,
      },
      {
        pfad: "/modelle",
        titel: "Modelle",
        symbol: Brain,
        beschreibung: "Schnelles und starkes Modell verwalten, mit Ersatzmodell bei Ausfall.",
        seite: Modelle,
      },
      {
        pfad: "/gedaechtnis",
        titel: "Gedächtnis",
        symbol: NotebookPen,
        beschreibung: "Was Missa sich gemerkt hat: ansehen, korrigieren, löschen.",
        seite: Gedaechtnis,
      },
      {
        pfad: "/regeln",
        titel: "Regeln",
        symbol: BellRing,
        beschreibung: "Regeln und Alarme wie „Serverlast über 90 % → Missa meldet sich“.",
        seite: Regeln,
      },
      {
        pfad: "/anrufe",
        titel: "Anrufe",
        symbol: Phone,
        beschreibung: "Telefonie: erlaubte Anrufer, Ruhezeiten und Anrufverlauf.",
      },
    ],
  },
  {
    titel: "Betrieb",
    eintraege: [
      {
        pfad: "/freigaben",
        titel: "Freigaben",
        symbol: ShieldCheck,
        beschreibung: "Aktionen, bei denen Missa erst nachfragen muss: erlauben oder ablehnen.",
        seite: Freigaben,
      },
      {
        pfad: "/clients",
        titel: "Clients",
        symbol: MonitorSmartphone,
        beschreibung: "Wer sich mit Missa Control verbinden darf (z. B. missa-core) – mit eigenem Token.",
        seite: Clients,
      },
      {
        pfad: "/protokoll",
        titel: "Protokoll",
        symbol: ScrollText,
        beschreibung: "Alle Aufrufe von Funktionen: wann, von wem, mit welchem Ergebnis.",
        seite: Protokoll,
      },
      {
        pfad: "/serverlast",
        titel: "Serverlast",
        symbol: Activity,
        beschreibung: "CPU, Arbeitsspeicher, Speicherplatz und GPU von ai01 mit Verlauf.",
        seite: Serverlast,
      },
    ],
  },
];

export const ALLE_EINTRAEGE: NavEintrag[] = NAVIGATION.flatMap((gruppe) => gruppe.eintraege);
