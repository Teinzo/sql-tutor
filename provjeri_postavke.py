"""Dijagnostička skripta za provjeru konfiguracije prije pokretanja aplikacije.

Pokretanje:
    python provjeri_postavke.py

Provjerava:
  1. je li API ključ postavljen,
  2. je li odabrani model dostupan računu,
  3. odgovara li model na probni upit,
  4. mogu li se izgraditi sve vježbovne sheme.
"""

import sys

import requests

from config import (
    LLM_API_KEY,
    LLM_MODEL,
    LLM_PROVIDER,
    is_llm_configured,
)

MODELI_URL = "https://api.openai.com/v1/models"

OK = "  [OK] "
GRESKA = "  [!!] "
INFO = "  [--] "


def provjeri_kljuc() -> bool:
    print("\n1. API ključ")
    if not LLM_API_KEY:
        print(GRESKA + "OPENAI_API_KEY nije postavljen u .env datoteci.")
        return False
    if not LLM_API_KEY.startswith("sk-"):
        print(
            GRESKA + f"Ključ ne izgleda kao {LLM_PROVIDER} ključ "
            "(očekuje se 'sk-...')."
        )
        return False
    print(OK + f"Ključ je postavljen ({LLM_API_KEY[:11]}…).")
    return True


def provjeri_model() -> bool:
    """Provjerava je li odabrani model dostupan ovom računu.

    OpenAI ne nudi javni endpoint za stanje kredita, pa se potrošeni krediti
    otkrivaju tek u koraku 3 (probni poziv vraća 429 s 'insufficient_quota').
    """
    print(f"\n2. Dostupnost modela '{LLM_MODEL}'")
    try:
        odgovor = requests.get(
            MODELI_URL,
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        print(GRESKA + f"Popis modela nije dohvatljiv: {exc}")
        return False

    if odgovor.status_code == 401:
        print(GRESKA + "Ključ je odbijen (401). Provjerite jeste li kopirali cijeli.")
        return False

    if odgovor.status_code != 200:
        print(GRESKA + f"{LLM_PROVIDER} je vratio status {odgovor.status_code}.")
        return False

    modeli = [m["id"] for m in odgovor.json().get("data", [])]

    if LLM_MODEL in modeli:
        print(OK + "Model postoji i dostupan je.")
        return True

    print(GRESKA + "Model NIJE pronađen na popisu dostupnih modela.")
    alternative = sorted(m for m in modeli if m.startswith("gpt-"))[:8]
    if alternative:
        print(INFO + "Alternative koje možete upisati u .env:")
        for m in alternative:
            print(f"        OPENAI_MODEL={m}")
    return False


def probni_upit() -> bool:
    print("\n3. Probni poziv modela")
    from ai_service import AIError, call_llm

    try:
        odgovor = call_llm(
            [{"role": "user", "content": "Odgovori jednom rečenicom: što je SQL?"}],
            # Modeli koji interno zaključuju troše dio budžeta na razmišljanje,
            # pa premali max_tokens vraća prazan odgovor.
            max_tokens=300,
        )
    except AIError as exc:
        print(GRESKA + str(exc))
        return False

    print(OK + f"Model je odgovorio: {odgovor[:100]}")
    return True


def probno_generiranje() -> bool:
    """Najosjetljivija AI funkcionalnost - traži od modela strogi JSON format."""
    print("\n4. Probno generiranje zadataka")
    from ai_service import AIError, generate_sql_tasks
    from sql_runner import QueryError, run_query

    try:
        zadaci = generate_sql_tasks("početnik", "osnovni upiti", "fakultet", 2)
    except AIError as exc:
        print(GRESKA + str(exc))
        print(
            INFO + "Slabiji modeli često ne poštuju JSON format. "
            "Pokušajte s kvalitetnijim modelom u .env:"
        )
        print("        OPENAI_MODEL=gpt-5.6-terra")
        return False

    if len(zadaci) < 2:
        print(
            INFO + f"Model je vratio samo {len(zadaci)} od 2 tražena zadatka — "
            "vjerojatno reže izlaz. Kvalitetniji model vraća sve."
        )
    else:
        print(OK + f"Model je vratio sve tražene zadatke ({len(zadaci)}).")

    izvrsivih = 0
    for zadatak in zadaci:
        try:
            run_query(zadatak["schema_id"], zadatak["solution_sql"], validate=False)
            izvrsivih += 1
            print(OK + f"'{zadatak['title']}' — rješenje se izvršava.")
        except QueryError as exc:
            print(GRESKA + f"'{zadatak['title']}' — rješenje ne radi: {exc}")

    if izvrsivih == 0:
        print(
            GRESKA + "Nijedno generirano rješenje nije izvršivo. "
            "Model ne razumije shemu dovoljno dobro — promijenite model."
        )
        return False

    return True


def provjeri_sheme() -> bool:
    print("\n0. Vježbovne sheme baza")
    from schemas import SCHEMAS
    from sql_runner import QueryError, run_query

    sve_ok = True
    for schema_id, shema in SCHEMAS.items():
        try:
            for tablica in shema["tablice"]:
                _, redci = run_query(
                    schema_id, f"SELECT COUNT(*) FROM {tablica}", validate=False
                )
            print(OK + f"{shema['naziv']}: {len(shema['tablice'])} tablica.")
        except QueryError as exc:
            print(GRESKA + f"{shema['naziv']}: {exc}")
            sve_ok = False
    return sve_ok


def main() -> int:
    print("=" * 62)
    print(" SQL Tutor — provjera postavki")
    print("=" * 62)

    sheme_ok = provjeri_sheme()

    if not is_llm_configured():
        provjeri_kljuc()
        print(
            "\nAplikacija se može pokrenuti, ali AI funkcionalnosti neće raditi.\n"
            "Dodajte OPENAI_API_KEY u .env datoteku."
        )
        return 1

    kljuc_ok = provjeri_kljuc()
    model_ok = provjeri_model() if kljuc_ok else False
    poziv_ok = probni_upit() if model_ok else False
    gen_ok = probno_generiranje() if poziv_ok else False

    print("\n" + "=" * 62)
    if sheme_ok and kljuc_ok and model_ok and poziv_ok and gen_ok:
        print(" Sve je spremno. Pokrenite:  uvicorn main:app --reload")
        return 0

    print(" Neke provjere nisu prošle — pogledajte poruke iznad.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
