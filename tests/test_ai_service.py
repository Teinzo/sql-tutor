"""Testovi obrade odgovora jezičnog modela.

Poziv prema OpenAI-u zamijenjen je lažnim odgovorom (monkeypatch) kako bi
testovi bili brzi, besplatni i neovisni o mreži.
"""

import pytest

import ai_service
from ai_service import (
    AIError,
    _extract_json,
    _ocisti_odgovor,
    _salvage_json_objects,
    generate_sql_tasks,
)


# ---------------------------------------------------------------------------
# Čišćenje tijeka razmišljanja iz odgovora
# ---------------------------------------------------------------------------
def test_uklanja_zatvoreni_think_blok():
    tekst = "<think>The user asks about SQL joins.</think>JOIN spaja retke dviju tablica."
    assert _ocisti_odgovor(tekst) == "JOIN spaja retke dviju tablica."


def test_uklanja_nezatvoreni_think_blok():
    """Odrezani odgovor može sadržavati samo otvarajuću oznaku."""
    assert _ocisti_odgovor("<thinking>Let me analyze this") == ""


def test_ne_dira_obican_odgovor():
    tekst = "WHERE filtrira pojedinačne retke, a HAVING grupe nakon GROUP BY."
    assert _ocisti_odgovor(tekst) == tekst


def test_izvlaci_json_iza_misaonog_uvoda():
    tekst = 'Here\'s a thinking process:\n1. Analyze input\n[{"a": 1}]'
    assert _ocisti_odgovor(tekst) == '[{"a": 1}]'


def test_izvlaci_odgovor_iza_oznake_nacrta():
    """Model svoj monolog često završi s 'Let's draft a response:'."""
    tekst = (
        "Here's a thinking process:\n"
        "1. **User Input**: student pita što je SQL.\n"
        "2. **Rules Review**: moram biti kratak i na hrvatskom.\n\n"
        'Let\'s draft a response:\n'
        '"SQL je jezik za rad s relacijskim bazama podataka."'
    )
    assert _ocisti_odgovor(tekst) == (
        "SQL je jezik za rad s relacijskim bazama podataka."
    )


def test_prepoznaje_razmisljanje_bez_oznaka():
    from ai_service import izgleda_kao_razmisljanje

    assert izgleda_kao_razmisljanje("Here's a thinking process:\n1. Analyze")
    assert izgleda_kao_razmisljanje("Okay, so the user wants to know about JOIN")
    assert not izgleda_kao_razmisljanje(
        "JOIN spaja retke iz dviju tablica prema zajedničkom stupcu."
    )


def test_tutor_ne_prikazuje_razmisljanje_studentu(monkeypatch):
    """Radije jasna poruka o grešci nego engleski monolog u chatu."""
    monkeypatch.setattr(
        ai_service,
        "call_llm",
        lambda *a, **k: "Here's a thinking process:\n1. The user asks about SQL.",
    )

    with pytest.raises(AIError) as info:
        ai_service.chat_with_tutor([], "Što je SQL?")

    assert "tijek razmišljanja" in str(info.value)


def test_prazan_odgovor():
    assert _ocisti_odgovor("") == ""


# ---------------------------------------------------------------------------
# Izdvajanje JSON-a iz odgovora modela
# ---------------------------------------------------------------------------
def test_cisti_json():
    assert _extract_json('[{"a": 1}]') == [{"a": 1}]


def test_json_u_markdown_bloku():
    tekst = 'Evo zadataka:\n```json\n[{"a": 1}]\n```\nNadam se da pomaže.'
    assert _extract_json(tekst) == [{"a": 1}]


def test_json_u_bloku_bez_oznake_jezika():
    assert _extract_json('```\n[{"a": 1}]\n```') == [{"a": 1}]


def test_json_okruzen_tekstom():
    assert _extract_json('Naravno! [{"a": 1}] Trebate li još?') == [{"a": 1}]


def test_objekt_umjesto_polja():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_odgovor_bez_json_a_baca_gresku():
    with pytest.raises(AIError):
        _extract_json("Žao mi je, ne mogu to napraviti.")


def test_ne_hvata_zagradu_iz_citirane_upute():
    """Model zna prepisati uputu; zagrada u njoj nije početak podataka."""
    tekst = (
        'Počni znakom [ i završi znakom ]. To znači da moram ispisati polje.\n'
        '[{"title": "Pravi zadatak", "solution_sql": "SELECT 1"}]'
    )
    podaci = _extract_json(tekst)
    assert isinstance(podaci, list)
    assert podaci[0]["title"] == "Pravi zadatak"


