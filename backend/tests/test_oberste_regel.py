"""Wächter für die oberste Regel: missa-core und fremde Container werden nie angefasst.

Diese Tests lesen Skripte, Compose-Datei und Dockerfile und schlagen an, sobald dort etwas
auftaucht, das fremde Container, Volumes, Netzwerke oder Systemdienste betreffen könnte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SKRIPTE = sorted((REPO / "scripts").glob("*.sh"))

VERBOTEN = [
    r"docker\s+system\s+prune",
    r"docker\s+(volume|network|image|container|builder)\s+prune",
    r"docker\s+(rm|stop|restart|kill|rmi|update|rename|pause)\b",
    r"docker\s+(volume|network)\s+(rm|create|connect|disconnect)",
    r"docker\.sock",
    r"\bsystemctl\b",
    r"\bservice\s+\w+\s+(start|stop|restart|reload)",
    r"\b(iptables|nft|ufw|firewall-cmd)\b",
    r"\bcaddy\b",
    r"\bapt(-get)?\s+(install|remove|purge)",
    r"\brm\s+-rf\s+/(?!\S*\$)",  # kein Löschen mit absolutem Pfad
]


def _ohne_kommentare(text: str) -> str:
    return "\n".join(zeile for zeile in text.splitlines() if not zeile.lstrip().startswith("#"))


def test_es_gibt_die_erwarteten_skripte() -> None:
    assert {skript.name for skript in SKRIPTE} >= {"install.sh", "update.sh", "backup.sh", "_gemeinsam.sh"}


@pytest.mark.parametrize("skript", SKRIPTE, ids=lambda skript: skript.name)
def test_skripte_enthalten_keine_verbotenen_befehle(skript: Path) -> None:
    text = _ohne_kommentare(skript.read_text(encoding="utf-8"))
    for muster in VERBOTEN:
        treffer = re.search(muster, text, flags=re.IGNORECASE)
        assert treffer is None, f"{skript.name} enthält Verbotenes: {treffer.group(0) if treffer else ''}"


@pytest.mark.parametrize("skript", SKRIPTE, ids=lambda skript: skript.name)
def test_skripte_brechen_bei_fehlern_ab(skript: Path) -> None:
    if skript.name.startswith("_"):
        return  # wird nur eingebunden
    assert "set -euo pipefail" in skript.read_text(encoding="utf-8")


@pytest.mark.parametrize("skript", SKRIPTE, ids=lambda skript: skript.name)
def test_docker_compose_nur_fuer_das_eigene_projekt(skript: Path) -> None:
    """Jeder Compose-Aufruf läuft über `compose()` aus _gemeinsam.sh, also mit `-p missa-control`."""
    text = _ohne_kommentare(skript.read_text(encoding="utf-8"))
    for zeile in text.splitlines():
        if re.search(r"\bdocker\s+compose\b", zeile):
            erlaubt = (
                'docker compose -p "$PROJEKT"' in zeile  # die Hilfsfunktion selbst
                or "docker compose version" in zeile  # prüft nur, ob Compose installiert ist
                or "docker compose -p $PROJEKT logs" in zeile  # Hinweistext für Menschen
                or 'Plugin \\"docker compose\\"' in zeile  # Fehlermeldung, kein Aufruf
            )
            assert erlaubt, f"{skript.name}: Compose-Aufruf ohne Projektnamen: {zeile.strip()}"
        for befehl in re.findall(r"\bdocker\s+(\w+)", zeile):
            assert befehl in ("compose", "info"), (
                f"{skript.name}: unerwarteter Docker-Befehl „docker {befehl}“"
            )
    assert 'PROJEKT="missa-control"' in (REPO / "scripts" / "_gemeinsam.sh").read_text(encoding="utf-8")


def test_compose_datei_bleibt_bei_den_eigenen_sachen() -> None:
    text = (REPO / "compose.yaml").read_text(encoding="utf-8")
    compose = yaml.safe_load(text)
    assert compose["name"] == "missa-control"
    assert "docker.sock" not in text
    assert set(compose["networks"]) == {"missa-control-net"}
    assert compose["networks"]["missa-control-net"].get("external") is not True
    for name, dienst in compose["services"].items():
        assert dienst.get("privileged") is not True, name
        assert dienst.get("network_mode") is None, name  # kein Zugriff aufs Host-Netz
        assert dienst.get("pid") is None, name
        assert set(dienst.get("networks", [])) <= {"missa-control-net"}, name
        for volume in dienst.get("volumes", []):
            quelle, _ziel, *modus = str(volume).split(":")
            if quelle.startswith("./data"):
                continue  # eigene Daten im Repo-Ordner
            # Eigene Konfiguration aus dem Repo-Ordner – und vom Host nur /proc und /sys. Alles nur lesend.
            assert quelle.startswith("./config/") or quelle in ("/proc", "/sys"), (
                f"{name}: unerwartetes Volume {volume}"
            )
            assert modus == ["ro"], f"{name}: {volume} muss nur lesend (:ro) eingebunden sein"
    assert set(compose["services"]) == {"missa-control", "mqtt"}  # nur eigene Dienste
    for name in ("missa-control", "mqtt"):
        dienst = compose["services"][name]
        assert dienst["restart"] == "unless-stopped", name
        assert dienst["read_only"] is True, name
        assert dienst["cap_drop"] == ["ALL"], name
        assert dienst["security_opt"] == ["no-new-privileges:true"], name
        assert "10001" in dienst["user"], name  # nie root
    # Keine Docker-Volumes: Alle eigenen Daten liegen in ./data. Das gilt auch für Volumes, die ein
    # Image von sich aus vorsieht (Mosquitto: /mosquitto/data und /mosquitto/log) – sonst legt Docker
    # dafür ein namenloses Volume an.
    assert "volumes" not in compose
    mqtt = compose["services"]["mqtt"]
    assert "./data/mosquitto:/mosquitto/data" in mqtt["volumes"]
    assert mqtt["tmpfs"] == ["/mosquitto/log"]
    # Der MQTT-Broker gehört zum Profil „geraete“ und lässt sich damit abschalten.
    assert mqtt["profiles"] == ["geraete"]
    assert "COMPOSE_PROFILES=geraete" in (REPO / ".env.example").read_text(encoding="utf-8")


def test_geraete_tests_fassen_nur_ihren_eigenen_test_container_an() -> None:
    """Die Geräte-Tests starten den echten MQTT-Broker als Container. Auch sie bleiben bei ihren
    eigenen Sachen: ein Container mit dem Präfix „missa-control“, der am Ende wieder gestoppt wird."""
    quelle = (REPO / "backend" / "tests" / "server.py").read_text(encoding="utf-8")
    assert set(re.findall(r'\[\s*"docker",\s*"(\w+)"', quelle)) == {"info", "run", "stop"}
    assert 'self.name = f"missa-control-test-mqtt-' in quelle
    assert '["docker", "stop", "-t", "1", self.name]' in quelle  # gestoppt wird nur genau dieser Container
    assert '"--rm"' in quelle and '"--tmpfs", "/mosquitto/log"' in quelle  # nichts bleibt zurück
    assert "docker.sock" not in quelle


def test_mqtt_broker_laesst_niemanden_ohne_anmeldung_herein() -> None:
    konfig = _ohne_kommentare((REPO / "config" / "mosquitto.conf").read_text(encoding="utf-8"))
    assert "allow_anonymous false" in konfig
    assert "allow_anonymous true" not in konfig
    assert "mosquitto_dynamic_security.so" in konfig  # eigener Zugang pro Gerät
    assert re.findall(r"^listener\s+(\d+)", konfig, flags=re.MULTILINE) == ["1883"]  # kein weiterer Anschluss
    assert "/mosquitto/data/" in konfig  # alle Daten in ./data/mosquitto


def test_gpu_zusatz_gibt_nur_das_auslese_werkzeug_frei() -> None:
    zusatz = yaml.safe_load((REPO / "config" / "compose.gpu.yaml").read_text(encoding="utf-8"))
    assert set(zusatz) == {"services"}
    assert set(zusatz["services"]) == {"missa-control"}
    dienst = zusatz["services"]["missa-control"]
    assert set(dienst) == {"deploy"}  # keine Volumes, kein Netz, keine Sonderrechte
    geraete = dienst["deploy"]["resources"]["reservations"]["devices"]
    assert [geraet["capabilities"] for geraet in geraete] == [["utility"]]


def test_dockerfile_laeuft_nicht_als_root() -> None:
    dockerfile = _ohne_kommentare((REPO / "Dockerfile").read_text(encoding="utf-8"))
    assert re.search(r"^USER 10001:10001$", dockerfile, flags=re.MULTILINE)
    assert "docker.sock" not in dockerfile
    assert "COPY . " not in dockerfile  # nur ausgewählte Ordner, nie .env oder data/


def test_quelltext_spricht_missa_core_nicht_schreibend_an() -> None:
    """Im Backend gibt es keinen Zugriff auf den Docker-Socket und keine Docker-Befehle."""
    for datei in (REPO / "backend" / "src").rglob("*.py"):
        text = datei.read_text(encoding="utf-8")
        assert "docker.sock" not in text, datei
        assert not re.search(r"subprocess\.\w+\(\s*\[?\s*[\"']docker", text), datei


def test_missa_core_wird_nur_mit_einem_lesenden_get_abgefragt() -> None:
    """Der einzige Kontakt zu missa-core ist ein HTTP-GET auf die Health-URL – und der steht an genau einer Stelle."""
    quelle = REPO / "backend" / "src" / "missa_control"
    code = _ohne_kommentare((quelle / "status" / "missa_core.py").read_text(encoding="utf-8"))
    assert code.count("await client.get(self.health_url)") == 1
    for verboten in (".post(", ".put(", ".patch(", ".delete(", ".request(", ".stream(", ".send(", ".head("):
        assert verboten not in code, verboten
    assert "follow_redirects=False" in code  # auch keine Weiterleitung führt woanders hin

    # Die Health-URL kennt sonst nur, wer sie einliest bzw. weiterreicht – niemand sonst fragt damit etwas ab.
    kennen = {
        datei.relative_to(quelle).as_posix()
        for datei in quelle.rglob("*.py")
        if "health_url" in datei.read_text(encoding="utf-8")
    }
    assert kennen == {"config.py", "main.py", "status/missa_core.py", "status/dienst.py"}
    for name in ("config.py", "main.py", "status/dienst.py"):
        text = (quelle / name).read_text(encoding="utf-8")
        assert "httpx" not in text, name

    # In Compose und Skripten taucht missa-core nur als diese eine Einstellung auf.
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")
    assert [
        zeile.strip() for zeile in _ohne_kommentare(compose).splitlines() if "MISSA_CORE" in zeile.upper()
    ] == ["MISSA_CORE_HEALTH_URL: ${MISSA_CORE_HEALTH_URL:-}"]
    for skript in SKRIPTE:
        assert "missa-core" not in _ohne_kommentare(skript.read_text(encoding="utf-8")).lower(), skript.name
        assert "missa_core" not in _ohne_kommentare(skript.read_text(encoding="utf-8")).lower(), skript.name
