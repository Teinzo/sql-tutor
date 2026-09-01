/* =========================================================================
   SQL Tutor - zajedničke pomoćne funkcije
   ========================================================================= */

/**
 * Poziva API i vraća parsirani JSON. Kod greške baca Error s porukom
 * koju je vratio poslužitelj.
 */
async function api(putanja, opcije = {}) {
    const odgovor = await fetch(putanja, {
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        ...opcije,
    });

    if (odgovor.status === 401) {
        window.location.href = '/login';
        throw new Error('Niste prijavljeni.');
    }

    let podaci = null;
    try {
        podaci = await odgovor.json();
    } catch (e) {
        podaci = null;
    }

    if (!odgovor.ok) {
        const poruka = (podaci && (podaci.detail || podaci.message))
            || `Greška ${odgovor.status}`;
        throw new Error(typeof poruka === 'string' ? poruka : JSON.stringify(poruka));
    }

    return podaci;
}

const apiGet  = (putanja) => api(putanja);
const apiPost = (putanja, tijelo) =>
    api(putanja, { method: 'POST', body: JSON.stringify(tijelo || {}) });
const apiDelete = (putanja) => api(putanja, { method: 'DELETE' });

/** Sigurno umeće tekst u HTML (sprječava XSS). */
function esc(vrijednost) {
    if (vrijednost === null || vrijednost === undefined) return '';
    return String(vrijednost)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Prikazuje poruku u elementu zadanog identifikatora. */
function poruka(id, tekst, vrsta = 'info') {
    const el = document.getElementById(id);
    if (!el) return;
    if (!tekst) {
        el.className = 'skriveno';
        el.innerHTML = '';
        return;
    }
    el.className = `poruka poruka-${vrsta}`;
    el.innerHTML = esc(tekst);
}

/** Odjava korisnika. */
async function odjava() {
    try {
        await apiPost('/api/logout');
    } catch (e) {
        /* svejedno preusmjeravamo */
    }
    window.location.href = '/';
}

/** Gradi HTML tablicu iz stupaca i redaka. */
function tablicaHtml(stupci, redci, ukupno) {
    if (!stupci || stupci.length === 0) {
        return '<p class="prigusen sitno">Upit nije vratio stupce.</p>';
    }
    if (!redci || redci.length === 0) {
        return `<div class="tablica-omot"><table><thead><tr>${
            stupci.map((s) => `<th>${esc(s)}</th>`).join('')
        }</tr></thead><tbody><tr><td colspan="${stupci.length}" class="prigusen"
            style="text-align:center">Upit nije vratio nijedan redak.</td></tr>
        </tbody></table></div>`;
    }

    const glava = stupci.map((s) => `<th>${esc(s)}</th>`).join('');
    const tijelo = redci.map((red) =>
        `<tr>${red.map((v) => (v === null
            ? '<td class="null-vrijednost">NULL</td>'
            : `<td>${esc(v)}</td>`)).join('')}</tr>`
    ).join('');

    let podnozje = '';
    if (ukupno !== undefined && ukupno > redci.length) {
        podnozje = `<p class="prigusen sitno" style="margin-top:8px">
            Prikazano prvih ${redci.length} od ukupno ${ukupno} redaka.</p>`;
    }

    return `<div class="tablica-omot"><table>
        <thead><tr>${glava}</tr></thead><tbody>${tijelo}</tbody>
    </table></div>${podnozje}`;
}

/** Vraća CSS klasu oznake prema razini težine. */
function oznakaTezine(tezina) {
    const mapa = {
        'početnik': 'oznaka-zelena',
        'pocetnik': 'oznaka-zelena',
        'srednji': 'oznaka-zuta',
        'napredni': 'oznaka-crvena',
    };
    return mapa[(tezina || '').toLowerCase()] || 'oznaka-siva';
}

/** Formatira ISO datum u hrvatski oblik. */
function datumHr(iso) {
    if (!iso) return '-';
    const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('hr-HR', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

/** Pretvara prijelome redaka u <br> uz prethodno bijeg specijalnih znakova. */
function tekstUHtml(tekst) {
    return esc(tekst).replace(/\n/g, '<br>');
}

/** Omogućuje umetanje tabulatora u textarea umjesto skoka na sljedeći element. */
function omoguciTabUEditoru(textarea) {
    if (!textarea) return;
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const pocetak = textarea.selectionStart;
            const kraj = textarea.selectionEnd;
            textarea.value = textarea.value.substring(0, pocetak) + '    '
                + textarea.value.substring(kraj);
            textarea.selectionStart = textarea.selectionEnd = pocetak + 4;
        }
    });
}

/** Označava aktivnu poveznicu u navigaciji. */
document.addEventListener('DOMContentLoaded', () => {
    const putanja = window.location.pathname;
    document.querySelectorAll('.nav-links a').forEach((a) => {
        const href = a.getAttribute('href');
        if (href === putanja || (href !== '/' && putanja.startsWith(href))) {
            a.classList.add('aktivan');
        }
    });
});