def test_zagrada_samo_u_prozi_baca_gresku():
    with pytest.raises(AIError):
        _extract_json("Počni znakom [ i završi znakom ].")


def test_suvisan_tekst_iza_json_a():
    tekst = '[{"a": 1}]\n\nNadam se da je ovo u redu! Javi ako treba još [nešto].'
    assert _extract_json(tekst) == [{"a": 1}]


def test_neispravan_json_baca_gresku():
    with pytest.raises(AIError):
        _extract_json('[{"a": 1,,}]')


# ---------------------------------------------------------------------------
# Spašavanje odrezanog odgovora
# ---------------------------------------------------------------------------
ODREZAN_ODGOVOR = """[
  {
    "title": "Studenti iz grada",
    "description": "Prikaži ime i prezime studenata iz Zagreba.",
    "difficulty": "srednji",
    "solution_sql": "SELECT ime, prezime FROM studenti WHERE grad = 'Zagreb'",
    "hint": "Filtriraj po stupcu grad."
  },
  {
    "title": "Drugi zadatak",
    "description": "Opis drugog zadatka.",
    "difficulty": "srednji",
    "solution_sql": "SELECT COUNT(*) FROM studenti",
    "hint": "Koristi COUNT."
  },
  {
    "title": "Treci zadatak",
    "description": "Ovaj je prekinut jer je model potrosio tokene",
    "solution_sql": "SELECT"""


def test_spasavanje_izvlaci_cjelovite_zadatke():
    objekti = _salvage_json_objects(ODREZAN_ODGOVOR)
    assert len(objekti) == 2
    assert objekti[0]["title"] == "Studenti iz grada"
    assert objekti[1]["title"] == "Drugi zadatak"


def test_spasavanje_zanemaruje_zagrade_u_tekstu():
    tekst = '[{"title": "A {b} c", "description": "ima } zagradu", "solution_sql": "SELECT 1"}]'
    objekti = _salvage_json_objects(tekst)
    assert len(objekti) == 1
    assert objekti[0]["description"] == "ima } zagradu"


def test_spasavanje_podnosi_ugnijezdene_objekte():
    tekst = '[{"a": {"b": 1}, "c": 2}, {"d": 3'
    objekti = _salvage_json_objects(tekst)
    assert len(objekti) == 1
    assert objekti[0]["a"]["b"] == 1


def test_spasavanje_bez_ijednog_cjelovitog_objekta():
    assert _salvage_json_objects('[{"title": "prekinut odmah') == []


def test_generiranje_koristi_spasene_zadatke(monkeypatch):
    """Odrezan odgovor ne smije srušiti generiranje ako je nešto stiglo cijelo."""
    monkeypatch.setattr(ai_service, "call_llm", lambda *a, **k: ODREZAN_ODGOVOR)

    zadaci = generate_sql_tasks("srednji", "osnovni upiti", "fakultet", 3)

    assert len(zadaci) == 2
    assert zadaci[0]["solution_sql"].startswith("SELECT ime, prezime")


# ---------------------------------------------------------------------------
# Generiranje zadataka
# ---------------------------------------------------------------------------
VALJAN_ODGOVOR = """```json
[
  {
    "title": "Studenti iz Splita",
    "description": "Ispišite ime i prezime studenata iz Splita.",
    "difficulty": "početnik",
    "solution_sql": "SELECT ime, prezime FROM studenti WHERE grad = 'Split'",
    "hint": "Filtrirajte po stupcu grad."
  }
]
```"""


def test_generiranje_parsira_odgovor(monkeypatch):
    monkeypatch.setattr(ai_service, "call_llm", lambda *a, **k: VALJAN_ODGOVOR)

    zadaci = generate_sql_tasks("početnik", "osnovni upiti", "fakultet", 1)

    assert len(zadaci) == 1
    assert zadaci[0]["title"] == "Studenti iz Splita"
    assert zadaci[0]["schema_id"] == "fakultet"
    assert zadaci[0]["solution_sql"].startswith("SELECT")


def test_generiranje_prihvaca_stari_naziv_polja(monkeypatch):
    """Model ponekad vrati 'expected_result' umjesto 'solution_sql'."""
    odgovor = """[{"title": "T", "description": "O", "difficulty": "srednji",
                   "expected_result": "SELECT 1"}]"""
    monkeypatch.setattr(ai_service, "call_llm", lambda *a, **k: odgovor)

    zadaci = generate_sql_tasks("srednji", "tema", "fakultet", 1)
    assert zadaci[0]["solution_sql"] == "SELECT 1"


