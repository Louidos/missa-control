"""Die ganze Einrichtung als eine Datei sichern und wieder einspielen.

Enthalten: Integrationen (Einstellungen, Funktionen, Rechte, Zugriffsstufe), Regeln, das aktuelle
Charakterprofil, Modelle und Rollen, Telefonie-Einstellungen und die Anordnung der Übersicht.
Zugänge nur, wenn beim Export ein eigenes Passwort gewählt wird – dann verschlüsselt (Schlüssel aus
dem Passwort abgeleitet). Ohne Passwort steht kein Geheimnis in der Datei; Verweise auf Zugänge
stehen nur mit ihrem Namen drin.

Nicht enthalten: Login und 2FA, Client-Tokens, Protokoll, Messwerte, Gedächtnis (eigener Export),
Geräte (sie werden neu gekoppelt) und der interne Zustand der Integrationen (z. B. die geheime Adresse
eines Webhooks – sie entsteht beim ersten Test neu).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from missa_control import __version__, zeit
from missa_control.fehler import PanelFehler
from missa_control.integrationen.dienst import IntegrationsDienst
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.integrationen.typen import RECHTE, STATUS_UNGETESTET, ZUGRIFFE
from missa_control.modellverwaltung.modelle import Modell, Rolle
from missa_control.profil.dienst import Profil
from missa_control.profil.modelle import ProfilVersion
from missa_control.regeln.modelle import Regel
from missa_control.status.modelle import KnotenPosition
from missa_control.telefonie.modelle import TelefonieEinstellung
from missa_control.zugaenge.dienst import ZugangsDienst
from missa_control.zugaenge.modelle import Zugang

FORMAT = "missa-control-sicherung"
VERSION = 1
ITERATIONEN = 390_000
BEREICHE = ("zugaenge", "integrationen", "regeln", "profil", "modelle", "telefonie", "uebersicht")
BEREICH_NAMEN = {
    "zugaenge": "Zugänge",
    "integrationen": "Integrationen",
    "regeln": "Regeln",
    "profil": "Charakterprofil",
    "modelle": "Modelle und Rollen",
    "telefonie": "Telefonie",
    "uebersicht": "Anordnung der Übersicht",
}
# Diese Arten werden nicht gesichert: Geräte haben Zugangsdaten am MQTT-Broker und werden neu gekoppelt.
NICHT_GESICHERT = ("geraet",)


def _schluessel(passwort: str, salz: bytes, iterationen: int) -> Fernet:
    ableitung = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salz, iterations=iterationen)
    return Fernet(base64.urlsafe_b64encode(ableitung.derive(passwort.encode())))


class SicherungsDienst:
    def __init__(self, *, integrationen: IntegrationsDienst, zugaenge: ZugangsDienst) -> None:
        self.integrationen = integrationen
        self.zugaenge = zugaenge

    # ------------------------------------------------------------------ Export

    def exportieren(self, db: Session, passwort: str | None = None) -> dict[str, Any]:
        """Die Einrichtung als Datei (JSON). Mit `passwort` kommen die Zugänge verschlüsselt mit."""
        zugang_namen = {zugang.id: zugang.name for zugang in db.scalars(select(Zugang))}
        integration_kennungen = {i.id: i.kennung for i in db.scalars(select(Integration))}
        modell_namen = {modell.id: modell.name for modell in db.scalars(select(Modell))}

        datei: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "panel_version": __version__,
            "erstellt": zeit.jetzt().isoformat(),
            "zugaenge": self._zugaenge_exportieren(db, passwort),
            "integrationen": self._integrationen_exportieren(db, zugang_namen),
            "regeln": [
                {
                    "name": regel.name,
                    "aktiv": regel.aktiv,
                    "ausloeser": _ids_zu_kennungen(regel.ausloeser, integration_kennungen),
                    "bedingung": regel.bedingung or {},
                    "aktion": regel.aktion,
                    "ruhezeit_minuten": regel.ruhezeit_minuten,
                    "quelle": regel.quelle,
                }
                for regel in db.scalars(select(Regel).order_by(Regel.id))
            ],
            "profil": None,
            "modelle": {
                "modelle": [
                    {
                        "name": modell.name,
                        "url": modell.url,
                        "zugang": zugang_namen.get(modell.zugang_id) if modell.zugang_id else None,
                        "modellname": modell.modellname,
                        "kontextlaenge": modell.kontextlaenge,
                    }
                    for modell in db.scalars(select(Modell).order_by(Modell.id))
                ],
                "rollen": [
                    {
                        "kennung": rolle.kennung,
                        "haupt": modell_namen.get(rolle.haupt_modell_id) if rolle.haupt_modell_id else None,
                        "ersatz": modell_namen.get(rolle.ersatz_modell_id)
                        if rolle.ersatz_modell_id
                        else None,
                    }
                    for rolle in db.scalars(select(Rolle).order_by(Rolle.id))
                ],
            },
            "telefonie": None,
            "uebersicht": [],
        }
        profil = db.scalar(select(ProfilVersion).order_by(ProfilVersion.id.desc()))
        if profil is not None:
            datei["profil"] = profil.inhalt
        telefonie = db.scalar(select(TelefonieEinstellung))
        if telefonie is not None:
            datei["telefonie"] = {
                "adapter": _knoten_zu_kennung(telefonie.adapter, integration_kennungen),
                "landesvorwahl": telefonie.landesvorwahl,
                "eigene_nummern": telefonie.eigene_nummern or [],
                "erlaubte_anrufer": telefonie.erlaubte_anrufer or [],
                "ruhezeiten": telefonie.ruhezeiten or [],
                "nur_bekannte": telefonie.nur_bekannte,
            }
        for position in db.scalars(select(KnotenPosition)):
            knoten = _knoten_zu_kennung(position.knoten, integration_kennungen)
            if knoten is not None:
                datei["uebersicht"].append({"knoten": knoten, "x": position.x, "y": position.y})
        return datei

    def _zugaenge_exportieren(self, db: Session, passwort: str | None) -> dict[str, Any]:
        zugaenge = list(db.scalars(select(Zugang).order_by(Zugang.id)))
        liste = [{"name": z.name, "typ": z.typ, "benutzer": z.benutzer, "notiz": z.notiz} for z in zugaenge]
        if not passwort:
            # Nur Name und Art – damit Verweise beim Einspielen wiedergefunden werden. Kein Wert.
            return {"verschluesselt": False, "liste": liste}
        if len(passwort) < 10:
            raise PanelFehler(
                422, "Das Passwort für die Sicherung ist zu kurz.", "Mindestens 10 Zeichen verwenden."
            )
        mit_werten = [
            {**eintrag, "wert": self.zugaenge.klartext(db, zugang.id).wert}
            for eintrag, zugang in zip(liste, zugaenge, strict=True)
        ]
        salz = os.urandom(16)
        inhalt = _schluessel(passwort, salz, ITERATIONEN).encrypt(json.dumps(mit_werten).encode())
        return {
            "verschluesselt": True,
            "verfahren": "PBKDF2-SHA256 + Fernet",
            "iterationen": ITERATIONEN,
            "salz": base64.b64encode(salz).decode(),
            "liste": [{"name": eintrag["name"], "typ": eintrag["typ"]} for eintrag in liste],
            "inhalt": inhalt.decode(),
        }

    def _integrationen_exportieren(self, db: Session, zugang_namen: dict[int, str]) -> list[dict[str, Any]]:
        ergebnis = []
        abfrage = select(Integration).options(selectinload(Integration.funktionen)).order_by(Integration.id)
        for integration in db.scalars(abfrage):
            eintrag = self.integrationen.katalog.eintraege.get(integration.manifest_id)
            if eintrag is not None and eintrag.manifest.art in NICHT_GESICHERT:
                continue
            zugang_felder = (
                {feld.name for feld in eintrag.manifest.felder if feld.typ == "zugang"} if eintrag else set()
            )
            konfig: dict[str, Any] = {}
            for name, wert in (integration.konfig or {}).items():
                if name in zugang_felder and isinstance(wert, int):
                    konfig[name] = {"zugang": zugang_namen.get(wert)}
                else:
                    konfig[name] = wert
            ergebnis.append(
                {
                    "manifest_id": integration.manifest_id,
                    "name": integration.name,
                    "kennung": integration.kennung,
                    "aktiv": integration.aktiv,
                    "zugriff": integration.zugriff,
                    "konfig": konfig,
                    "funktionen": [
                        {
                            "name": funktion.name,
                            "beschreibung": funktion.beschreibung,
                            "parameter": funktion.parameter,
                            "schreibend": funktion.schreibend,
                            "recht": funktion.recht,
                            "vorhanden": funktion.vorhanden,
                            "extra": funktion.extra,
                        }
                        for funktion in integration.funktionen
                    ],
                }
            )
        return ergebnis

    # ------------------------------------------------------------------ Einlesen

    @staticmethod
    def lesen(text: str | bytes) -> dict[str, Any]:
        """Liest und prüft eine Sicherungsdatei (Format-Kennzeichen und Version)."""
        try:
            datei = json.loads(text)
        except ValueError as fehler:
            raise PanelFehler(
                422, "Die Datei ist keine Sicherung von Missa Control (kein gültiges JSON)."
            ) from fehler
        if not isinstance(datei, dict) or datei.get("format") != FORMAT:
            raise PanelFehler(
                422,
                "Die Datei ist keine Sicherung von Missa Control.",
                "Bitte eine Datei wählen, die unter „Sicherung → Herunterladen“ entstanden ist.",
            )
        version = datei.get("version")
        if not isinstance(version, int) or version < 1:
            raise PanelFehler(422, "Die Version der Sicherung ist unbekannt.")
        if version > VERSION:
            raise PanelFehler(
                422,
                f"Die Sicherung stammt aus einer neueren Version des Panels (Format {version}, "
                f"dieses Panel kennt Format {VERSION}).",
                "Zuerst das Panel aktualisieren (./scripts/update.sh), dann erneut einspielen.",
            )
        return datei

    @staticmethod
    def _zugaenge_entschluesseln(datei: dict[str, Any], passwort: str | None) -> list[dict[str, Any]] | None:
        """Die Zugänge mit Werten – oder `None`, wenn die Datei keine enthält."""
        block = datei.get("zugaenge") or {}
        if not block.get("verschluesselt"):
            return None
        if not passwort:
            raise PanelFehler(
                422,
                "Die Sicherung enthält verschlüsselte Zugänge – bitte das Passwort der Sicherung eingeben.",
                "Das Passwort wurde beim Herunterladen gewählt.",
            )
        try:
            fernet = _schluessel(
                passwort, base64.b64decode(block["salz"]), int(block.get("iterationen", ITERATIONEN))
            )
            return json.loads(fernet.decrypt(str(block["inhalt"]).encode()))
        except (InvalidToken, KeyError, ValueError) as fehler:
            raise PanelFehler(
                422,
                "Das Passwort der Sicherung stimmt nicht.",
                "Es ist das Passwort, das beim Herunterladen gewählt wurde – nicht das Passwort des Panels.",
            ) from fehler

    # ------------------------------------------------------------------ Vorschau

    def vorschau(self, db: Session, datei: dict[str, Any], passwort: str | None = None) -> dict[str, Any]:
        """Was würde sich ändern? Pro Bereich: neu, würde überschrieben, unverändert, nur hier vorhanden."""
        zugaenge_mit_werten = self._zugaenge_entschluesseln(datei, passwort)
        bereiche: list[dict[str, Any]] = []

        def bereich(kennung: str, eintraege: list[tuple[str, str]], nur_hier: list[str]) -> None:
            bereiche.append(
                {
                    "bereich": kennung,
                    "titel": BEREICH_NAMEN[kennung],
                    "eintraege": [{"name": name, "status": status} for name, status in eintraege],
                    "nur_hier": nur_hier,
                }
            )

        # Zugänge
        vorhandene = {z.name: z for z in db.scalars(select(Zugang))}
        liste = (datei.get("zugaenge") or {}).get("liste") or []
        eintraege = []
        for eintrag in liste:
            name = str(eintrag.get("name"))
            if name not in vorhandene:
                status = "neu" if zugaenge_mit_werten is not None else "fehlt"
            elif zugaenge_mit_werten is None:
                status = "unveraendert"
            else:
                wert = next((z.get("wert") for z in zugaenge_mit_werten if z.get("name") == name), None)
                alt = self.zugaenge.klartext(db, vorhandene[name].id).wert
                status = "unveraendert" if wert == alt else "ueberschrieben"
            eintraege.append((name, status))
        bereich("zugaenge", eintraege, sorted(set(vorhandene) - {str(e.get("name")) for e in liste}))

        # Integrationen
        vorhanden_i = {
            i.kennung: i
            for i in db.scalars(select(Integration).options(selectinload(Integration.funktionen)))
        }
        eintraege = []
        for eintrag in datei.get("integrationen") or []:
            alt = vorhanden_i.get(eintrag.get("kennung"))
            if alt is None:
                status = "neu"
            else:
                gleich = (
                    alt.name == eintrag.get("name")
                    and alt.aktiv == eintrag.get("aktiv")
                    and alt.zugriff == eintrag.get("zugriff")
                    and {f.name: f.recht for f in alt.funktionen}
                    == {f["name"]: f["recht"] for f in eintrag.get("funktionen") or []}
                    and _konfig_ohne_zugaenge(alt.konfig) == _konfig_ohne_zugaenge(eintrag.get("konfig"))
                )
                status = "unveraendert" if gleich else "ueberschrieben"
            eintraege.append((f"{eintrag.get('name')} ({eintrag.get('kennung')})", status))
        neue_kennungen = {e.get("kennung") for e in datei.get("integrationen") or []}
        bereich(
            "integrationen",
            eintraege,
            sorted(f"{i.name} ({k})" for k, i in vorhanden_i.items() if k not in neue_kennungen),
        )

        # Regeln
        vorhanden_r = {r.name: r for r in db.scalars(select(Regel))}
        eintraege = []
        for eintrag in datei.get("regeln") or []:
            alt = vorhanden_r.get(eintrag.get("name"))
            if alt is None:
                status = "neu"
            else:
                gleich = (
                    alt.aktiv == eintrag.get("aktiv")
                    and alt.aktion == eintrag.get("aktion")
                    and (alt.bedingung or {}) == (eintrag.get("bedingung") or {})
                    and alt.ruhezeit_minuten == eintrag.get("ruhezeit_minuten")
                    and alt.ausloeser.get("art") == (eintrag.get("ausloeser") or {}).get("art")
                )
                status = "unveraendert" if gleich else "ueberschrieben"
            eintraege.append((str(eintrag.get("name")), status))
        namen_r = {e.get("name") for e in datei.get("regeln") or []}
        bereich("regeln", eintraege, sorted(n for n in vorhanden_r if n not in namen_r))

        # Profil
        aktuell = db.scalar(select(ProfilVersion).order_by(ProfilVersion.id.desc()))
        if datei.get("profil") is not None:
            if aktuell is None:
                status = "neu"
            else:
                status = "unveraendert" if aktuell.inhalt == datei["profil"] else "ueberschrieben"
            bereich("profil", [("Charakterprofil", status)], [])
        else:
            bereich("profil", [], [])

        # Modelle und Rollen
        vorhanden_m = {m.name: m for m in db.scalars(select(Modell))}
        modelle = (datei.get("modelle") or {}).get("modelle") or []
        eintraege = []
        for eintrag in modelle:
            alt = vorhanden_m.get(eintrag.get("name"))
            if alt is None:
                status = "neu"
            else:
                gleich = (alt.url, alt.modellname, alt.kontextlaenge) == (
                    eintrag.get("url"),
                    eintrag.get("modellname"),
                    eintrag.get("kontextlaenge"),
                )
                status = "unveraendert" if gleich else "ueberschrieben"
            eintraege.append((str(eintrag.get("name")), status))
        namen_m = {e.get("name") for e in modelle}
        bereich("modelle", eintraege, sorted(n for n in vorhanden_m if n not in namen_m))

        # Telefonie
        if datei.get("telefonie") is not None:
            alt_t = db.scalar(select(TelefonieEinstellung))
            if alt_t is None:
                status = "neu"
            else:
                neu_t = datei["telefonie"]
                gleich = (
                    alt_t.landesvorwahl == neu_t.get("landesvorwahl")
                    and (alt_t.eigene_nummern or []) == neu_t.get("eigene_nummern")
                    and (alt_t.erlaubte_anrufer or []) == neu_t.get("erlaubte_anrufer")
                    and (alt_t.ruhezeiten or []) == neu_t.get("ruhezeiten")
                    and alt_t.nur_bekannte == neu_t.get("nur_bekannte")
                )
                status = "unveraendert" if gleich else "ueberschrieben"
            bereich("telefonie", [("Telefonie-Einstellungen", status)], [])
        else:
            bereich("telefonie", [], [])

        # Übersicht
        anzahl = len(datei.get("uebersicht") or [])
        bereich(
            "uebersicht",
            [(f"{anzahl} Knoten-Position(en)", "neu")] if anzahl else [],
            [],
        )
        return {
            "panel_version": datei.get("panel_version"),
            "erstellt": datei.get("erstellt"),
            "mit_zugaengen": zugaenge_mit_werten is not None,
            "bereiche": bereiche,
        }

    # ------------------------------------------------------------------ Einspielen

    def einspielen(
        self,
        db: Session,
        datei: dict[str, Any],
        *,
        modi: dict[str, str],
        passwort: str | None = None,
    ) -> dict[str, Any]:
        """Spielt die Sicherung ein. `modi`: pro Bereich „ergaenzen“ (Standard) oder „ersetzen“.

        - ergänzen: neue Einträge dazu, gleichnamige überschreiben, alle übrigen bleiben
        - ersetzen: der Bereich wird vorher geleert
        """
        for bereich, modus in modi.items():
            if bereich not in BEREICHE or modus not in ("ergaenzen", "ersetzen", "auslassen"):
                raise PanelFehler(422, f"Unbekannter Bereich oder Modus: {bereich} = {modus}")
        zugaenge_mit_werten = self._zugaenge_entschluesseln(datei, passwort)

        def modus(bereich: str) -> str:
            return modi.get(bereich, "ergaenzen")

        zusammenfassung: dict[str, int] = {}
        jetzt = zeit.jetzt()

        # --- Zugänge
        if modus("zugaenge") != "auslassen":
            if modus("zugaenge") == "ersetzen" and zugaenge_mit_werten is not None:
                benutzte = set(self.integrationen.zugang_verwendung(db)) | {
                    m.zugang_id for m in db.scalars(select(Modell)) if m.zugang_id
                }
                for zugang in db.scalars(select(Zugang)):
                    if zugang.id not in benutzte or modus("integrationen") == "ersetzen":
                        db.delete(zugang)
                db.flush()
            anzahl = 0
            for eintrag in zugaenge_mit_werten or []:
                alt = db.scalar(select(Zugang).where(Zugang.name == eintrag["name"]))
                if alt is None:
                    self.zugaenge.anlegen(
                        db,
                        name=eintrag["name"],
                        typ=eintrag["typ"],
                        wert=eintrag["wert"],
                        benutzer=eintrag.get("benutzer"),
                        notiz=eintrag.get("notiz") or "",
                    )
                else:
                    self.zugaenge.aendern(db, alt.id, wert=eintrag["wert"], benutzer=eintrag.get("benutzer"))
                anzahl += 1
            zusammenfassung["zugaenge"] = anzahl
        zugang_ids = {z.name: z.id for z in db.scalars(select(Zugang))}

        # --- Integrationen
        fehlende_zugaenge: list[str] = []
        if modus("integrationen") != "auslassen":
            if modus("integrationen") == "ersetzen":
                for integration in list(db.scalars(select(Integration))):
                    eintrag = self.integrationen.katalog.eintraege.get(integration.manifest_id)
                    if eintrag is not None and eintrag.manifest.art in NICHT_GESICHERT:
                        continue  # Geräte bleiben
                    db.delete(integration)
                db.flush()
            anzahl = 0
            for eintrag in datei.get("integrationen") or []:
                anzahl += 1
                fehlt = self._integration_einspielen(db, eintrag, zugang_ids, jetzt)
                if fehlt:
                    fehlende_zugaenge.append(eintrag.get("name") or eintrag.get("kennung"))
            zusammenfassung["integrationen"] = anzahl
        db.flush()
        kennung_ids = {i.kennung: i.id for i in db.scalars(select(Integration))}

        # --- Regeln
        if modus("regeln") != "auslassen":
            if modus("regeln") == "ersetzen":
                db.execute(delete(Regel))
            anzahl = 0
            for eintrag in datei.get("regeln") or []:
                ausloeser = _kennungen_zu_ids(eintrag.get("ausloeser") or {}, kennung_ids)
                alt = db.scalar(select(Regel).where(Regel.name == eintrag.get("name")))
                if alt is None:
                    alt = Regel(
                        name=str(eintrag.get("name")),
                        erstellt=jetzt,
                        quelle=eintrag.get("quelle") or "manuell",
                    )
                    db.add(alt)
                alt.aktiv = bool(eintrag.get("aktiv", True))
                alt.ausloeser = ausloeser
                alt.bedingung = eintrag.get("bedingung") or {}
                alt.aktion = eintrag.get("aktion") or {}
                alt.ruhezeit_minuten = int(eintrag.get("ruhezeit_minuten") or 0)
                alt.geaendert = jetzt
                anzahl += 1
            zusammenfassung["regeln"] = anzahl

        # --- Profil (wird eine neue Version – der Verlauf bleibt)
        if modus("profil") != "auslassen" and datei.get("profil") is not None:
            try:
                inhalt = Profil.model_validate(datei["profil"]).bereinigt().model_dump()
            except ValidationError as fehler:
                raise PanelFehler(422, "Das Charakterprofil in der Sicherung ist ungültig.") from fehler
            aktuell = db.scalar(select(ProfilVersion).order_by(ProfilVersion.id.desc()))
            if aktuell is None or aktuell.inhalt != inhalt:
                db.add(
                    ProfilVersion(erstellt=jetzt, kommentar="Aus einer Sicherung eingespielt", inhalt=inhalt)
                )
            zusammenfassung["profil"] = 1

        # --- Modelle und Rollen
        if modus("modelle") != "auslassen":
            block = datei.get("modelle") or {}
            if modus("modelle") == "ersetzen":
                for rolle in db.scalars(select(Rolle)):
                    rolle.haupt_modell_id = None
                    rolle.ersatz_modell_id = None
                db.flush()
                db.execute(delete(Modell))
            anzahl = 0
            for eintrag in block.get("modelle") or []:
                alt = db.scalar(select(Modell).where(Modell.name == eintrag.get("name")))
                if alt is None:
                    alt = Modell(name=str(eintrag.get("name")), erstellt=jetzt)
                    db.add(alt)
                alt.url = str(eintrag.get("url") or "")
                alt.modellname = str(eintrag.get("modellname") or "")
                alt.kontextlaenge = eintrag.get("kontextlaenge")
                alt.zugang_id = zugang_ids.get(eintrag.get("zugang")) if eintrag.get("zugang") else None
                alt.test_ok = None
                alt.geaendert = jetzt
                anzahl += 1
            db.flush()
            modell_ids = {m.name: m.id for m in db.scalars(select(Modell))}
            for eintrag in block.get("rollen") or []:
                rolle = db.scalar(select(Rolle).where(Rolle.kennung == eintrag.get("kennung")))
                if rolle is None:
                    continue  # Rollen sind fest (schnell, stark)
                rolle.haupt_modell_id = modell_ids.get(eintrag.get("haupt")) if eintrag.get("haupt") else None
                rolle.ersatz_modell_id = (
                    modell_ids.get(eintrag.get("ersatz")) if eintrag.get("ersatz") else None
                )
            zusammenfassung["modelle"] = anzahl

        # --- Telefonie
        if modus("telefonie") != "auslassen" and datei.get("telefonie") is not None:
            neu = datei["telefonie"]
            einstellung = db.scalar(select(TelefonieEinstellung))
            if einstellung is None:
                einstellung = TelefonieEinstellung()
                db.add(einstellung)
            adapter = _kennung_zu_knoten(neu.get("adapter"), kennung_ids)
            einstellung.adapter = adapter or "test"
            einstellung.landesvorwahl = neu.get("landesvorwahl") or "+41"
            einstellung.eigene_nummern = neu.get("eigene_nummern") or []
            einstellung.erlaubte_anrufer = neu.get("erlaubte_anrufer") or []
            einstellung.ruhezeiten = neu.get("ruhezeiten") or []
            einstellung.nur_bekannte = bool(neu.get("nur_bekannte", True))
            zusammenfassung["telefonie"] = 1

        # --- Übersicht
        if modus("uebersicht") != "auslassen":
            if modus("uebersicht") == "ersetzen":
                db.execute(delete(KnotenPosition))
            anzahl = 0
            for eintrag in datei.get("uebersicht") or []:
                knoten = _kennung_zu_knoten(eintrag.get("knoten"), kennung_ids)
                if knoten is None:
                    continue
                position = db.get(KnotenPosition, knoten)
                if position is None:
                    position = KnotenPosition(knoten=knoten)
                    db.add(position)
                position.x = float(eintrag.get("x") or 0)
                position.y = float(eintrag.get("y") or 0)
                anzahl += 1
            zusammenfassung["uebersicht"] = anzahl

        db.commit()
        return {"eingespielt": zusammenfassung, "zugang_fehlt": fehlende_zugaenge}

    def _integration_einspielen(
        self, db: Session, eintrag: dict[str, Any], zugang_ids: dict[str, int], jetzt: Any
    ) -> bool:
        """Legt eine Integration an oder überschreibt sie. Gibt zurück, ob ein Zugang fehlt."""
        kennung = str(eintrag.get("kennung") or "")
        katalog = self.integrationen.katalog.eintraege.get(str(eintrag.get("manifest_id")))
        zugang_felder = (
            {feld.name for feld in katalog.manifest.felder if feld.typ == "zugang"} if katalog else set()
        )
        konfig: dict[str, Any] = {}
        fehlt: list[str] = []
        for name, wert in (eintrag.get("konfig") or {}).items():
            if isinstance(wert, dict) and set(wert) == {"zugang"}:
                zugang_id = zugang_ids.get(wert["zugang"]) if wert["zugang"] else None
                if zugang_id is None:
                    fehlt.append(str(wert["zugang"]))
                else:
                    konfig[name] = zugang_id
            elif name not in zugang_felder:
                konfig[name] = wert

        integration = db.scalar(
            select(Integration)
            .options(selectinload(Integration.funktionen))
            .where(Integration.kennung == kennung)
        )
        if integration is None:
            integration = Integration(
                manifest_id=str(eintrag.get("manifest_id")),
                kennung=kennung,
                zustand={},
                erstellt=jetzt,
            )
            db.add(integration)
        integration.manifest_id = str(eintrag.get("manifest_id"))
        integration.name = str(eintrag.get("name") or kennung)
        integration.konfig = konfig
        integration.aktiv = bool(eintrag.get("aktiv", True))
        zugriff = eintrag.get("zugriff")
        integration.zugriff = zugriff if zugriff in ZUGRIFFE else "nachfragen"
        integration.geaendert = jetzt
        integration.geprueft = None
        # Bis zum nächsten Test: „ungetestet“ – oder „Zugang fehlt“, wenn die Sicherung keinen mitbrachte.
        integration.status = STATUS_UNGETESTET
        integration.status_meldung = (
            f"Zugang fehlt: {', '.join(sorted(set(fehlt)))}" if fehlt else "Aus einer Sicherung eingespielt."
        )
        integration.status_hinweis = (
            "Unter „Integrationen“ bearbeiten, einen Zugang auswählen oder neu anlegen und testen."
            if fehlt
            else "Bitte einmal „Testen“ – danach steht die Integration wieder auf „in Ordnung“."
        )
        vorhandene = {funktion.name: funktion for funktion in integration.funktionen}
        neue_namen = set()
        for daten in eintrag.get("funktionen") or []:
            name = str(daten.get("name"))
            neue_namen.add(name)
            funktion = vorhandene.get(name)
            if funktion is None:
                funktion = Funktion(name=name)
                integration.funktionen.append(funktion)
            funktion.beschreibung = str(daten.get("beschreibung") or "")
            funktion.parameter = daten.get("parameter") or {"type": "object", "properties": {}}
            funktion.schreibend = bool(daten.get("schreibend", True))
            recht = daten.get("recht")
            funktion.recht = recht if recht in RECHTE else "nachfragen"
            funktion.vorhanden = bool(daten.get("vorhanden", True))
            funktion.extra = daten.get("extra") or {}
            funktion.zu_pruefen = False
        for name, funktion in vorhandene.items():
            if name not in neue_namen:
                integration.funktionen.remove(funktion)
        return bool(fehlt)


# ---------------------------------------------------------------------- Verweise über Datenbank-Nummern


def _ids_zu_kennungen(daten: dict[str, Any], kennungen: dict[int, str]) -> dict[str, Any]:
    """In Regeln stehen Integrationen als Nummer – in der Sicherung als Kennung (Nummern ändern sich)."""
    daten = dict(daten or {})
    if isinstance(daten.get("integration_id"), int):
        daten["integration"] = kennungen.get(daten.pop("integration_id"))
    daten.pop("geraet_id", None)  # Geräte werden nicht gesichert
    return daten


def _kennungen_zu_ids(daten: dict[str, Any], ids: dict[str, int]) -> dict[str, Any]:
    daten = dict(daten or {})
    if "integration" in daten:
        kennung = daten.pop("integration")
        if kennung in ids:
            daten["integration_id"] = ids[kennung]
    return daten


def _knoten_zu_kennung(knoten: str | None, kennungen: dict[int, str]) -> str | None:
    """„integration:7“ → „integration@kalender“. Knoten mit anderen Nummern werden weggelassen."""
    if not knoten:
        return None
    art, _, rest = knoten.partition(":")
    if not rest:
        return knoten
    if art == "integration" and rest.isdigit():
        kennung = kennungen.get(int(rest))
        return f"integration@{kennung}" if kennung else None
    return None if rest.isdigit() else knoten


def _kennung_zu_knoten(knoten: str | None, ids: dict[str, int]) -> str | None:
    if not knoten:
        return None
    if knoten.startswith("integration@"):
        nummer = ids.get(knoten.split("@", 1)[1])
        return f"integration:{nummer}" if nummer else None
    return knoten


def _konfig_ohne_zugaenge(konfig: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (konfig or {}).items() if not isinstance(v, int | dict)}
