# Meldungen

Wartet eine Freigabe oder fällt eine Integration aus, schickt das Panel **von sich aus** eine Nachricht –
aufs Handy über [ntfy](https://ntfy.sh) oder an einen beliebigen Webhook.

## Ziel anlegen

Im Panel **Meldungen → Ziel hinzufügen**:

| Feld | Bedeutung |
| --- | --- |
| Name | z. B. „Handy“ |
| Art | **ntfy** oder **Webhook** |
| Adresse | ntfy: Adresse des Servers, z. B. `https://ntfy.sh` oder dein eigener. Webhook: die Adresse, an die das Panel sendet. |
| Thema | nur ntfy: das Thema, das du in der ntfy-App abonniert hast. Auf ntfy.sh einen schwer zu erratenden Namen wählen – wer ihn kennt, kann mitlesen. |
| Zugang | optional: Token oder Benutzer + Passwort, falls das Ziel eine Anmeldung verlangt (wird als `Authorization: Bearer …` bzw. Basic gesendet). Geheimnisse liegen wie immer verschlüsselt unter „Zugänge“. |
| Adresse des Panels | für den Link in der Meldung (z. B. zur Seite „Freigaben“). Vorbelegt mit der Adresse, unter der du das Panel gerade öffnest. |

Mit **„Test-Meldung senden“** prüfst du das Ziel sofort. Schlägt das Senden fehl, steht der Grund am
Ziel und im Protokoll (Funktion `meldung_ntfy` bzw. `meldung_webhook`).

## Was gemeldet wird

Pro Ziel wählbar:

| Meldung | Standard |
| --- | --- |
| Freigabe wartet | an |
| Integration ausgefallen / wieder da | an |
| Gerät offline | aus |
| Regel ausgelöst ab Dringlichkeit „hoch“ | aus |

Die Meldung zu einer **Freigabe** enthält den Vorschau-Satz („was genau würde passieren“) und den Link
zur Seite „Freigaben“ – **nie** die Parameter des Aufrufs, denn sie können Geheimnisse enthalten.
Erlauben und Ablehnen geht weiterhin **nur im Panel**; eine Meldung enthält keine Knöpfe dafür.

## Schutz vor Flut

- Dieselbe Meldung (gleiche Art, gleicher Titel) geht höchstens einmal pro Minute hinaus.
- Kommen mehr als 5 Meldungen in einer Minute, werden die übrigen zu einer einzigen
  zusammengefasst („3 weitere Meldungen“ mit der Liste der Titel).

## Ein Ziel antwortet nicht

Gesendet wird im Hintergrund, mit höchstens 5 Sekunden pro Versuch. Ein langsames oder nicht
erreichbares Ziel hält deshalb weder Freigaben noch das Panel auf. Der Grund steht am Ziel und im
Protokoll; beim nächsten erfolgreichen Senden verschwindet der Fehler.

## Was ein Webhook bekommt

`POST` an die Adresse, `Content-Type: application/json`:

```json
{
  "quelle": "missa-control",
  "art": "freigabe",
  "titel": "Freigabe wartet: kalender_termin_loeschen",
  "nachricht": "Löscht den Termin „Zahnarzt“ am 3. Februar – Bitte im Panel unter „Freigaben“ erlauben oder ablehnen.",
  "dringlichkeit": "hoch",
  "zeit": "2026-11-16T12:00:00+00:00",
  "link": "http://ai01:8090/freigaben",
  "daten": {"freigabe_id": 7, "funktion": "kalender_termin_loeschen"}
}
```

`art` ist `freigabe`, `integration`, `geraet_offline`, `regel_hoch`, `zusammenfassung` oder `test`.
Bei ntfy wird dieselbe Nachricht als JSON an die Adresse des Servers geschickt (`topic`, `title`,
`message`, `priority`, `click`).
