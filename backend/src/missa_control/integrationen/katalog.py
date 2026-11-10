"""Der Katalog: alle verfügbaren Integrationen.

Eingebaute Integrationen liegen im Repo unter `integrations/`, eigene in `data/integrations/`.
Jeder Unterordner mit einer gültigen `integration.yaml` wird beim Start erkannt.
Ordner, die mit `_` oder `.` beginnen (z. B. `_vorlage`), werden übersprungen.
"""

from __future__ import annotations

import ast
import io
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from missa_control.fehler import PanelFehler
from missa_control.integrationen.manifest import (
    MANIFEST_DATEI,
    Manifest,
    ManifestFehler,
    manifest_aus_text,
    manifest_laden,
)

MAX_ZIP_BYTES = 5 * 1024 * 1024
MAX_ENTPACKT_BYTES = 20 * 1024 * 1024
MAX_DATEIEN = 300


@dataclass(frozen=True)
class KatalogEintrag:
    manifest: Manifest
    ordner: Path
    eingebaut: bool


@dataclass(frozen=True)
class KatalogProblem:
    """Ein Ordner, der wie eine Integration aussieht, aber nicht geladen werden konnte."""

    ordner: str
    meldungen: list[str]


class Katalog:
    def __init__(self, eingebaut: Path | None, eigene: Path) -> None:
        self.eingebaut_ordner = eingebaut
        self.eigene_ordner = eigene
        self.eintraege: dict[str, KatalogEintrag] = {}
        self.probleme: list[KatalogProblem] = []
        self.einlesen()

    def einlesen(self) -> None:
        """Liest beide Ordner neu ein."""
        eintraege: dict[str, KatalogEintrag] = {}
        probleme: list[KatalogProblem] = []
        for basis, eingebaut in ((self.eingebaut_ordner, True), (self.eigene_ordner, False)):
            if basis is None or not basis.is_dir():
                continue
            for ordner in sorted(pfad for pfad in basis.iterdir() if pfad.is_dir()):
                if ordner.name.startswith(("_", ".")):
                    continue
                try:
                    manifest = manifest_laden(ordner)
                    if manifest.art == "python" and not (ordner / "main.py").is_file():
                        raise ManifestFehler(["Die Datei main.py fehlt (nötig bei „art: python“)."])
                    if manifest.id in eintraege:
                        anderer = eintraege[manifest.id]
                        woher = (
                            "einer eingebauten Integration"
                            if anderer.eingebaut
                            else f"„{anderer.ordner.name}“"
                        )
                        raise ManifestFehler([f"Die id „{manifest.id}“ wird bereits von {woher} verwendet."])
                except ManifestFehler as fehler:
                    probleme.append(KatalogProblem(ordner=ordner.name, meldungen=fehler.meldungen))
                    continue
                eintraege[manifest.id] = KatalogEintrag(manifest=manifest, ordner=ordner, eingebaut=eingebaut)
        self.eintraege = eintraege
        self.probleme = probleme

    def holen(self, manifest_id: str) -> KatalogEintrag:
        eintrag = self.eintraege.get(manifest_id)
        if eintrag is None:
            raise PanelFehler(
                404,
                f"Die Integration „{manifest_id}“ gibt es im Katalog nicht (mehr).",
                "Wurde der Ordner gelöscht oder umbenannt? Unter „Katalog“ lässt sich der Katalog neu einlesen.",
            )
        return eintrag

    # ---------- eigene Integrationen hochladen ----------

    def zip_hochladen(self, inhalt: bytes, *, ersetzen: bool = False) -> tuple[Manifest, bool]:
        """Prüft ein ZIP und legt es als eigene Integration ab. Gibt (Manifest, wurde_ersetzt) zurück."""
        if len(inhalt) > MAX_ZIP_BYTES:
            raise PanelFehler(413, "Das ZIP ist zu gross (höchstens 5 MB).")
        try:
            archiv = zipfile.ZipFile(io.BytesIO(inhalt))
        except zipfile.BadZipFile as fehler:
            raise PanelFehler(
                422,
                "Die Datei ist kein gültiges ZIP-Archiv.",
                "Bitte den Ordner der Integration als .zip packen und erneut hochladen.",
            ) from fehler

        with archiv:
            dateien = [info for info in archiv.infolist() if not info.is_dir()]
            wurzel = _wurzel_finden(dateien)
            _dateien_pruefen(dateien)
            manifest = _manifest_aus_zip(archiv, wurzel)
            if manifest.art == "python":
                _main_pruefen(archiv, wurzel)

            vorhanden = self.eintraege.get(manifest.id)
            if vorhanden is not None and vorhanden.eingebaut:
                raise PanelFehler(
                    409,
                    f"Die id „{manifest.id}“ gehört zu einer eingebauten Integration.",
                    "Bitte in integration.yaml eine andere id eintragen.",
                )
            ziel = self.eigene_ordner / manifest.id
            ersetzt = ziel.exists()
            if ersetzt and not ersetzen:
                raise PanelFehler(
                    409,
                    f"Eine eigene Integration mit der id „{manifest.id}“ gibt es schon.",
                    "Zum Aktualisieren „Vorhandene ersetzen“ wählen – oder in integration.yaml eine andere id eintragen.",
                )

            self.eigene_ordner.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.eigene_ordner, prefix=".upload-") as zwischen:
                entpackt = Path(zwischen) / manifest.id
                for info in dateien:
                    relativ = (
                        PurePosixPath(info.filename).relative_to(wurzel)
                        if wurzel
                        else PurePosixPath(info.filename)
                    )
                    datei = entpackt.joinpath(*relativ.parts)
                    datei.parent.mkdir(parents=True, exist_ok=True)
                    datei.write_bytes(archiv.read(info))
                if ersetzt:
                    shutil.rmtree(ziel)
                entpackt.rename(ziel)
        self.einlesen()
        return manifest, ersetzt

    def eigene_entfernen(self, manifest_id: str) -> None:
        eintrag = self.holen(manifest_id)
        if eintrag.eingebaut:
            raise PanelFehler(409, "Eingebaute Integrationen können nicht aus dem Katalog entfernt werden.")
        shutil.rmtree(eintrag.ordner)
        self.einlesen()


