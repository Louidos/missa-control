"""Nextcloud-Kalender: einrichten, Termine lesen und – nach Freigabe – eintragen, ändern, löschen.

Als Gegenstelle läuft ein echter CalDAV-Server (Radicale). Er spricht denselben Standard wie Nextcloud.
Die Uhr des Panels steht auf Donnerstag, 15.01.2026, 13:00 Uhr Ortszeit (Europe/Zurich).
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hilfen import client_token, mcp_client, mcp_text, warte_auf
from server import KalenderServer, LaufenderServer, freier_port

pytestmark = pytest.mark.anyio

KOPF = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Nextcloud//Test//DE\n"
FUSS = "END:VCALENDAR\n"


def _ical(inhalt: str) -> str:
    return f"{KOPF}BEGIN:VEVENT\nDTSTAMP:20260101T000000Z\n{inhalt.strip()}\nEND:VEVENT\n{FUSS}"


@pytest.fixture
def nextcloud(tmp_path: Path) -> Iterator[KalenderServer]:
    with KalenderServer(tmp_path / "caldav") as server:
        server.kalender_anlegen("privat", "Persönlich")
        server.kalender_anlegen("arbeit", "Arbeit")
        server.kalender_anlegen("aufgaben", "Aufgaben", art="VTODO")  # reine Aufgabenliste
        yield server


_nummer = itertools.count(1)


def _zugang(admin: TestClient, server: KalenderServer, passwort: str | None = None) -> int:
    antwort = admin.post(
        "/api/zugaenge",
        json={
            "name": f"Nextcloud {next(_nummer)}",
            "typ": "benutzer_passwort",
            "benutzer": server.benutzer,
            "wert": passwort or server.passwort,
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def _einrichten(admin: TestClient, server: KalenderServer, **mehr: Any) -> dict:
    """Die drei Schritte des Assistenten: Formular → testen (zeigt die Kalender) → Kalender wählen und aktivieren."""
    konfig: dict[str, Any] = {"url": server.url, "zugang": _zugang(admin, server)}
    test = admin.post(
        "/api/integrationen/testen", json={"manifest_id": "nextcloud-kalender", "konfig": konfig}
    ).json()
    assert test["ok"] is True, test
    privat = next(o["wert"] for o in test["optionen"]["kalender"] if o["titel"] == "Persönlich")
    antwort = admin.post(
        "/api/integrationen",
        json={
            "manifest_id": "nextcloud-kalender",
            "name": "Kalender",
            "konfig": {**konfig, "kalender": privat, **mehr},
            "test_id": test["test_id"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _aufrufen(admin: TestClient, integration: dict, funktion: str, **argumente: Any) -> dict:
    """„Ausprobieren“ im Panel – ruft die Funktion direkt auf (ohne Freigabe)."""
    antwort = admin.post(
        f"/api/integrationen/{integration['id']}/aufrufen",
        json={"funktion": funktion, "argumente": argumente},
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _ergebnis(admin: TestClient, integration: dict, funktion: str, **argumente: Any) -> dict:
    antwort = _aufrufen(admin, integration, funktion, **argumente)
    assert antwort["ok"] is True, antwort
    return json.loads(antwort["ergebnis"])


# ====================================================================== einrichten


def test_einrichten_in_drei_schritten_zeigt_die_kalender_zur_auswahl(
    angemeldet: TestClient, nextcloud: KalenderServer
) -> None:
    karte = next(
        e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "nextcloud-kalender"
    )
    assert [(f["name"], f["typ"], f["nach_test"]) for f in karte["felder"]] == [
        ("url", "url", False),
        ("zugang", "zugang", False),
        ("kalender", "auswahl", True),  # erscheint erst nach dem Test
        ("alle_kalender", "schalter", True),
    ]
    assert "App-Passwort" in karte["hinweis"]

    konfig = {"url": nextcloud.url, "zugang": _zugang(angemeldet, nextcloud)}
    test = angemeldet.post(
        "/api/integrationen/testen", json={"manifest_id": "nextcloud-kalender", "konfig": konfig}
    ).json()
    assert test["ok"] is True, test
    assert test["meldung"] == "Verbunden als louis – 2 Kalender gefunden."
    assert test["details"] == ["Arbeit", "Persönlich"]  # die Aufgabenliste ist kein Kalender
    assert [o["titel"] for o in test["optionen"]["kalender"]] == ["Arbeit", "Persönlich"]
    assert {f["name"]: (f["recht"], f["schreibend"]) for f in test["funktionen"]} == {
        "termine_anzeigen": ("erlaubt", False),
        "termin_eintragen": ("nachfragen", True),
        "termin_aendern": ("nachfragen", True),
        "termin_loeschen": ("nachfragen", True),
    }

    # Ohne gewählten Kalender lässt sich nicht aktivieren.
    ohne = angemeldet.post(
        "/api/integrationen",
        json={"manifest_id": "nextcloud-kalender", "konfig": konfig, "test_id": test["test_id"]},
    )
    assert ohne.status_code == 422
    assert ohne.json()["meldung"] == "Bitte „Kalender für neue Termine“ ausfüllen."

    kalender = _einrichten(angemeldet, nextcloud)
    assert kalender["status"] == "ok"
    assert {f["gateway_name"] for f in kalender["funktionen"]} == {
        "kalender_termin_aendern",
        "kalender_termin_eintragen",
        "kalender_termin_loeschen",
        "kalender_termine_anzeigen",
    }
    assert kalender["konfig"]["kalender"] == "/louis/privat/"
    assert nextcloud.passwort not in json.dumps(kalender)  # das App-Passwort bleibt im Panel


def test_fehler_beim_einrichten_sind_verstaendlich(angemeldet: TestClient, nextcloud: KalenderServer) -> None:
    def testen(url: str, zugang: int) -> dict:
        return angemeldet.post(
            "/api/integrationen/testen",
            json={"manifest_id": "nextcloud-kalender", "konfig": {"url": url, "zugang": zugang}},
        ).json()

    falsch = testen(nextcloud.url, _zugang(angemeldet, nextcloud, passwort="falsches-passwort"))
    assert falsch["ok"] is False
    assert falsch["meldung"] == "Die Gegenstelle lehnt den Zugang ab (401 – nicht angemeldet)."
    assert "Zugang" in falsch["hinweis"]

    aus = testen(f"http://127.0.0.1:{freier_port()}", _zugang(angemeldet, nextcloud))
    assert (aus["ok"], aus["meldung"]) == (False, "Die Gegenstelle ist nicht erreichbar.")

    ohne_zugang = angemeldet.post(
        "/api/integrationen/testen",
        json={"manifest_id": "nextcloud-kalender", "konfig": {"url": nextcloud.url}},
    )
    assert ohne_zugang.status_code == 422
    assert ohne_zugang.json()["meldung"] == "Bitte „Benutzer und App-Passwort“ ausfüllen."


def test_kein_caldav_unter_der_adresse(
    angemeldet: TestClient, panel: LaufenderServer, nextcloud: KalenderServer
) -> None:
    """Zeigt die Adresse auf etwas anderes (hier: das Panel selbst), sagt die Meldung, was erwartet wird."""
    antwort = angemeldet.post(
        "/api/integrationen/testen",
        json={
            "manifest_id": "nextcloud-kalender",
            "konfig": {"url": panel.url, "zugang": _zugang(angemeldet, nextcloud)},
        },
    ).json()
    assert antwort["ok"] is False
    assert antwort["meldung"] == "Unter dieser Adresse wurde kein Kalender-Dienst (CalDAV) gefunden."
    assert "https://cloud.example.ch" in antwort["hinweis"]


# ====================================================================== Missa über das Gateway


async def test_missa_liest_termine_und_traegt_nach_freigabe_ein(
    angemeldet: TestClient, panel: LaufenderServer, nextcloud: KalenderServer
) -> None:
    """Fertig-wenn: Kalender einrichten, Missa kann über das Gateway Termine lesen und (nach Freigabe) eintragen."""
    _einrichten(angemeldet, nextcloud)
    nextcloud.ablegen(
        "privat",
        "zahnarzt",
        _ical(
            "UID:zahnarzt-1\nDTSTART:20260116T080000Z\nDTEND:20260116T090000Z\nSUMMARY:Zahnarzt\nLOCATION:Praxis Dr. Müller"
        ),
    )
    token = client_token(angemeldet)

    async with mcp_client(panel.url, token) as missa:
        # Lesen geht sofort.
        gelesen = await missa.call_tool("kalender_termine_anzeigen", {})
        assert gelesen.is_error is False, mcp_text(gelesen)
        daten = json.loads(mcp_text(gelesen))
        assert daten["heute"] == "Donnerstag, 15.01.2026"
        assert daten["zeitraum"] == "Do, 15.01.2026 bis Mi, 21.01.2026"  # ohne Angaben: 7 Tage ab heute
        assert daten["termine"] == [
            {
                "id": "zahnarzt-1",
                "titel": "Zahnarzt",
                "wann": "Fr, 16.01.2026, 09:00–10:00",  # 08:00 UTC ist 09:00 Uhr Ortszeit
                "beginn": "2026-01-16T09:00+01:00",
                "ende": "2026-01-16T10:00+01:00",
                "ganztaegig": False,
                "kalender": "Persönlich",
                "ort": "Praxis Dr. Müller",
            }
        ]

        # Eintragen wartet auf die Freigabe – und die sagt genau, was eingetragen würde.
        wunsch = {
            "titel": "Abendessen mit Oma",
            "beginn": "morgen 18:30",
            "ende": "morgen 20:00",
            "ort": "Zuhause",
        }
        aufruf = asyncio.create_task(missa.call_tool("kalender_termin_eintragen", wunsch))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["vorschau"] == (
            "Trägt in den Kalender „Persönlich“ ein: „Abendessen mit Oma“ – Fr, 16.01.2026, 18:30–20:00, Ort: Zuhause"
        )
        await asyncio.sleep(0.2)
        assert not aufruf.done()
        assert list(nextcloud.dateien("privat")) == ["zahnarzt.ics"]  # noch nichts eingetragen

        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        eingetragen = await asyncio.wait_for(aufruf, timeout=10)
        assert eingetragen.is_error is False, mcp_text(eingetragen)
        antwort = json.loads(mcp_text(eingetragen))
        assert antwort["meldung"] == (
            "Eingetragen: „Abendessen mit Oma“ – Fr, 16.01.2026, 18:30–20:00 (Kalender „Persönlich“)"
        )

        # Der Termin liegt wirklich auf dem Server – in UTC, wie es CalDAV vorsieht.
        dateien = nextcloud.dateien("privat")
        neu = dateien[f"{antwort['id']}.ics"]
        assert "SUMMARY:Abendessen mit Oma" in neu
        assert "DTSTART:20260116T173000Z" in neu
        assert "DTEND:20260116T190000Z" in neu
        assert "LOCATION:Zuhause" in neu

        # … und Missa sieht ihn beim nächsten Lesen.
        morgen = json.loads(
            mcp_text(await missa.call_tool("kalender_termine_anzeigen", {"von": "morgen", "bis": "morgen"}))
        )
        assert morgen["zeitraum"] == "Fr, 16.01.2026"
        assert [(t["titel"], t["wann"]) for t in morgen["termine"]] == [
            ("Zahnarzt", "Fr, 16.01.2026, 09:00–10:00"),
            ("Abendessen mit Oma", "Fr, 16.01.2026, 18:30–20:00"),
        ]

        # Abgelehnt: es wird nichts eingetragen.
        aufruf = asyncio.create_task(
            missa.call_tool("kalender_termin_eintragen", {"titel": "Nein", "beginn": "2026-01-20"})
        )
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["vorschau"].endswith("„Nein“ – Di, 20.01.2026 (ganztägig)")
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": False})
        assert (await asyncio.wait_for(aufruf, timeout=10)).is_error is True
        assert len(nextcloud.dateien("privat")) == 2

        # Unsinnige Angaben: sofort eine verständliche Antwort, niemand wird gefragt.
        unsinn = await asyncio.wait_for(
            missa.call_tool("kalender_termin_eintragen", {"titel": "X", "beginn": "irgendwann"}), timeout=10
        )
        assert unsinn.is_error is True
        assert "„irgendwann“ (beginn) ist kein gültiger Zeitpunkt." in mcp_text(unsinn)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []


async def test_aendern_und_loeschen_zeigen_in_der_freigabe_welcher_termin_gemeint_ist(
    angemeldet: TestClient, panel: LaufenderServer, nextcloud: KalenderServer
) -> None:
    _einrichten(angemeldet, nextcloud)
    nextcloud.ablegen(
        "arbeit",
        "besprechung",
        _ical("UID:besprechung-7\nDTSTART:20260119T130000Z\nDTEND:20260119T143000Z\nSUMMARY:Besprechung"),
    )
    token = client_token(angemeldet)

    async def mit_freigabe(missa: Any, name: str, argumente: dict) -> tuple[Any, str]:
        aufruf = asyncio.create_task(missa.call_tool(name, argumente))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        return await asyncio.wait_for(aufruf, timeout=10), offen[0]["vorschau"]

    async with mcp_client(panel.url, token) as missa:
        # Nur der Beginn ändert sich: der Termin behält seine Dauer von anderthalb Stunden.
        geaendert, vorschau = await mit_freigabe(
            missa,
            "kalender_termin_aendern",
            {"id": "besprechung-7", "beginn": "2026-01-19 16:00", "ort": "Sitzungszimmer"},
        )
        assert geaendert.is_error is False, mcp_text(geaendert)
        assert vorschau == (
            "Ändert den Termin „Besprechung“ (Mo, 19.01.2026, 14:00–15:30, Kalender „Arbeit“). "
            "Neu: Mo, 19.01.2026, 16:00–17:30; Ort „Sitzungszimmer“."
        )
        assert (
            json.loads(mcp_text(geaendert))["meldung"]
            == "Geändert: „Besprechung“ – Mo, 19.01.2026, 16:00–17:30"
        )
        auf_dem_server = nextcloud.dateien("arbeit")["besprechung.ics"]
        assert "DTSTART:20260119T150000Z" in auf_dem_server
        assert "DTEND:20260119T163000Z" in auf_dem_server
        assert "LOCATION:Sitzungszimmer" in auf_dem_server
        assert "SEQUENCE:1" in auf_dem_server

        geloescht, vorschau = await mit_freigabe(missa, "kalender_termin_loeschen", {"id": "besprechung-7"})
        assert geloescht.is_error is False, mcp_text(geloescht)
        assert (
            vorschau == "Löscht den Termin „Besprechung“ – Mo, 19.01.2026, 16:00–17:30 (Kalender „Arbeit“)."
        )
        assert nextcloud.dateien("arbeit") == {}

        # Gibt es den Termin nicht (mehr), wird niemand gefragt.
        for name, argumente in (
            ("kalender_termin_loeschen", {"id": "besprechung-7"}),
            ("kalender_termin_aendern", {"id": "gibt-es-nicht", "titel": "Neu"}),
        ):
            weg = await asyncio.wait_for(missa.call_tool(name, argumente), timeout=10)
            assert weg.is_error is True
            assert "gibt es nicht (mehr)" in mcp_text(weg)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []


# ====================================================================== lesen im Einzelnen


def test_ganztaegige_mehrtaegige_und_serientermine(angemeldet: TestClient, nextcloud: KalenderServer) -> None:
    kalender = _einrichten(angemeldet, nextcloud)
    nextcloud.ablegen(
        "privat",
        "ferien",
        _ical("UID:ferien\nDTSTART;VALUE=DATE:20260117\nDTEND;VALUE=DATE:20260120\nSUMMARY:Skiferien"),
    )
    nextcloud.ablegen(
        "privat",
        "geburtstag",
        _ical("UID:geb\nDTSTART;VALUE=DATE:20260116\nDTEND;VALUE=DATE:20260117\nSUMMARY:Geburtstag Oma"),
    )
    nextcloud.ablegen(
        "arbeit",
        "standup",
        _ical(
            "UID:standup\nDTSTART:20260112T080000Z\nDTEND:20260112T081500Z\nRRULE:FREQ=DAILY;COUNT=10\nEXDATE:20260117T080000Z\nSUMMARY:Standup"
        ),
    )
    nextcloud.ablegen(
        "privat",
        "nachtzug",
        _ical(
            "UID:zug\nDTSTART:20260116T210000Z\nDTEND:20260117T053000Z\nSUMMARY:Nachtzug\nDESCRIPTION:Wagen 12"
        ),
    )
    nextcloud.ablegen(
        "privat",
        "abgesagt",
        _ical(
            "UID:abgesagt\nDTSTART:20260116T100000Z\nDTEND:20260116T110000Z\nSUMMARY:Abgesagt\nSTATUS:CANCELLED"
        ),
    )

    daten = _ergebnis(angemeldet, kalender, "termine_anzeigen", von="2026-01-16", bis="2026-01-18")
    assert daten["zeitraum"] == "Fr, 16.01.2026 bis So, 18.01.2026"
    assert [(t["titel"], t["wann"], t["kalender"]) for t in daten["termine"]] == [
        ("Geburtstag Oma", "Fr, 16.01.2026 (ganztägig)", "Persönlich"),  # ganztägige zuerst
        ("Standup", "Fr, 16.01.2026, 09:00–09:15", "Arbeit"),
        ("Nachtzug", "Fr, 16.01.2026, 22:00 bis Sa, 17.01.2026, 06:30", "Persönlich"),
        ("Skiferien", "Sa, 17.01.2026 bis Mo, 19.01.2026 (ganztägig)", "Persönlich"),
        ("Standup", "So, 18.01.2026, 09:00–09:15", "Arbeit"),  # der 17. ist als Ausnahme gestrichen
    ]
    standup = next(t for t in daten["termine"] if t["titel"] == "Standup")
    assert standup["serie"] is True
    assert (
        daten["termine"][0]["ganztaegig"],
        daten["termine"][0]["beginn"],
        daten["termine"][0]["ende"],
    ) == (
        True,
        "2026-01-16",
        "2026-01-16",
    )
    assert next(t for t in daten["termine"] if t["titel"] == "Nachtzug")["beschreibung"] == "Wagen 12"

    # Suche, einzelner Tag, leerer Zeitraum
    assert [
        t["titel"]
        for t in _ergebnis(
            angemeldet, kalender, "termine_anzeigen", von="2026-01-16", bis="2026-01-31", suche="ski"
        )["termine"]
    ] == ["Skiferien"]
    assert [
        t["titel"]
        for t in _ergebnis(angemeldet, kalender, "termine_anzeigen", von="19.01.2026", bis="19.01.2026")[
            "termine"
        ]
    ] == [
        "Skiferien",
        "Standup",
    ]
    leer = _ergebnis(angemeldet, kalender, "termine_anzeigen", von="2026-03-01", bis="2026-03-02")
    assert (leer["anzahl"], leer["hinweis"]) == (0, "In diesem Zeitraum gibt es keine Termine.")

    # Sommerzeit: 08:00 UTC ist im Juli 10:00 Uhr Ortszeit.
    nextcloud.ablegen(
        "privat",
        "sommer",
        _ical("UID:sommer\nDTSTART:20260701T080000Z\nDTEND:20260701T090000Z\nSUMMARY:Baden"),
    )
    sommer = _ergebnis(angemeldet, kalender, "termine_anzeigen", von="2026-07-01", bis="2026-07-01")
    assert sommer["termine"][0]["wann"] == "Mi, 01.07.2026, 10:00–11:00"
    assert sommer["termine"][0]["beginn"] == "2026-07-01T10:00+02:00"

    # Serientermine: Ändern und Löschen betreffen die ganze Serie – das steht in der Vorschau.
    with angemeldet.app.state.datenbank.sitzung() as db:  # type: ignore[attr-defined]
        dienst = angemeldet.app.state.integrationen  # type: ignore[attr-defined]
        integration = dienst.holen(db, kalender["id"])
        vorschau = asyncio.run(dienst.vorschau(db, integration, "termin_loeschen", {"id": "standup"}))
    assert vorschau.endswith("Achtung: Das ist ein Serientermin – es betrifft alle Termine der Serie.")


def test_nur_der_gewaehlte_kalender_wenn_so_eingestellt(
    angemeldet: TestClient, nextcloud: KalenderServer
) -> None:
    kalender = _einrichten(angemeldet, nextcloud, alle_kalender=False)
    nextcloud.ablegen(
        "privat", "a", _ical("UID:a\nDTSTART:20260116T080000Z\nDTEND:20260116T090000Z\nSUMMARY:Privat")
    )
    nextcloud.ablegen(
        "arbeit", "b", _ical("UID:b\nDTSTART:20260116T100000Z\nDTEND:20260116T110000Z\nSUMMARY:Arbeit")
    )
    assert [t["titel"] for t in _ergebnis(angemeldet, kalender, "termine_anzeigen")["termine"]] == ["Privat"]


@pytest.mark.parametrize(
    ("argumente", "meldung"),
    [
        ({"von": "2026-01-20", "bis": "2026-01-19"}, "Das Ende des Zeitraums liegt vor dem Beginn."),
        ({"von": "2026-01-01", "bis": "2028-01-01"}, "Der Zeitraum ist zu lang."),
        ({"von": "32.01.2026"}, "„32.01.2026“ (von) ist kein gültiger Zeitpunkt."),
        ({"von": "2026-01-16 25:00"}, "„2026-01-16 25:00“ (von) enthält keine gültige Uhrzeit."),
    ],
)
def test_ungueltige_zeitraeume(
    angemeldet: TestClient, nextcloud: KalenderServer, argumente: dict, meldung: str
) -> None:
    kalender = _einrichten(angemeldet, nextcloud)
    antwort = _aufrufen(angemeldet, kalender, "termine_anzeigen", **argumente)
    assert (antwort["ok"], antwort["meldung"]) == (False, meldung)


def test_eintragen_ganztaegig_und_ungueltige_angaben(
    angemeldet: TestClient, nextcloud: KalenderServer
) -> None:
    kalender = _einrichten(angemeldet, nextcloud)
    ferien = _ergebnis(
        angemeldet,
        kalender,
        "termin_eintragen",
        titel=" Ferien  im Tessin ",
        beginn="2026-02-07",
        ende="2026-02-14",
    )
    assert ferien["meldung"] == (
        "Eingetragen: „Ferien im Tessin“ – Sa, 07.02.2026 bis Sa, 14.02.2026 (ganztägig) (Kalender „Persönlich“)"
    )
    datei = nextcloud.dateien("privat")[f"{ferien['id']}.ics"]
    assert "DTSTART;VALUE=DATE:20260207" in datei
    assert "DTEND;VALUE=DATE:20260215" in datei  # in CalDAV zählt der Endtag nicht mehr mit

    ohne_ende = _ergebnis(
        angemeldet, kalender, "termin_eintragen", titel="Telefonat", beginn="2026-02-03T09:15"
    )
    assert ohne_ende["meldung"].startswith(
        "Eingetragen: „Telefonat“ – Di, 03.02.2026, 09:15–10:15"
    )  # eine Stunde

    for argumente, meldung in (
        ({"titel": " ", "beginn": "2026-02-03"}, "Der Termin braucht einen Titel."),
        (
            {"titel": "X", "beginn": "2026-02-03 10:00", "ende": "2026-02-03 09:00"},
            "Das Ende liegt vor dem Beginn.",
        ),
        (
            {"titel": "X", "beginn": "2026-02-03 10:00", "ende": "2026-02-04"},
            "Beginn und Ende passen nicht zusammen.",
        ),
    ):
        antwort = _aufrufen(angemeldet, kalender, "termin_eintragen", **argumente)
        assert (antwort["ok"], antwort["meldung"]) == (False, meldung)
    nichts = _aufrufen(angemeldet, kalender, "termin_aendern", id=ferien["id"])
    assert nichts["meldung"] == "Es wurde nichts angegeben, das sich ändern soll."
    umbenannt = _ergebnis(angemeldet, kalender, "termin_aendern", id=ferien["id"], titel="Ferien in Locarno")
    assert (
        umbenannt["meldung"]
        == "Geändert: „Ferien in Locarno“ – Sa, 07.02.2026 bis Sa, 14.02.2026 (ganztägig)"
    )


def test_faellt_die_nextcloud_aus_zeigt_das_der_status(angemeldet: TestClient, tmp_path: Path) -> None:
    with KalenderServer(tmp_path / "caldav") as server:
        server.kalender_anlegen("privat", "Persönlich")
        kalender = _einrichten(angemeldet, server)
        assert _ergebnis(angemeldet, kalender, "termine_anzeigen")["anzahl"] == 0
    # Der Server ist jetzt aus.
    antwort = _aufrufen(angemeldet, kalender, "termine_anzeigen")
    assert (antwort["ok"], antwort["meldung"]) == (False, "Die Gegenstelle ist nicht erreichbar.")
    status = angemeldet.get(f"/api/integrationen/{kalender['id']}").json()
    assert (status["status"], status["status_meldung"]) == ("fehler", "Die Gegenstelle ist nicht erreichbar.")
