# Eigene Integration schreiben

Eine Integration gibt Missa neue Fähigkeiten. Für die meisten Fälle braucht es **gar keinen Code**:
Ein MCP-Server oder eine REST-API mit OpenAPI-Beschreibung lässt sich direkt im Katalog einrichten.

Diese Anleitung ist für alles andere: ein kleiner Ordner mit zwei Dateien.

```
data/integrations/erreichbar/
├── integration.yaml   ← Name, Beschreibung, Formular
└── main.py            ← Python-Funktionen für Missa (optional)
```

Jede Integration bekommt vom Panel automatisch: ein Formular aus dem Manifest, den Verbindungstest,
Rechte pro Funktion, Status, Protokoll und verständliche Fehlermeldungen.

## In fünf Minuten zur ersten Integration

1. Den Ordner `integrations/_vorlage/` nach `data/integrations/<dein-name>/` kopieren.
2. In `integration.yaml` die Zeilen `id` und `name` ändern.
3. Panel neu starten – oder im Katalog auf **Neu einlesen** klicken.
4. Im Katalog erscheint die neue Karte: **Einrichten → Verbindung testen → Aktivieren**.

Alternativ den Ordner als ZIP packen und im Katalog über **Eigene Integration hochladen (ZIP)**
hochladen. Das Panel prüft das Manifest und sagt genau, was nicht stimmt.

Eigene Integrationen liegen immer in `data/integrations/` (sie bleiben bei Updates erhalten und sind
im Backup enthalten). Die eingebauten liegen im Repo unter `integrations/`.

## Vollständiges Beispiel

Die Integration prüft, ob ein Dienst im Netz antwortet, und merkt sich Notizen dazu.

`integration.yaml`:

```yaml
id: erreichbar
name: Erreichbarkeit
beschreibung: Prüft, ob ein Dienst im Netz antwortet, und merkt sich Notizen dazu.
symbol: "📡"
art: python
version: 1.0.0
felder:
  - name: adresse
    titel: Adresse des Dienstes
    typ: url
    pflicht: true
    hilfe: z. B. http://192.168.1.20:8080
  - name: token
    titel: Token (optional)
    typ: zugang
    zugang_typen: [bearer_token]
```

`main.py` (28 Zeilen):

```python
from missa_control.sdk import Fehler, Kontext, auth_header, funktion, verbindungstest


async def _abfragen(kontext: Kontext, pfad: str = "") -> int:
    kopf = auth_header(kontext.zugang_optional("token"))
    async with kontext.http() as client:
        antwort = await client.get(kontext.konfig["adresse"] + pfad, headers=kopf)
    return antwort.status_code


@verbindungstest
async def testen(kontext: Kontext) -> str:
    return f"Dienst antwortet mit Status {await _abfragen(kontext)}."


@funktion(beschreibung="Prüft, ob der Dienst erreichbar ist.", schreibend=False)
async def dienst_pruefen(kontext: Kontext, pfad: str = "") -> dict:
    """pfad: Unterseite, die geprüft werden soll, z. B. /status"""
    status = await _abfragen(kontext, pfad)
    if status >= 500:
        raise Fehler(f"Der Dienst meldet einen Fehler ({status}).", "Läuft der Dienst richtig?")
    return {"erreichbar": status < 400, "status": status}


@funktion(beschreibung="Merkt sich eine Notiz zum Dienst.", schreibend=True)
def notiz_merken(kontext: Kontext, text: str) -> str:
    kontext.zustand.setdefault("notizen", []).append(text)
    return f"{len(kontext.zustand['notizen'])} Notiz(en) gespeichert."
```

Das ist alles. Missa sieht danach zwei Funktionen: `erreichbarkeit_dienst_pruefen` (lesend, sofort
erlaubt) und `erreichbarkeit_notiz_merken` (schreibend, fragt erst nach).

## Das Manifest `integration.yaml`

| Eintrag | Pflicht | Bedeutung |
| --- | --- | --- |
| `id` | ja | Eindeutiger Kurzname: Kleinbuchstaben, Ziffern, Bindestriche |
| `name` | ja | Titel der Karte im Katalog |
| `beschreibung` | ja | Ein Satz: Was kann Missa damit? |
| `art` | ja | `python` für eigenen Code (daneben gibt es `mcp`, `openapi`, `webhook`, `geraet`) |
| `symbol` | nein | Ein Emoji |
| `version` | nein | Version der Integration, z. B. `1.0.0` |
| `felder` | nein | Die Felder des Formulars (siehe unten) |
| `standardrechte` | nein | Recht pro Funktion: `erlaubt`, `nachfragen` oder `gesperrt` |
| `mehrfach` | nein | `false`, wenn die Integration nur einmal eingerichtet werden darf |
| `kennung` | nein | Feste Vorsilbe der Funktionsnamen (sonst aus dem Namen gebildet) |
| `hinweis` | nein | Erklärender Text über dem Formular |

Tippfehler fallen sofort auf: Unbekannte Einträge lehnt das Panel mit einer klaren Meldung ab.

### Felder

Jedes Feld hat `name` (so heisst der Wert im Code), `titel` (Beschriftung) und einen `typ`:

