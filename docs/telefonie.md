# Telefonie

Missa kann anrufen und angerufen werden – vorbereitet ist dafür alles, was das Panel entscheidet:
wer Missa erreichen darf, wen sie anrufen darf, wann sie still bleibt, die Freigabe und der
Verlauf. Was noch fehlt, ist das Telefon selbst: Mitgeliefert ist ein **Test-Adapter**, der Anrufe
nur protokolliert und als Ereignis meldet. Ein echter Adapter (SIP-Anlage, Telefon-App) lässt sich
später als Integration ergänzen – ohne dass sich an den Regeln hier etwas ändert.

## Seite „Anrufe“

| Einstellung | Bedeutung |
| --- | --- |
| Eigene Nummern | Unter diesen Nummern erreicht Missa dich. Die erste wird angerufen, wenn Missa oder eine Regel ohne Nummer anruft. Eigene Nummern dürfen Missa immer anrufen. |
| Erlaubte Anrufer | Weitere Nummern, die Missa erreichen dürfen. Alle anderen Anrufe werden abgewiesen und stehen im Verlauf. |
| Ruhezeiten | In dieser Zeit ruft Missa nur an, wenn es **dringend** ist. Alles andere wird nicht ausgeführt, steht im Verlauf und kommt als Ereignis bei Missa an. |
| Missa ruft nur eigene Nummern und erlaubte Anrufer an | Eingeschaltet (Standard) kann Missa keine fremden Nummern wählen. |
| Landesvorwahl | Wird Nummern ohne Vorwahl vorangestellt: `079 123 45 67` wird zu `+41791234567`. So sind verschieden geschriebene Nummern dieselbe. |
| Telefonie-Adapter | Wer wirklich telefoniert. Zur Wahl stehen der Test-Adapter und alle Integrationen, die einen Adapter mitbringen. |

Unter **Ausprobieren** lässt sich beides ohne Telefon durchspielen: ein Anruf hinaus und ein Anruf
herein („käme diese Nummer durch?“). Der **Verlauf** zeigt Zeit, Richtung, Nummer, Dauer, Grund und
Ergebnis – auch für abgewiesene und in der Ruhezeit unterdrückte Anrufe.

## Wer anrufen darf

- **Missa** über die Funktion `telefon_anrufen` (Integration „Telefonie“ im Katalog aktivieren).
  Standard: „erst nachfragen“ – die Freigabe zeigt, wer angerufen und was gesagt würde.
- **Regeln** mit der Aktion „Anrufen“, z. B. „Wenn die CPU-Auslastung 5 Minuten lang über 90 %
  liegt, dann ruft Missa dich an“. Eine Regel fragt beim Auslösen nicht mehr nach; legt Missa selbst
  eine solche Regel an, braucht das Anlegen deine Freigabe.
- **Du** im Panel unter „Ausprobieren“.

In allen drei Fällen gelten dieselben Grenzen: bekannte Nummern, Ruhezeit (ausser dringend).

## Einen echten Adapter ergänzen

Die Schnittstelle besteht aus drei Dingen:

| Was | Richtung | Wie |
| --- | --- | --- |
| **anrufen** | Panel → Adapter | Funktion mit `@telefon_anrufen` in der `main.py` einer Integration |
| **Anruf beendet** | Adapter → Panel | Ergebnis der Funktion – oder später `POST /api/telefonie/adapter/anrufe/<id>/beendet` |
| **eingehender Anruf** | Adapter → Panel | `POST /api/telefonie/adapter/eingehend` – die Antwort sagt, ob der Anruf angenommen werden darf |

Ein Adapter ist eine ganz normale eigene Integration (siehe
[eigene-integration.md](eigene-integration.md)), deren `main.py` eine Funktion mit `@telefon_anrufen`
enthält. Sobald die Integration eingerichtet ist, steht sie auf der Seite „Anrufe“ als Adapter zur
Wahl. Felder im Formular (Adresse der Telefonanlage, Zugang) funktionieren wie bei jeder Integration.

```python
from missa_control.sdk import Fehler, Kontext, telefon_anrufen, telefon_auflegen


@telefon_anrufen
async def anrufen(kontext: Kontext, auftrag):
    """auftrag: anruf_id, nummer, name, text, dringlichkeit"""
    async with kontext.http() as client:
        antwort = await client.post(
            kontext.konfig["adresse"] + "/anrufe",
            json={"nummer": auftrag.nummer, "ansage": auftrag.text, "kennung": auftrag.anruf_id},
        )
    if antwort.status_code == 486:
        raise Fehler("Besetzt.", "Später noch einmal versuchen.")
    antwort.raise_for_status()
    # Nichts zurückgeben: Der Anruf läuft, das Ende meldet die Telefonanlage später (siehe unten).
    # Wartet die Funktion selbst bis zum Ende, gibt sie stattdessen zurück:
    # return {"ergebnis": "beendet", "dauer_sekunden": 42}   # oder "nicht_erreicht"


@telefon_auflegen  # optional
async def auflegen(kontext: Kontext, anruf_id: int) -> None:
    ...
```

Die Gegenrichtung braucht keinen Code im Panel. Die Telefonanlage, die App oder eine kleine Brücke
dazwischen meldet sich mit einem **Client-Token** (Seite „Clients“):

```bash
curl -X POST http://<adresse>:8090/api/telefonie/adapter/eingehend \
  -H "Authorization: Bearer <Token>" -H "Content-Type: application/json" \
  -d '{"nummer": "+41445556677"}'
```

Antwort: `{"annehmen": true, "anruf_id": 17, "nummer": "+41445556677", "name": "Oma", "grund": ""}` –
bei `annehmen: false` legt der Adapter auf; im Verlauf steht der Versuch als „abgewiesen“.

```bash
curl -X POST http://<adresse>:8090/api/telefonie/adapter/anrufe/17/beendet \
  -H "Authorization: Bearer <Token>" -H "Content-Type: application/json" \
  -d '{"dauer_sekunden": 42, "ergebnis": "beendet"}'
```

`ergebnis` ist `beendet` oder `nicht_erreicht`. Meldet ein Adapter das Ende nie, schliesst das Panel
den Anruf nach 12 Stunden selbst ab.

Was beim Anruf gesprochen wird, ist Sache von Missa und dem Adapter: Das Panel reicht den Text
weiter (`auftrag.text`) und meldet jeden Anruf als Ereignis der Art `anruf` – so erfährt missa-core
davon (siehe [anbindung-missa-core.md](anbindung-missa-core.md)).

## Grenzen dieses Stands

- Es ist kein echtes Telefon angeschlossen; mit dem Test-Adapter klingelt nirgends etwas.
- Ruhezeiten gelten täglich (keine Wochentage) und nur für ausgehende Anrufe.
- Einträge im Verlauf werden wie das Protokoll nach 30 Tagen gelöscht.
