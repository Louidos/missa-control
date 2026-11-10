"""Manifest `integration.yaml`, Katalog und ZIP-Upload."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from missa_control.config import Einstellungen
from missa_control.integrationen.manifest import ManifestFehler, manifest_aus_text
from missa_control.main import create_app

REPO = Path(__file__).resolve().parents[2]
VORLAGE = REPO / "integrations" / "_vorlage"

GUELTIG = """
id: wetter
name: Wetter
beschreibung: Aktuelles Wetter abfragen
symbol: "🌦️"
art: python
version: 1.2
felder:
  - name: ort
    titel: Ort
    pflicht: true
  - name: einheit
    titel: Einheit
    typ: auswahl
    standard: c
    optionen: [c, {wert: f, titel: Fahrenheit}]
  - name: key
    titel: API-Key
    typ: zugang
    zugang_typen: [api_key]
standardrechte:
  wetter_aktuell: erlaubt
"""


def test_gueltiges_manifest() -> None:
    manifest = manifest_aus_text(GUELTIG)
    assert manifest.id == "wetter"
    assert manifest.version == "1.2"
    assert [feld.typ for feld in manifest.felder] == ["text", "auswahl", "zugang"]
    assert [(o.wert, o.titel) for o in manifest.felder[1].optionen] == [("c", "c"), ("f", "Fahrenheit")]
    assert manifest.standardrechte == {"wetter_aktuell": "erlaubt"}
    assert manifest.mehrfach is True


@pytest.mark.parametrize(
    ("aenderung", "erwartet"),
    [
        (("id: wetter", "id: Wetter App"), "„id“ hat ein ungültiges Format"),
        (("art: python", "art: zauberei"), "„art“ hat einen ungültigen Wert (erlaubt: 'mcp', 'openapi'"),
        (("name: Wetter\n", ""), "„name“ fehlt (Pflichtangabe)"),
        (("beschreibung:", "beschreibnug:"), "„beschreibnug“ ist kein bekannter Eintrag (Tippfehler?)"),
        (
            ("    pflicht: true", "    pflicht: vielleicht"),
            "„felder → 0 → pflicht“ muss true oder false sein",
        ),
        (("  - name: einheit", "  - name: ort"), "Feldnamen kommen mehrfach vor: ort"),
        (("    optionen: [c, {wert: f, titel: Fahrenheit}]\n", ""), "braucht „optionen“"),
        (
            ("  wetter_aktuell: erlaubt", "  wetter_aktuell: immer"),
            "ungültigen Wert (erlaubt: 'erlaubt', 'nachfragen'",
        ),
    ],
)
def test_ungueltiges_manifest_wird_verstaendlich_erklaert(aenderung: tuple[str, str], erwartet: str) -> None:
    assert aenderung[0] in GUELTIG
    with pytest.raises(ManifestFehler) as fehler:
        manifest_aus_text(GUELTIG.replace(*aenderung))
    assert erwartet in " | ".join(fehler.value.meldungen)


def test_kaputtes_yaml_nennt_die_zeile() -> None:
    with pytest.raises(ManifestFehler, match="kein gültiges YAML in Zeile 3"):
        manifest_aus_text("id: x\nname: y\n  falsch: [eingerückt\n")
    with pytest.raises(ManifestFehler, match="schlüssel: wert"):
        manifest_aus_text("- nur\n- eine\n- liste\n")


# ---------- Katalog ----------


def test_katalog_zeigt_eingebaute_integrationen_ohne_vorlage(angemeldet: TestClient) -> None:
    katalog = angemeldet.get("/api/katalog").json()
    nach_id = {eintrag["id"]: eintrag for eintrag in katalog["eintraege"]}
    assert {"mcp-server", "rest-api"} <= set(nach_id)
    assert "meine-integration" not in nach_id  # der Ordner _vorlage wird übersprungen
    assert nach_id["mcp-server"]["art_name"] == "MCP-Server"
    assert nach_id["mcp-server"]["eingebaut"] is True
    assert nach_id["mcp-server"]["kann_hinzufuegen"] is True
    assert [feld["name"] for feld in nach_id["mcp-server"]["felder"]] == ["url", "zugang", "verbindung"]
    assert katalog["probleme"] == []


def test_alle_eingebauten_manifeste_sind_gueltig(app: FastAPI) -> None:
    katalog = app.state.integrationen.katalog
    assert katalog.probleme == []
    assert len(katalog.eintraege) >= 2


def test_vorlage_kopieren_namen_aendern_neu_starten(
    einstellungen: Einstellungen, uhr, tmp_path: Path
) -> None:
    """Fertig-wenn: Vorlage kopieren, Namen ändern, Panel neu starten → Integration erscheint im Katalog."""
    from hilfen import einrichten

    ziel = einstellungen.eigene_integrationen_ordner / "gruss"
    shutil.copytree(VORLAGE, ziel)
    manifest = (ziel / "integration.yaml").read_text(encoding="utf-8")
    manifest = manifest.replace("id: meine-integration", "id: gruss").replace(
        "name: Meine Integration", "name: Grüsse"
    )
    (ziel / "integration.yaml").write_text(manifest, encoding="utf-8")

    app = create_app(einstellungen)  # „Panel neu starten“
    with TestClient(app) as client:
        einrichten(client, uhr)
        eintraege = {e["id"]: e for e in client.get("/api/katalog").json()["eintraege"]}
        assert eintraege["gruss"]["name"] == "Grüsse"
        assert eintraege["gruss"]["eingebaut"] is False

        test = client.post("/api/integrationen/testen", json={"manifest_id": "gruss", "konfig": {}}).json()
        assert test["ok"] is True, test
        assert test["meldung"] == "Alles bereit."
        assert test["funktionen"] == [
            {
                "name": "begruessen",
                "beschreibung": "Begrüsst eine Person mit dem eingestellten Grusswort.",
                "schreibend": False,
                "recht": "erlaubt",
            }
        ]
        angelegt = client.post(
            "/api/integrationen",
            json={
                "manifest_id": "gruss",
                "name": "Grüsse",
                "konfig": {"gruss": "Grüezi"},
                "test_id": test["test_id"],
            },
        )
        assert angelegt.status_code == 201, angelegt.text
        integration = angelegt.json()
        assert integration["kennung"] == "gruesse"
        assert integration["funktionen"][0]["gateway_name"] == "gruesse_begruessen"
        assert integration["funktionen"][0]["parameter"]["properties"]["name"] == {
            "default": "Welt",
            "description": "Wer begrüsst werden soll",
            "type": "string",
        }
        aufruf = client.post(
            f"/api/integrationen/{integration['id']}/aufrufen",
            json={"funktion": "begruessen", "argumente": {"name": "Missa"}},
        ).json()
        assert aufruf == {"ok": True, "ergebnis": "Grüezi, Missa!"}
    app.state.datenbank.schliessen()


def test_kaputte_eigene_integration_wird_gemeldet_und_stoert_die_anderen_nicht(
    einstellungen: Einstellungen, uhr
) -> None:
    from hilfen import einrichten

    kaputt = einstellungen.eigene_integrationen_ordner / "kaputt"
    kaputt.mkdir(parents=True)
    (kaputt / "integration.yaml").write_text("id: kaputt\nname: Kaputt\nart: python\n", encoding="utf-8")
    ohne_main = einstellungen.eigene_integrationen_ordner / "ohne-main"
    ohne_main.mkdir()
    (ohne_main / "integration.yaml").write_text(
        "id: ohne-main\nname: Ohne\nbeschreibung: x\nart: python\n", encoding="utf-8"
    )
    doppelt = einstellungen.eigene_integrationen_ordner / "doppelt"
    doppelt.mkdir()
    (doppelt / "integration.yaml").write_text(
        "id: mcp-server\nname: Doppelt\nbeschreibung: x\nart: mcp\n", encoding="utf-8"
    )

    app = create_app(einstellungen)
    with TestClient(app) as client:
        einrichten(client, uhr)
        katalog = client.get("/api/katalog").json()
    app.state.datenbank.schliessen()
    probleme = {problem["ordner"]: " ".join(problem["meldungen"]) for problem in katalog["probleme"]}
    assert "„beschreibung“ fehlt" in probleme["kaputt"]
    assert "main.py fehlt" in probleme["ohne-main"]
    assert "wird bereits von einer eingebauten Integration verwendet" in probleme["doppelt"]
    assert "mcp-server" in {eintrag["id"] for eintrag in katalog["eintraege"]}


# ---------- ZIP-Upload ----------


def _zip(dateien: dict[str, str]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as archiv:
        for name, inhalt in dateien.items():
            archiv.writestr(name, inhalt)
    return puffer.getvalue()


def _vorlage_dateien(praefix: str = "", id_: str = "upload") -> dict[str, str]:
    manifest = (
        (VORLAGE / "integration.yaml")
        .read_text(encoding="utf-8")
        .replace("id: meine-integration", f"id: {id_}")
    )
    return {f"{praefix}integration.yaml": manifest, f"{praefix}main.py": (VORLAGE / "main.py").read_text()}


def _hochladen(client: TestClient, inhalt: bytes, **form: str):
    return client.post(
        "/api/katalog/hochladen", files={"datei": ("x.zip", inhalt, "application/zip")}, data=form
    )


@pytest.mark.parametrize("praefix", ["", "mein-ordner/"])
def test_zip_hochladen(angemeldet: TestClient, einstellungen: Einstellungen, praefix: str) -> None:
    antwort = _hochladen(angemeldet, _zip(_vorlage_dateien(praefix)))
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"id": "upload", "name": "Meine Integration", "ersetzt": False}
    assert (einstellungen.eigene_integrationen_ordner / "upload" / "main.py").is_file()
    assert "upload" in {e["id"] for e in angemeldet.get("/api/katalog").json()["eintraege"]}

    # Sofort benutzbar – ohne Neustart:
    test = angemeldet.post("/api/integrationen/testen", json={"manifest_id": "upload", "konfig": {}}).json()
    assert test["ok"] is True
    assert [f["name"] for f in test["funktionen"]] == ["begruessen"]


def test_zip_ersetzen_nur_auf_wunsch(angemeldet: TestClient) -> None:
    assert _hochladen(angemeldet, _zip(_vorlage_dateien())).status_code == 200
    nochmal = _hochladen(angemeldet, _zip(_vorlage_dateien()))
    assert nochmal.status_code == 409
    assert "ersetzen" in nochmal.json()["hinweis"]
    ersetzt = _hochladen(angemeldet, _zip(_vorlage_dateien()), ersetzen="true")
    assert ersetzt.json()["ersetzt"] is True


@pytest.mark.parametrize(
    ("inhalt", "status", "erwartet"),
    [
        (b"das ist kein zip", 422, "kein gültiges ZIP-Archiv"),
        (_zip({"main.py": "x = 1"}), 422, "fehlt die Datei integration.yaml"),
        (
            _zip({"a/integration.yaml": "x", "b/integration.yaml": "x"}),
            422,
            "fehlt die Datei integration.yaml",
        ),
        (_zip({"integration.yaml": "id: x\nname: y\nart: python\n"}), 422, "„beschreibung“ fehlt"),
        (
            _zip({"integration.yaml": "id: Gross\nname: y\nbeschreibung: z\nart: mcp\n"}),
            422,
            "ungültiges Format",
        ),
        (
            _zip({"integration.yaml": "id: x\nname: y\nbeschreibung: z\nart: python\n"}),
            422,
            "fehlt die Datei main.py",
        ),
        (
            _zip(
                {
                    "integration.yaml": "id: x\nname: y\nbeschreibung: z\nart: python\n",
                    "main.py": "def kaputt(:\n",
                }
            ),
            422,
            "Syntaxfehler in Zeile 1",
        ),
        (
            _zip({"integration.yaml": "id: x\nname: y\nbeschreibung: z\nart: mcp\n", "../../boese.txt": "x"}),
            422,
            "unzulässigen Pfad",
        ),
        (
            _zip({"integration.yaml": "id: mcp-server\nname: y\nbeschreibung: z\nart: mcp\n"}),
            409,
            "eingebauten Integration",
        ),
    ],
)
def test_ungueltiges_zip_wird_mit_klarer_meldung_abgelehnt(
    angemeldet: TestClient, einstellungen: Einstellungen, inhalt: bytes, status: int, erwartet: str
) -> None:
    antwort = _hochladen(angemeldet, inhalt)
    assert antwort.status_code == status, antwort.text
    assert erwartet in antwort.json()["meldung"] + " " + antwort.json().get("hinweis", "")
    # Nichts davon landet auf der Platte:
    ordner = einstellungen.eigene_integrationen_ordner
    assert not ordner.exists() or list(ordner.iterdir()) == []
    assert not (einstellungen.daten_ordner.parent / "boese.txt").exists()


def test_eigene_integration_aus_katalog_entfernen(angemeldet: TestClient) -> None:
    _hochladen(angemeldet, _zip(_vorlage_dateien()))
    assert angemeldet.delete("/api/katalog/mcp-server").status_code == 409  # eingebaut bleibt
    assert angemeldet.delete("/api/katalog/upload").json() == {"ok": True}
    assert "upload" not in {e["id"] for e in angemeldet.get("/api/katalog").json()["eintraege"]}
