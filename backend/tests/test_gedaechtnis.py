"""Gedächtnis: Missa merkt sich Dinge über das Gateway; im Panel lässt sich alles ansehen, ändern und löschen."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr, client_token, integration_anlegen, mcp_client, mcp_text, warte_auf
from missa_control.gedaechtnis.dienst import begriffe, volltext_abfrage
from server import LaufenderServer

pytestmark = pytest.mark.anyio


def _anlegen(admin: TestClient, text: str, kategorie: str = "sonstiges") -> dict:
    antwort = admin.post("/api/gedaechtnis", json={"text": text, "kategorie": kategorie})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _texte(admin: TestClient, **filter: str) -> list[str]:
    antwort = admin.get("/api/gedaechtnis", params=filter)
    assert antwort.status_code == 200, antwort.text
    return [eintrag["text"] for eintrag in antwort.json()["eintraege"]]


# ====================================================================== im Panel


def test_anlegen_auflisten_und_filtern(angemeldet: TestClient, uhr: Uhr) -> None:
    leer = angemeldet.get("/api/gedaechtnis").json()
    assert (leer["eintraege"], leer["gesamt"], leer["treffer"]) == ([], 0, 0)
    assert [k["wert"] for k in leer["kategorien"]] == [
        "vorlieben",
        "gewohnheiten",
        "projektwissen",
        "personen",
        "sonstiges",
    ]

    kaffee = _anlegen(angemeldet, "  Trinkt morgens   am liebsten Kaffee mit Hafermilch ", "vorlieben")
    assert kaffee["text"] == "Trinkt morgens am liebsten Kaffee mit Hafermilch"  # aufgeräumt
    assert (kaffee["kategorie"], kaffee["kategorie_name"]) == ("vorlieben", "Vorlieben")
    assert (kaffee["quelle"], kaffee["quelle_name"]) == ("manuell", "manuell")
    assert kaffee["erstellt"] == kaffee["geaendert"] == uhr.jetzt.isoformat()
    uhr.vor(minutes=1)
    _anlegen(angemeldet, "Oma Müller hat am 3. Mai Geburtstag", "Personen")  # Grossschreibung ist egal
    uhr.vor(minutes=1)
    _anlegen(angemeldet, "Der Autoschlüssel liegt in der Schublade im Flur")

    alle = angemeldet.get("/api/gedaechtnis").json()
    assert alle["gesamt"] == alle["treffer"] == 3
    assert alle["eintraege"][0]["text"].startswith("Der Autoschlüssel")  # neueste zuerst
    assert {k["wert"]: k["anzahl"] for k in alle["kategorien"]} == {
        "vorlieben": 1,
        "gewohnheiten": 0,
        "projektwissen": 0,
        "personen": 1,
        "sonstiges": 1,
    }
    assert _texte(angemeldet, kategorie="personen") == ["Oma Müller hat am 3. Mai Geburtstag"]
    assert _texte(angemeldet, quelle="missa") == []
    assert len(_texte(angemeldet, quelle="manuell")) == 3
    assert len(_texte(angemeldet, limit="2")) == 2
    assert angemeldet.get("/api/gedaechtnis", params={"limit": "2"}).json()["treffer"] == 3


def test_volltextsuche_findet_wortteile_und_alle_begriffe_muessen_passen(angemeldet: TestClient) -> None:
    _anlegen(angemeldet, "Trinkt morgens am liebsten Kaffee mit Hafermilch", "vorlieben")
    _anlegen(angemeldet, "Der Autoschlüssel liegt in der Schublade im Flur")
    _anlegen(angemeldet, "Oma Müller hat am 3. Mai Geburtstag", "personen")
    _anlegen(angemeldet, "Der Server heisst ai01, der TV im Wohnzimmer ist ein LG", "projektwissen")

    assert _texte(angemeldet, suche="kaffee") == ["Trinkt morgens am liebsten Kaffee mit Hafermilch"]
    assert _texte(angemeldet, suche="SCHLÜSSEL") == ["Der Autoschlüssel liegt in der Schublade im Flur"]
    assert _texte(angemeldet, suche="geburtstag müller") == ["Oma Müller hat am 3. Mai Geburtstag"]
    assert _texte(angemeldet, suche="kaffee geburtstag") == []  # im Panel müssen alle Begriffe vorkommen
    assert _texte(angemeldet, suche="ai01") == ["Der Server heisst ai01, der TV im Wohnzimmer ist ein LG"]
    # Kurze Begriffe (unter 3 Zeichen) werden ebenfalls gefunden.
    assert _texte(angemeldet, suche="tv") == ["Der Server heisst ai01, der TV im Wohnzimmer ist ein LG"]
    assert _texte(angemeldet, suche="tv server") == [
        "Der Server heisst ai01, der TV im Wohnzimmer ist ein LG"
    ]
    assert _texte(angemeldet, suche="tv kaffee") == []
    assert _texte(angemeldet, suche="kaffee", kategorie="personen") == []
    antwort = angemeldet.get("/api/gedaechtnis", params={"suche": "der"}).json()
    assert (antwort["treffer"], antwort["gesamt"]) == (2, 4)


@pytest.mark.parametrize(
    "suche",
    [
        '"',
        '"kaffee" OR (',
        "kaffee*",
        "NEAR(a b)",
        "text:kaffee",
        "a AND b",
        "(((",
        "100%",
        "_",
        "'; DROP TABLE x",
    ],
)
def test_sonderzeichen_in_der_suche_sind_harmlos(angemeldet: TestClient, suche: str) -> None:
    _anlegen(angemeldet, "Kaffee mit 100% Hafermilch")
    antwort = angemeldet.get("/api/gedaechtnis", params={"suche": suche})
    assert antwort.status_code == 200, antwort.text
    assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 1  # die Tabelle gibt es noch


def test_suchbegriffe_und_volltext_abfrage() -> None:
    assert begriffe('  „Kaffee“, (Hafermilch)! kaffee  "x" ') == ["kaffee", "hafermilch", "x"]
    assert begriffe("") == []
    assert volltext_abfrage(["kaffee", 'ha"fer'], alle=True) == '"kaffee" AND "ha""fer"'
    assert volltext_abfrage(["kaffee", "tee"], alle=False) == '"kaffee" OR "tee"'


def test_bearbeiten_und_loeschen_halten_die_suche_aktuell(angemeldet: TestClient, uhr: Uhr) -> None:
    eintrag = _anlegen(angemeldet, "Der Autoschlüssel liegt in der Schublade")
    uhr.vor(hours=1)
    geaendert = angemeldet.put(
        f"/api/gedaechtnis/{eintrag['id']}",
        json={"text": "Der Autoschlüssel hängt am Brett", "kategorie": "gewohnheiten"},
    )
    assert geaendert.status_code == 200, geaendert.text
    assert geaendert.json()["kategorie"] == "gewohnheiten"
    assert geaendert.json()["erstellt"] == eintrag["erstellt"]
    assert geaendert.json()["geaendert"] == uhr.jetzt.isoformat()
    assert _texte(angemeldet, suche="schublade") == []
    assert _texte(angemeldet, suche="brett") == ["Der Autoschlüssel hängt am Brett"]

    # Nur die Kategorie ändern lässt den Text, wie er ist; ohne Änderung bleibt auch der Zeitstempel.
    uhr.vor(hours=1)
    gleich = angemeldet.put(f"/api/gedaechtnis/{eintrag['id']}", json={"kategorie": "gewohnheiten"}).json()
    assert gleich["geaendert"] == geaendert.json()["geaendert"]
    assert gleich["text"] == "Der Autoschlüssel hängt am Brett"

    assert angemeldet.delete(f"/api/gedaechtnis/{eintrag['id']}").status_code == 204
    assert _texte(angemeldet, suche="brett") == []
    assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 0
    weg = angemeldet.delete(f"/api/gedaechtnis/{eintrag['id']}")
    assert weg.status_code == 404
    assert "gibt es im Gedächtnis nicht" in weg.json()["meldung"]
    assert angemeldet.put(f"/api/gedaechtnis/{eintrag['id']}", json={"text": "x"}).status_code == 404


def test_ungueltige_eingaben_werden_verstaendlich_abgelehnt(angemeldet: TestClient) -> None:
    leer = angemeldet.post("/api/gedaechtnis", json={"text": "   "})
    assert leer.status_code == 422
    assert leer.json()["meldung"] == "Der Eintrag ist leer."

    lang = angemeldet.post("/api/gedaechtnis", json={"text": "x" * 2001})
    assert lang.status_code == 422
    assert "zu lang" in lang.json()["meldung"]
    assert "2000" in lang.json()["hinweis"]

    kategorie = angemeldet.post("/api/gedaechtnis", json={"text": "Test", "kategorie": "geheim"})
    assert kategorie.status_code == 422
    assert kategorie.json()["meldung"] == "Die Kategorie „geheim“ gibt es nicht."
    assert "vorlieben" in kategorie.json()["hinweis"]
    assert angemeldet.get("/api/gedaechtnis", params={"kategorie": "geheim"}).status_code == 422
    assert angemeldet.get("/api/gedaechtnis", params={"quelle": "irgendwer"}).status_code == 422
    assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 0


def test_derselbe_text_wird_nicht_doppelt_gespeichert(angemeldet: TestClient) -> None:
    erster = _anlegen(angemeldet, "Mag keine Oliven", "vorlieben")
    zweiter = _anlegen(angemeldet, "mag keine  oliven")
    assert erster["neu"] is True
    assert (zweiter["neu"], zweiter["id"]) == (False, erster["id"])
    assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 1


def test_export_als_json_datei(angemeldet: TestClient, uhr: Uhr) -> None:
    _anlegen(angemeldet, "Mag keine Oliven", "vorlieben")
    _anlegen(angemeldet, "Jeden Montag ist Sport", "gewohnheiten")
    antwort = angemeldet.get("/api/gedaechtnis/export")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/json")
    assert (
        antwort.headers["content-disposition"] == 'attachment; filename="missa-gedaechtnis-2026-01-15.json"'
    )
    daten = json.loads(antwort.content.decode("utf-8"))
    assert daten["anzahl"] == 2
    assert daten["exportiert"] == uhr.jetzt.isoformat()
    assert [(e["text"], e["kategorie"], e["quelle"]) for e in daten["eintraege"]] == [
        ("Mag keine Oliven", "vorlieben", "manuell"),
        ("Jeden Montag ist Sport", "gewohnheiten", "manuell"),
    ]
    assert "Oliven" in antwort.text  # Umlaute und Text stehen lesbar in der Datei


def test_ohne_anmeldung_ist_das_gedaechtnis_nicht_erreichbar(client: TestClient) -> None:
    assert client.get("/api/gedaechtnis").status_code == 401
    assert client.get("/api/gedaechtnis/export").status_code == 401
    assert client.post("/api/gedaechtnis", json={"text": "x"}).status_code == 401


# ====================================================================== Missa über das Gateway


def test_integration_ist_mit_einem_klick_aktiv_und_hat_die_richtigen_rechte(angemeldet: TestClient) -> None:
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "gedaechtnis")
    assert karte["felder"] == []  # nichts einzustellen
    angelegt = angemeldet.post("/api/integrationen", json={"manifest_id": "gedaechtnis", "konfig": {}})
    assert angelegt.status_code == 201, angelegt.text
    assert angelegt.json()["status_meldung"] == "Gedächtnis bereit: 0 Einträge."
    funktionen = {f["gateway_name"]: (f["recht"], f["schreibend"]) for f in angelegt.json()["funktionen"]}
    assert funktionen == {
        "gedaechtnis_merken": ("erlaubt", True),
        "gedaechtnis_suchen": ("erlaubt", False),
        "gedaechtnis_vergessen": ("nachfragen", True),  # Standard: erst nachfragen
    }
    merken = next(f for f in angelegt.json()["funktionen"] if f["name"] == "merken")
    assert merken["parameter"]["required"] == ["text"]
    assert merken["parameter"]["properties"]["kategorie"]["enum"] == [
        "vorlieben",
        "gewohnheiten",
        "projektwissen",
        "personen",
        "sonstiges",
    ]
    assert "vollständiger Satz" in merken["parameter"]["properties"]["text"]["description"]


async def test_ueber_das_gateway_gemerktes_erscheint_im_panel_und_geloeschtes_wird_nicht_mehr_gefunden(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    """Fertig-wenn: gemerkter Eintrag erscheint im Panel; im Panel gelöscht → `suchen` findet ihn nicht mehr."""
    integration_anlegen(angemeldet, "gedaechtnis")
    token = client_token(angemeldet)

    async with mcp_client(panel.url, token) as missa:
        gemerkt = await missa.call_tool(
            "gedaechtnis_merken",
            {"text": "Louis trinkt morgens am liebsten Kaffee mit Hafermilch", "kategorie": "vorlieben"},
        )
        assert gemerkt.is_error is False, mcp_text(gemerkt)
        antwort = json.loads(mcp_text(gemerkt))
        assert antwort == {"id": antwort["id"], "kategorie": "Vorlieben", "meldung": "Gemerkt."}
        await missa.call_tool("gedaechtnis_merken", {"text": "Oma Müller hat am 3. Mai Geburtstag"})
        nochmal = await missa.call_tool(
            "gedaechtnis_merken", {"text": "Louis trinkt morgens am liebsten Kaffee mit Hafermilch"}
        )
        assert json.loads(mcp_text(nochmal))["meldung"] == "Das steht schon im Gedächtnis."

        # Im Panel sichtbar – mit Quelle „Missa“.
        im_panel = angemeldet.get("/api/gedaechtnis").json()
        assert im_panel["gesamt"] == 2
        kaffee = next(e for e in im_panel["eintraege"] if "Kaffee" in e["text"])
        assert (kaffee["quelle"], kaffee["quelle_name"], kaffee["kategorie"]) == (
            "missa",
            "Missa",
            "vorlieben",
        )
        assert _texte(angemeldet, quelle="missa", suche="hafermilch") == [kaffee["text"]]

        # Missa sucht: ein passendes Stichwort genügt, der beste Treffer steht vorn.
        gefunden = json.loads(
            mcp_text(
                await missa.call_tool("gedaechtnis_suchen", {"text": "Was trinkt Louis? Kaffee oder Tee"})
            )
        )
        assert gefunden["anzahl"] == 1
        assert gefunden["eintraege"][0] == {
            "id": kaffee["id"],
            "text": "Louis trinkt morgens am liebsten Kaffee mit Hafermilch",
            "kategorie": "Vorlieben",
            "gemerkt_am": "2026-01-15",
        }
        # Ganze Sätze sind in Ordnung: Füllwörter wie „ist“ und „der“ finden nicht alles Mögliche.
        satz = json.loads(
            mcp_text(
                await missa.call_tool("gedaechtnis_suchen", {"text": "Wann ist der Geburtstag von der Oma?"})
            )
        )
        assert [e["text"] for e in satz["eintraege"]] == ["Oma Müller hat am 3. Mai Geburtstag"]
        fuellwoerter = json.loads(mcp_text(await missa.call_tool("gedaechtnis_suchen", {"text": "hat"})))
        assert fuellwoerter["anzahl"] == 1  # bleibt sonst nichts übrig, wird trotzdem gesucht
        personen = json.loads(
            mcp_text(await missa.call_tool("gedaechtnis_suchen", {"kategorie": "sonstiges"}))
        )
        assert [e["text"] for e in personen["eintraege"]] == ["Oma Müller hat am 3. Mai Geburtstag"]
        einer = json.loads(mcp_text(await missa.call_tool("gedaechtnis_suchen", {"anzahl": 1})))
        assert einer["anzahl"] == 1
        assert "Es gibt 2 passende Einträge" in einer["hinweis"]

        # Im Panel korrigiert → Missa findet den neuen Text; im Panel gelöscht → Missa findet nichts mehr.
        angemeldet.put(f"/api/gedaechtnis/{kaffee['id']}", json={"text": "Louis trinkt morgens Grüntee"})
        korrigiert = json.loads(mcp_text(await missa.call_tool("gedaechtnis_suchen", {"text": "grüntee"})))
        assert [e["id"] for e in korrigiert["eintraege"]] == [kaffee["id"]]
        assert angemeldet.delete(f"/api/gedaechtnis/{kaffee['id']}").status_code == 204
        for stichwort in ("grüntee", "Louis", "trinkt morgens"):
            weg = json.loads(mcp_text(await missa.call_tool("gedaechtnis_suchen", {"text": stichwort})))
            assert (weg["anzahl"], weg["eintraege"]) == (0, [])
            assert weg["hinweis"].startswith("Nichts gefunden.")

        # Ungültige Angaben kommen als verständlicher Fehler zurück.
        falsch = await missa.call_tool("gedaechtnis_merken", {"text": "x", "kategorie": "geheim"})
        assert falsch.is_error is True
        leer = await missa.call_tool("gedaechtnis_merken", {"text": "  "})
        assert leer.is_error is True
        assert "Der Eintrag ist leer." in mcp_text(leer)


async def test_vergessen_fragt_erst_nach_und_zeigt_was_geloescht_wuerde(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    integration_anlegen(angemeldet, "gedaechtnis")
    token = client_token(angemeldet)
    eintrag = _anlegen(angemeldet, "Mag keine Oliven", "vorlieben")

    async with mcp_client(panel.url, token) as missa:
        werkzeuge = {w.name: w for w in (await missa.list_tools()).tools}
        assert "erst ausgeführt, nachdem der Besitzer" in werkzeuge["gedaechtnis_vergessen"].description
        assert "erst ausgeführt" not in werkzeuge["gedaechtnis_merken"].description

        aufruf = asyncio.create_task(missa.call_tool("gedaechtnis_vergessen", {"id": eintrag["id"]}))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["funktion"] == "gedaechtnis_vergessen"
        assert offen[0]["argumente"] == {"id": eintrag["id"]}
        # Die Freigabe sagt, worum es geht – nicht nur „id: 1“.
        assert offen[0]["vorschau"] == "Löscht aus dem Gedächtnis (Vorlieben): „Mag keine Oliven“"
        await asyncio.sleep(0.2)
        assert not aufruf.done()
        assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 1  # noch nichts gelöscht

        # Ablehnen: der Eintrag bleibt.
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": False})
        abgelehnt = await asyncio.wait_for(aufruf, timeout=5)
        assert abgelehnt.is_error is True
        assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 1

        # Erlauben: der Eintrag ist weg.
        aufruf = asyncio.create_task(missa.call_tool("gedaechtnis_vergessen", {"id": eintrag["id"]}))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        erlaubt = await asyncio.wait_for(aufruf, timeout=5)
        assert erlaubt.is_error is False, mcp_text(erlaubt)
        assert json.loads(mcp_text(erlaubt)) == {
            "id": eintrag["id"],
            "meldung": "Vergessen: „Mag keine Oliven“",
        }
        assert angemeldet.get("/api/gedaechtnis").json()["gesamt"] == 0

        # Gibt es den Eintrag gar nicht, wird niemand gefragt – die Antwort kommt sofort.
        unbekannt = await asyncio.wait_for(missa.call_tool("gedaechtnis_vergessen", {"id": 999}), timeout=5)
        assert unbekannt.is_error is True
        assert "Den Eintrag 999 gibt es im Gedächtnis nicht" in mcp_text(unbekannt)
        falscher_typ = await asyncio.wait_for(
            missa.call_tool("gedaechtnis_vergessen", {"id": "alles"}), timeout=5
        )
        assert falscher_typ.is_error is True
        assert "Ungültige Parameter" in mcp_text(falscher_typ)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []
        verlauf = angemeldet.get("/api/freigaben").json()["verlauf"]
        assert [f["status"] for f in verlauf] == ["erlaubt", "abgelehnt"]
        assert verlauf[0]["vorschau"].startswith("Löscht aus dem Gedächtnis")


def test_gedaechtnis_uebersteht_einen_neustart(app: FastAPI, angemeldet: TestClient) -> None:
    from missa_control.main import create_app

    _anlegen(angemeldet, "Der Autoschlüssel liegt in der Schublade")
    neu = create_app(app.state.einstellungen)
    try:
        with neu.state.datenbank.sitzung() as db:
            eintraege, treffer = neu.state.gedaechtnis.suchen(db, "schlüssel")
            assert treffer == 1
            assert eintraege[0].text == "Der Autoschlüssel liegt in der Schublade"
    finally:
        neu.state.datenbank.schliessen()
