"""Zajedničke postavke za testove.

Testovi se izvode nad privremenom bazom kako se ne bi dirala razvojna baza
`sql_tutor.db`. Putanja se mijenja prije uvoza modula koji je koriste.
"""

import sys
import tempfile
from pathlib import Path

# Korijen projekta mora biti na putanji za uvoz modula.
KORIJEN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KORIJEN))

import config  # noqa: E402

_privremena = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_privremena.close()
config.DB_PATH = _privremena.name

import database  # noqa: E402

database.DB_PATH = _privremena.name

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def pripremi_bazu():
    """Kreira shemu i početne podatke jednom za cijelu sesiju testiranja."""
    database.init_db()
    yield
    Path(_privremena.name).unlink(missing_ok=True)


@pytest.fixture()
def klijent(pripremi_bazu):
    """Neprijavljeni HTTP klijent. Svaki test dobiva svježe kolačiće."""
    from main import app

    with TestClient(app) as c:
        yield c


def _prijavi(klijent, korisnik: str, lozinka: str):
    odgovor = klijent.post(
        "/api/login", json={"username": korisnik, "password": lozinka}
    )
    assert odgovor.status_code == 200, odgovor.text
    return klijent


@pytest.fixture()
def student(klijent):
    """Klijent prijavljen kao demo student."""
    return _prijavi(klijent, "student", "student123")


@pytest.fixture()
def nastavnik(klijent):
    """Klijent prijavljen kao demo nastavnik."""
    return _prijavi(klijent, "nastavnik", "nastavnik123")