| `typ` | Im Formular | Im Code |
| --- | --- | --- |
| `text` | Textfeld | `kontext.konfig["name"]` → Text |
| `zahl` | Zahlenfeld | → Zahl |
| `url` | Adresse (muss mit `http://` oder `https://` beginnen) | → Text |
| `auswahl` | Auswahlliste aus `optionen` | → gewählter `wert` |
| `schalter` | Ein/Aus | → `True` / `False` |
| `zugang` | Zugang auswählen oder direkt neu anlegen | `kontext.zugang("name")` |
| `datei` | Datei hochladen (Inhalt als Text) | → Inhalt der Datei |

Weitere Angaben pro Feld: `pflicht`, `hilfe`, `platzhalter`, `standard`, bei `auswahl` die `optionen`
(`- wert` oder `- {wert: …, titel: …}`), bei `zugang` die erlaubten `zugang_typen`
(`api_key`, `bearer_token`, `benutzer_passwort`), bei `datei` die `endungen`.

**Geheimnisse gehören nie in ein Textfeld.** Mit `typ: zugang` werden sie verschlüsselt gespeichert,
nur maskiert angezeigt und automatisch aus allen Protokollen geschwärzt.

## Funktionen in `main.py`

```python
@funktion(beschreibung="Was die Funktion tut", schreibend=False)
def meine_funktion(kontext: Kontext, ort: str, tage: int = 3) -> dict:
    """ort: Für welchen Ort
    tage: Wie viele Tage im Voraus"""
```

- **Name:** der Name der Python-Funktion (oder `name="…"` im Decorator). Am Gateway bekommt er die
  Vorsilbe der Integration.
- **Beschreibung:** `beschreibung=` – fehlt sie, wird der erste Absatz des Docstrings verwendet.
- **Parameter:** kommen aus den Typ-Hinweisen (`str`, `int`, `float`, `bool`, `list[…]`, `dict`,
  `Literal["a", "b"]`, `… | None`). Parameter mit Standardwert sind freiwillig. Zeilen der Form
  `name: Erklärung` im Docstring werden zur Beschreibung des Parameters.
- **`schreibend`:** `False` für Funktionen, die nur lesen – sie sind sofort „erlaubt“. Alles andere
  (ändern, löschen, senden, anrufen) ist schreibend und startet mit „erst nachfragen“.
  **Ohne Angabe gilt eine Funktion vorsichtshalber als schreibend.**
- **Rückgabe:** Text, Zahl, Liste oder Wörterbuch – Missa bekommt es als Text bzw. JSON.
- Funktionen dürfen normal (`def`) oder asynchron (`async def`) sein.
- Der erste Parameter `kontext` ist freiwillig; ohne ihn bekommt die Funktion nur ihre eigenen Parameter.

### Das Kontext-Objekt

| Zugriff | Liefert |
| --- | --- |
| `kontext.konfig["feld"]` | Wert aus dem Formular |
| `kontext.zugang("feld")` | Zugang: `.wert` (Key, Token oder Passwort), `.benutzer`, `.typ` – fehlt er, entsteht automatisch eine verständliche Meldung |
| `kontext.zugang_optional("feld")` | wie oben, aber `None`, wenn kein Zugang gewählt ist |
| `kontext.http()` | fertiger HTTP-Client (`httpx2`) mit Zeitlimit: `async with kontext.http() as client:` |
| `kontext.zustand` | kleines Gedächtnis der Integration (Wörterbuch), bleibt über Neustarts erhalten |
| `kontext.log` | Protokoll: `kontext.log.info("…")` |
| `kontext.name` | Name der eingerichteten Integration |

`auth_header(zugang)` baut den üblichen `Authorization`-Header (Bearer bzw. Basic).

### Verbindung testen

Eine Funktion mit `@verbindungstest` läuft bei „Verbindung testen“ (optional, höchstens eine).
Sie gibt einen kurzen Text zurück, z. B. `"Verbunden als missa"`.

### Fehler mit Lösungshinweis

```python
raise Fehler("Der Dienst lehnt das Token ab.", "Unter „Zugänge“ ein neues Token eintragen.")
```

Der erste Text sagt, was passiert ist, der zweite, was man tun kann. Beides erscheint im Panel und
geht als Antwort an Missa. Häufige Netzwerkfehler (nicht erreichbar, 401, 404, Zeitüberschreitung)
übersetzt das Panel von selbst.

## Ausprobieren und Fehler finden

- Unter **Integrationen → Funktionen und Rechte** hat jede Funktion einen Knopf **Ausprobieren**.
- **Testen** auf der Seite „Integrationen“ lädt eine geänderte `main.py` neu – ohne Neustart.
- Fehler aus dem eigenen Code stehen mit vollem Text im Protokoll:
  `docker compose -p missa-control logs missa-control`

## Was erlaubt ist

Eigene Integrationen laufen direkt im Panel und dürfen alles, was das Panel darf. Deshalb:

- Nur eigenen Code verwenden, keinen fremden ungeprüft hochladen.
- Im Panel stehen u. a. `httpx2`, `pydantic` und `pyyaml` bereit. Weitere Python-Pakete müssen ins
  Image (in `backend/pyproject.toml` eintragen und `./scripts/update.sh` ausführen).
- missa-core wird von Integrationen nie verändert – Missa holt sich ihre Funktionen selbst ab.