def _wurzel_finden(dateien: list[zipfile.ZipInfo]) -> str:
    """integration.yaml liegt im Hauptordner des ZIP oder in genau einem Unterordner."""
    namen = [PurePosixPath(info.filename) for info in dateien]
    if any(name == PurePosixPath(MANIFEST_DATEI) for name in namen):
        return ""
    kandidaten = {name.parts[0] for name in namen if len(name.parts) == 2 and name.name == MANIFEST_DATEI}
    if len(kandidaten) == 1:
        return kandidaten.pop()
    raise PanelFehler(
        422,
        f"Im ZIP fehlt die Datei {MANIFEST_DATEI}.",
        f"{MANIFEST_DATEI} muss im Hauptordner des Archivs liegen oder in genau einem Unterordner.",
    )


def _dateien_pruefen(dateien: list[zipfile.ZipInfo]) -> None:
    if len(dateien) > MAX_DATEIEN:
        raise PanelFehler(422, f"Das ZIP enthält zu viele Dateien (höchstens {MAX_DATEIEN}).")
    if sum(info.file_size for info in dateien) > MAX_ENTPACKT_BYTES:
        raise PanelFehler(422, "Der Inhalt des ZIP ist zu gross (höchstens 20 MB entpackt).")
    for info in dateien:
        pfad = PurePosixPath(info.filename)
        ist_verknuepfung = (info.external_attr >> 16) & 0o170000 == 0o120000
        if pfad.is_absolute() or ".." in pfad.parts or "\\" in info.filename or ist_verknuepfung:
            raise PanelFehler(
                422,
                f"Das ZIP enthält einen unzulässigen Pfad: {info.filename}",
                "Erlaubt sind nur normale Dateien innerhalb des Integrations-Ordners.",
            )


def _manifest_aus_zip(archiv: zipfile.ZipFile, wurzel: str) -> Manifest:
    name = f"{wurzel}/{MANIFEST_DATEI}" if wurzel else MANIFEST_DATEI
    try:
        return manifest_aus_text(archiv.read(name).decode("utf-8"))
    except UnicodeDecodeError as fehler:
        raise PanelFehler(422, f"{MANIFEST_DATEI} ist nicht als UTF-8 gespeichert.") from fehler
    except ManifestFehler as fehler:
        raise PanelFehler(
            422,
            f"{MANIFEST_DATEI} ist ungültig: " + " · ".join(fehler.meldungen),
            "Die Vorlage in integrations/_vorlage/ zeigt den richtigen Aufbau.",
        ) from fehler


def _main_pruefen(archiv: zipfile.ZipFile, wurzel: str) -> None:
    name = f"{wurzel}/main.py" if wurzel else "main.py"
    if name not in archiv.namelist():
        raise PanelFehler(
            422,
            "Im ZIP fehlt die Datei main.py.",
            "Bei „art: python“ stehen die Funktionen in main.py neben integration.yaml.",
        )
    try:
        ast.parse(archiv.read(name).decode("utf-8"), filename="main.py")
    except SyntaxError as fehler:
        raise PanelFehler(
            422,
            f"main.py enthält einen Syntaxfehler in Zeile {fehler.lineno}: {fehler.msg}",
            "Bitte den Fehler korrigieren und das ZIP erneut hochladen.",
        ) from fehler
    except UnicodeDecodeError as fehler:
        raise PanelFehler(422, "main.py ist nicht als UTF-8 gespeichert.") from fehler