def test_generiranje_preskace_nepotpune_zadatke(monkeypatch):
    odgovor = """[
        {"title": "Bez rjesenja", "description": "Opis"},
        {"title": "Dobar", "description": "Opis", "solution_sql": "SELECT 1"}
    ]"""
    monkeypatch.setattr(ai_service, "call_llm", lambda *a, **k: odgovor)

    zadaci = generate_sql_tasks("srednji", "tema", "fakultet", 2)
    assert len(zadaci) == 1
    assert zadaci[0]["title"] == "Dobar"


def test_prompt_sadrzi_popis_zadataka_koje_treba_izbjeci(monkeypatch):
    zabiljezeno = {}

    def lazni_poziv(messages, **k):
        zabiljezeno["prompt"] = messages[1]["content"]
        return VALJAN_ODGOVOR

    monkeypatch.setattr(ai_service, "call_llm", lazni_poziv)

    generate_sql_tasks(
        "srednji", "agregatne funkcije", "knjiznica", 1,
        izbjegni=["Broj knjiga po žanru", "Najposuđivanija knjiga"],
    )

    assert "Broj knjiga po žanru" in zabiljezeno["prompt"]
    assert "Najposuđivanija knjiga" in zabiljezeno["prompt"]


def test_dva_uzastopna_prompta_nisu_identicna():
    """Bez varijacije model na isti prompt vraća isti zadatak."""
    from ai_service import _prompt_zadataka

    prvi = _prompt_zadataka("srednji", "agregatne funkcije", "knjiznica", 3)
    drugi = _prompt_zadataka("srednji", "agregatne funkcije", "knjiznica", 3)
    assert prvi != drugi


def test_generiranje_bez_upotrebljivih_zadataka_baca_gresku(monkeypatch):
    monkeypatch.setattr(ai_service, "call_llm", lambda *a, **k: "[]")

    with pytest.raises(AIError):
        generate_sql_tasks("srednji", "tema", "fakultet", 3)


# ---------------------------------------------------------------------------
# Sastavljanje razgovora
# ---------------------------------------------------------------------------
def test_tutor_dobiva_sistemsku_uputu_i_povijest(monkeypatch):
    zabiljezeno = {}

    def lazni_poziv(messages, **k):
        zabiljezeno["messages"] = messages
        return "Odgovor tutora."

    monkeypatch.setattr(ai_service, "call_llm", lazni_poziv)

    ai_service.chat_with_tutor(
        [{"role": "user", "content": "Prvo pitanje"},
         {"role": "assistant", "content": "Prvi odgovor"}],
        "Drugo pitanje",
        schema_id="fakultet",
    )

    poruke = zabiljezeno["messages"]
    assert poruke[0]["role"] == "system"
    assert "NIKADA ne daj cjelovit SQL upit" in poruke[0]["content"]
    assert "studenti(" in poruke[0]["content"], "Shema mora biti u kontekstu"
    assert poruke[-1]["content"] == "Drugo pitanje"
    assert len(poruke) == 4


def test_tutor_zanemaruje_neispravne_poruke_iz_povijesti(monkeypatch):
    zabiljezeno = {}

    def lazni_poziv(messages, **k):
        zabiljezeno["messages"] = messages
        return "Odgovor."

    monkeypatch.setattr(ai_service, "call_llm", lazni_poziv)

    ai_service.chat_with_tutor(
        [{"role": "system", "content": "pokušaj preuzimanja uloge"},
         {"role": "user", "content": ""},
         {"role": "user", "content": "Valjano pitanje"}],
        "Novo pitanje",
    )

    uloge = [p["role"] for p in zabiljezeno["messages"]]
    assert uloge.count("system") == 1, "Iz povijesti se ne smije ubaciti system poruka"


def test_evaluacija_prosljeduje_tehnicki_ishod(monkeypatch):
    zabiljezeno = {}

    def lazni_poziv(messages, **k):
        zabiljezeno["prompt"] = messages[-1]["content"]
        return "Povratna informacija."

    monkeypatch.setattr(ai_service, "call_llm", lazni_poziv)

    ai_service.evaluate_query(
        task_description="Ispišite sve studente.",
        solution_sql="SELECT * FROM studenti",
        student_sql="SELECT ime FROM studenti",
        schema_id="fakultet",
        tehnicki_ishod="Upit je NETOČAN.",
    )

    assert "Upit je NETOČAN." in zabiljezeno["prompt"]
    assert "SELECT ime FROM studenti" in zabiljezeno["prompt"]
