"""Login-Logik: Einrichtung, Anmeldung mit Passwort + TOTP, Sitzungen und Sperre."""

from __future__ import annotations

import hmac
import math
from dataclasses import dataclass
from datetime import timedelta

import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.auth.modelle import Admin, Sitzung
from missa_control.config import Einstellungen
from missa_control.fehler import PanelFehler
from missa_control.krypto import Krypto

MIN_PASSWORT_LAENGE = 10
MAX_PASSWORT_LAENGE = 256
TOTP_SCHRITT_SEKUNDEN = 30
AUSSTELLER = "Missa Control"
KONTO = "admin"

_hasher = PasswordHasher()


@dataclass(frozen=True)
class Einrichtungsdaten:
    """Was die Oberfläche bei der Einrichtung anzeigt, und der Token für den Einrichtungs-Cookie."""

    geheimnis: str
    otpauth_url: str
    qr_svg: str
    einrichtungs_token: str


class AuthDienst:
    def __init__(self, einstellungen: Einstellungen, krypto: Krypto) -> None:
        self.einstellungen = einstellungen
        self.krypto = krypto

    # ---------- Zustand ----------

    @staticmethod
    def admin(db: Session) -> Admin | None:
        return db.get(Admin, 1)

    def ist_eingerichtet(self, db: Session) -> bool:
        admin = self.admin(db)
        return bool(admin and admin.eingerichtet)

    # ---------- Einrichtung ----------

    def einrichtung_beginnen(self, db: Session, passwort: str) -> Einrichtungsdaten:
        """Schritt 1: Passwort setzen. Solange der Code nicht bestätigt ist, kann neu begonnen werden."""
        admin = self.admin(db)
        if admin and admin.eingerichtet:
            raise PanelFehler(409, "Das Panel ist bereits eingerichtet.", "Bitte normal anmelden.")
        if len(passwort) < MIN_PASSWORT_LAENGE:
            raise PanelFehler(
                422,
                f"Das Passwort ist zu kurz (mindestens {MIN_PASSWORT_LAENGE} Zeichen).",
                "Am besten einen Passwort-Manager verwenden und ein langes, zufälliges Passwort wählen.",
            )
        if len(passwort) > MAX_PASSWORT_LAENGE:
            raise PanelFehler(422, f"Das Passwort ist zu lang (höchstens {MAX_PASSWORT_LAENGE} Zeichen).")

        geheimnis = pyotp.random_base32()
        token = self.krypto.neuer_token()
        if admin is None:
            admin = Admin(id=1, erstellt=zeit.jetzt())
            db.add(admin)
        admin.passwort_hash = _hasher.hash(passwort)
        admin.totp_geheimnis = self.krypto.verschluesseln(geheimnis)
        admin.eingerichtet = False
        admin.einrichtung_pruefsumme = self.krypto.token_pruefsumme(token)
        admin.totp_letzter_schritt = None
        admin.fehlversuche = 0
        admin.gesperrt_bis = None
        db.commit()

        url = pyotp.TOTP(geheimnis).provisioning_uri(name=KONTO, issuer_name=AUSSTELLER)
        qr = segno.make(url, error="m").svg_data_uri(scale=5, border=2, dark="#000000", light="#ffffff")
        return Einrichtungsdaten(geheimnis=geheimnis, otpauth_url=url, qr_svg=qr, einrichtungs_token=token)

    def einrichtung_abschliessen(self, db: Session, code: str, einrichtungs_token: str | None) -> str:
        """Schritt 2: Code aus der Authenticator-App bestätigen. Gibt den Sitzungs-Token zurück."""
        admin = self.admin(db)
        if admin is None:
            raise PanelFehler(
                409, "Die Einrichtung wurde noch nicht begonnen.", "Bitte zuerst ein Passwort setzen."
            )
        if admin.eingerichtet:
            raise PanelFehler(409, "Das Panel ist bereits eingerichtet.", "Bitte normal anmelden.")
        erwartet = admin.einrichtung_pruefsumme or ""
        erhalten = self.krypto.token_pruefsumme(einrichtungs_token or "")
        if not hmac.compare_digest(erwartet, erhalten):
            raise PanelFehler(
                403,
                "Die Einrichtung wurde in einem anderen Browser begonnen oder ist abgelaufen.",
                "Bitte die Einrichtung in diesem Browser neu starten (Passwort erneut setzen).",
            )
        self._sperre_pruefen(admin)
        if not self._totp_pruefen(admin, code):
            self._fehlversuch(db, admin)
            raise PanelFehler(
                401,
                "Der Code stimmt nicht.",
                "Bitte den aktuellen 6-stelligen Code aus der Authenticator-App eingeben. "
                "Stimmt die Uhrzeit auf dem Handy?",
            )
        admin.eingerichtet = True
        admin.einrichtung_pruefsumme = None
        admin.fehlversuche = 0
        return self._sitzung_erzeugen(db)

    # ---------- Anmeldung ----------

    def anmelden(self, db: Session, passwort: str, code: str) -> str:
        """Prüft Passwort und Code. Gibt den Sitzungs-Token zurück."""
        admin = self.admin(db)
        if admin is None or not admin.eingerichtet:
            raise PanelFehler(
                409, "Das Panel ist noch nicht eingerichtet.", "Bitte zuerst die Einrichtung abschliessen."
            )
        self._sperre_pruefen(admin)

        passwort_ok = self._passwort_pruefen(admin, passwort[:MAX_PASSWORT_LAENGE])
        # Der Code wird nur "verbraucht", wenn auch das Passwort stimmt.
        if not (passwort_ok and self._totp_pruefen(admin, code)):
            verbleibend = self._fehlversuch(db, admin)
            if verbleibend == 0:
                raise self._gesperrt_fehler(admin)
            raise PanelFehler(
                401,
                "Passwort oder Code falsch.",
                f"Noch {verbleibend} Versuch(e), danach ist die Anmeldung "
                f"{self.einstellungen.sperre_minuten} Minuten gesperrt.",
            )
        admin.fehlversuche = 0
        admin.gesperrt_bis = None
        return self._sitzung_erzeugen(db)

    def abmelden(self, db: Session, token: str | None) -> None:
        if token:
            db.execute(delete(Sitzung).where(Sitzung.token_pruefsumme == self.krypto.token_pruefsumme(token)))
            db.commit()

    def sitzung_gueltig(self, db: Session, token: str | None) -> bool:
        if not token:
            return False
        sitzung = db.scalar(
            select(Sitzung).where(Sitzung.token_pruefsumme == self.krypto.token_pruefsumme(token))
        )
        return sitzung is not None and sitzung.laeuft_ab > zeit.jetzt()

    # ---------- intern ----------

    def _sitzung_erzeugen(self, db: Session) -> str:
        zeitpunkt = zeit.jetzt()
        db.execute(delete(Sitzung).where(Sitzung.laeuft_ab <= zeitpunkt))
        token = self.krypto.neuer_token()
        db.add(
            Sitzung(
                token_pruefsumme=self.krypto.token_pruefsumme(token),
                erstellt=zeitpunkt,
                laeuft_ab=zeitpunkt + timedelta(hours=self.einstellungen.sitzung_stunden),
            )
        )
        db.commit()
        return token

    @staticmethod
    def _passwort_pruefen(admin: Admin, passwort: str) -> bool:
        try:
            return _hasher.verify(admin.passwort_hash, passwort)
        except (Argon2Error, InvalidHashError):
            return False

    def _totp_pruefen(self, admin: Admin, code: str) -> bool:
        """Akzeptiert den aktuellen Code sowie den davor und danach (Uhren gehen selten exakt gleich)."""
        code = "".join(zeichen for zeichen in code if zeichen.isdigit())
        if len(code) != 6:
            return False
        totp = pyotp.TOTP(self.krypto.entschluesseln(admin.totp_geheimnis))
        aktuell = int(zeit.jetzt().timestamp()) // TOTP_SCHRITT_SEKUNDEN
        for schritt in (aktuell - 1, aktuell, aktuell + 1):
            if schritt <= (admin.totp_letzter_schritt or 0):
                continue  # dieser Code wurde schon einmal benutzt
            if hmac.compare_digest(totp.at(schritt * TOTP_SCHRITT_SEKUNDEN), code):
                admin.totp_letzter_schritt = schritt
                return True
        return False

    def _sperre_pruefen(self, admin: Admin) -> None:
        if admin.gesperrt_bis and admin.gesperrt_bis > zeit.jetzt():
            raise self._gesperrt_fehler(admin)

    def _fehlversuch(self, db: Session, admin: Admin) -> int:
        """Zählt einen Fehlversuch und sperrt bei Bedarf. Gibt die verbleibenden Versuche zurück."""
        admin.fehlversuche += 1
        verbleibend = max(self.einstellungen.max_fehlversuche - admin.fehlversuche, 0)
        if verbleibend == 0:
            admin.gesperrt_bis = zeit.jetzt() + timedelta(minutes=self.einstellungen.sperre_minuten)
            admin.fehlversuche = 0
        db.commit()
        return verbleibend

    @staticmethod
    def _gesperrt_fehler(admin: Admin) -> PanelFehler:
        rest = (admin.gesperrt_bis - zeit.jetzt()).total_seconds() if admin.gesperrt_bis else 0
        minuten = max(math.ceil(rest / 60), 1)
        return PanelFehler(
            429,
            "Zu viele Fehlversuche – die Anmeldung ist vorübergehend gesperrt.",
            f"Bitte in {minuten} Minute(n) erneut versuchen.",
        )
