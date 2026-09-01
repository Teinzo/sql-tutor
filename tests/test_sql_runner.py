"""Testovi sigurnosne provjere i ocjenjivanja SQL upita.

Ovi testovi ne zahtijevaju pristup jezičnom modelu jer provjeravaju
deterministički dio sustava.
"""

import pytest

from sql_runner import QueryError, grade_query, run_query, validate_query


# ---------------------------------------------------------------------------
# Sigurnosna provjera upita
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "upit",
    [
        "SELECT * FROM studenti",
        "select ime, prezime from studenti where dob > 20",
        "  SELECT COUNT(*) FROM studenti  ",
        "WITH x AS (SELECT * FROM studenti) SELECT * FROM x",
        "SELECT * FROM studenti WHERE grad = 'Zagreb';",
    ],
)
def test_dopusteni_upiti_prolaze(upit):
    validate_query(upit)  # ne smije baciti iznimku


@pytest.mark.parametrize(
    "upit",
    [
        "DROP TABLE studenti",
        "DELETE FROM studenti",
        "UPDATE studenti SET dob = 99",
        "INSERT INTO studenti VALUES (99, 'X', 'Y', 20, 1, 1, 'Z')",
        "CREATE TABLE zlo (id INT)",
        "ATTACH DATABASE 'druga.db' AS d",
        "PRAGMA table_info(studenti)",
        "SELECT * FROM studenti; DROP TABLE studenti",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('zlo.so')",
    ],
)
def test_zabranjeni_upiti_padaju(upit):
    with pytest.raises(QueryError):
        validate_query(upit)


def test_komentar_ne_moze_sakriti_zabranjenu_naredbu():
    with pytest.raises(QueryError):
        validate_query("SELECT 1 -- bezopasno\n; DROP TABLE studenti")


def test_zabranjena_rijec_u_tekstu_je_dopustena():
    """Riječ 'delete' unutar tekstualnog literala nije naredba."""
    validate_query("SELECT ime FROM studenti WHERE grad = 'delete'")


def test_prazan_upit_pada():
    with pytest.raises(QueryError):
        validate_query("   ")


# ---------------------------------------------------------------------------
# Izvršavanje upita
# ---------------------------------------------------------------------------
def test_izvrsavanje_vraca_stupce_i_retke():
    stupci, redci = run_query("fakultet", "SELECT ime, prezime FROM studenti")
    assert stupci == ["ime", "prezime"]
    assert len(redci) == 10


def test_nepostojeca_tablica_daje_razumljivu_poruku():
    with pytest.raises(QueryError) as info:
        run_query("fakultet", "SELECT * FROM nepostojeca")
    assert "ne postoji" in str(info.value)


def test_nepostojeci_stupac_daje_razumljivu_poruku():
    with pytest.raises(QueryError) as info:
        run_query("fakultet", "SELECT nepostojeci FROM studenti")
    assert "ne postoji" in str(info.value)


def test_sve_sheme_se_mogu_izgraditi():
    for shema, tablica in [
        ("fakultet", "studenti"),
        ("webshop", "proizvodi"),
        ("knjiznica", "knjige"),
    ]:
        _, redci = run_query(shema, f"SELECT COUNT(*) FROM {tablica}")
        assert redci[0][0] > 0


def test_glavna_baza_nije_dostupna_iz_sandboxa():
    """Tablice aplikacije (users, tasks) ne smiju biti vidljive studentu."""
    with pytest.raises(QueryError):
        run_query("fakultet", "SELECT * FROM users")


# ---------------------------------------------------------------------------
# Ocjenjivanje
# ---------------------------------------------------------------------------
RJESENJE = "SELECT ime, prezime FROM studenti ORDER BY prezime"


def test_identican_upit_je_tocan():
    r = grade_query("fakultet", RJESENJE, RJESENJE)
    assert r["is_correct"] is True
    assert r["status"] == "tocno"


def test_drugacije_napisan_ekvivalentan_upit_je_tocan():
    upit = "select ime, prezime from studenti order by prezime asc"
    r = grade_query("fakultet", upit, RJESENJE)
    assert r["is_correct"] is True


def test_pogresan_redoslijed_prepoznat_je_kao_takav():
    upit = "SELECT ime, prezime FROM studenti ORDER BY ime"
    r = grade_query("fakultet", upit, RJESENJE)
    assert r["is_correct"] is False
    assert "redoslijed" in r["poruka"].lower()


def test_pogresan_broj_stupaca():
    upit = "SELECT ime FROM studenti ORDER BY prezime"
    r = grade_query("fakultet", upit, RJESENJE)
    assert r["is_correct"] is False
    assert "stup" in r["poruka"]


def test_pogresan_broj_redaka():
    upit = "SELECT ime, prezime FROM studenti WHERE dob > 100 ORDER BY prezime"
    r = grade_query("fakultet", upit, RJESENJE)
    assert r["is_correct"] is False
    assert r["broj_redaka"] == 0
    assert r["ocekivano"] == 10


def test_neispravan_upit_vraca_status_greska():
    r = grade_query("fakultet", "SELECT FROM WHERE", RJESENJE)
    assert r["status"] == "greska"
    assert r["is_correct"] is False


def test_zabranjeni_upit_pri_ocjenjivanju_vraca_gresku():
    r = grade_query("fakultet", "DROP TABLE studenti", RJESENJE)
    assert r["status"] == "greska"
    assert r["is_correct"] is False


def test_null_vrijednosti_se_ispravno_usporeduju():
    upit = "SELECT naslov FROM knjige WHERE autor_id IS NULL"
    r = grade_query("knjiznica", upit, upit)
    assert r["is_correct"] is True
    assert r["broj_redaka"] == 1


def test_agregacija_s_group_by():
    rjesenje = (
        "SELECT s.naziv, COUNT(st.id) AS broj "
        "FROM smjerovi s JOIN studenti st ON st.smjer_id = s.id "
        "GROUP BY s.naziv ORDER BY broj DESC"
    )
    r = grade_query("fakultet", rjesenje, rjesenje)
    assert r["is_correct"] is True
    assert r["broj_redaka"] == 4
