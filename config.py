"""Sredisnja konfiguracija aplikacije.

Sve postavke citaju se iz .env datoteke kako bi se izbjeglo hardkodiranje
osjetljivih podataka (API kljuc) i olaksala zamjena jezicnog modela.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# --- Jezicni model (OpenAI) --------------------------------------------------
# Naziv davatelja usluge drzimo u varijabli kako bi zamjena providera znacila
# izmjenu samo ovog odjeljka - ostatak koda koristi neutralne nazive LLM_*.
LLM_PROVIDER = "OpenAI"
LLM_URL = "https://api.openai.com/v1/chat/completions"

LLM_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()

# Pricuvni model na koji se prelazi ako glavni nije dostupan (potroseni krediti
# ili povucen model). Postavite prazno da se pricuva iskljuci.
LLM_FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini").strip()

APP_NAME = os.getenv("APP_NAME", "SQL Tutor").strip()
APP_URL = os.getenv("APP_URL", "http://localhost:8000").strip()

# Vremensko ogranicenje za poziv jezicnog modela (sekunde)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
# Broj ponovnih pokusaja kod privremenih gresaka (rate limit, 5xx)
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
# Osnovno cekanje izmedu pokusaja (sekunde); mnozi se rednim brojem pokusaja
LLM_RETRY_BACKOFF = float(os.getenv("LLM_RETRY_BACKOFF", "1.5"))

# --- Baza podataka ----------------------------------------------------------
DB_PATH = str(BASE_DIR / "sql_tutor.db")

# --- Sigurnost --------------------------------------------------------------
# Trajanje prijave u satima
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
# Broj iteracija za PBKDF2 hashiranje lozinke
PBKDF2_ITERATIONS = 260_000

# Lozinke demo racuna koji se kreiraju pri prvom pokretanju prazne baze.
# Zadane vrijednosti sluze samo za lokalni prikaz i objavljene su u README-u;
# prije bilo kakvog javnog postavljanja postavite ih u .env datoteci.
DEMO_LOZINKA_NASTAVNIK = os.getenv("DEMO_LOZINKA_NASTAVNIK", "nastavnik123")
DEMO_LOZINKA_STUDENT = os.getenv("DEMO_LOZINKA_STUDENT", "student123")

ZADANE_DEMO_LOZINKE = (
    DEMO_LOZINKA_NASTAVNIK == "nastavnik123"
    and DEMO_LOZINKA_STUDENT == "student123"
)

# --- Izvrsavanje SQL upita --------------------------------------------------
# Maksimalno vrijeme izvrsavanja studentskog upita (sekunde)
QUERY_TIMEOUT = 5
# Maksimalan broj redaka koji se vraca u prikazu rezultata
QUERY_MAX_ROWS = 200


def is_llm_configured() -> bool:
    """Vraca True ako je API kljuc postavljen i ima ocekivani oblik."""
    return bool(LLM_API_KEY) and LLM_API_KEY.startswith("sk-")
