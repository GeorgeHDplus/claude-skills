#!/usr/bin/env bash
# validate-skill-structure.sh — prüft ein einzelnes Skill-Paket (SKILL.md)
# gegen die Struktur-Konventionen dieses Repos.
#
# Standalone: reine Standard-Shell-Werkzeuge (bash/awk/grep/sed/wc), keine
# externen Skripte oder Netzwerkzugriffe. Ein Skill-Ordner kann irgendwohin
# kopiert und hier geprüft werden.
#
# Ergänzt (ersetzt nicht) die repo-weiten Python-Tools:
#   scripts/audit_skills.py          — läuft über ALLE SKILL.md und aggregiert
#   engineering/write-a-skill/scripts/skill_review_checklist_runner.py
#
# Verwendung:
#   scripts/validate-skill-structure.sh <skill-verzeichnis>
#
# Exit 0 = keine FAIL-Befunde (WARN erlaubt)
# Exit 1 = mindestens ein FAIL (Struktur verletzt) oder Aufruf-Fehler

set -euo pipefail

FAILS=0
WARNS=0

fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }
warn() { echo "WARN: $*" >&2; WARNS=$((WARNS + 1)); }
ok()   { echo "OK:   $*"; }

# --- Aufruf prüfen ---------------------------------------------------------
if [[ $# -ne 1 ]]; then
    echo "Verwendung: $0 <skill-verzeichnis>" >&2
    exit 1
fi

SKILL_DIR="${1%/}"
SKILL_MD="$SKILL_DIR/SKILL.md"

if [[ ! -d "$SKILL_DIR" ]]; then
    echo "FAIL: Verzeichnis nicht gefunden: $SKILL_DIR" >&2
    exit 1
fi
if [[ ! -f "$SKILL_MD" ]]; then
    echo "FAIL: Keine SKILL.md in $SKILL_DIR" >&2
    exit 1
fi

echo "=== Prüfe $SKILL_MD ==="

CONTENT="$(cat "$SKILL_MD")"

# --- 1. Frontmatter-Grenzen ------------------------------------------------
# Erste Zeile muss '---' sein, und es muss eine zweite '---' geben.
FIRST_LINE="$(head -n1 "$SKILL_MD")"
DELIM_COUNT="$(grep -c '^---[[:space:]]*$' "$SKILL_MD" || true)"

if [[ "$FIRST_LINE" != "---" ]]; then
    fail "SKILL.md beginnt nicht mit YAML-Frontmatter ('---' in Zeile 1)"
elif [[ "$DELIM_COUNT" -lt 2 ]]; then
    fail "YAML-Frontmatter nicht geschlossen (zweites '---' fehlt)"
else
    ok "Frontmatter-Grenzen vorhanden"
fi

# Frontmatter (zwischen den ersten beiden '---') und Body (danach) extrahieren.
FRONTMATTER="$(awk '/^---[[:space:]]*$/{n++; next} n==1{print} n>=2{exit}' "$SKILL_MD")"
BODY="$(awk '/^---[[:space:]]*$/{n++; next} n>=2{print}' "$SKILL_MD")"

# --- 2. name ---------------------------------------------------------------
NAME_LINE="$(printf '%s\n' "$FRONTMATTER" | grep -m1 '^name:' || true)"
if [[ -z "$NAME_LINE" ]]; then
    fail "Frontmatter-Feld 'name' fehlt"
else
    NAME_VAL="$(printf '%s' "$NAME_LINE" | sed 's/^name:[[:space:]]*//; s/^["'\'']//; s/["'\'']$//')"
    if [[ -z "$NAME_VAL" ]]; then
        fail "'name' ist leer"
    elif ! printf '%s' "$NAME_VAL" | grep -qE '^[a-z0-9]+(-[a-z0-9]+)*$'; then
        warn "'name' ist nicht kebab-case (nur a-z, 0-9, Bindestriche): '$NAME_VAL'"
    else
        ok "name = '$NAME_VAL'"
    fi
fi

# --- 3. description --------------------------------------------------------
DESC_LINE="$(printf '%s\n' "$FRONTMATTER" | grep -m1 '^description:' || true)"
if [[ -z "$DESC_LINE" ]]; then
    fail "Frontmatter-Feld 'description' fehlt"
else
    DESC_VAL="$(printf '%s' "$DESC_LINE" | sed 's/^description:[[:space:]]*//; s/^["'\'']//; s/["'\'']$//')"
    DESC_LEN="${#DESC_VAL}"
    if [[ -z "$DESC_VAL" ]]; then
        fail "'description' ist leer"
    else
        # Längen-Limit der Skill-Spezifikation: 1024 Zeichen.
        if [[ "$DESC_LEN" -gt 1024 ]]; then
            fail "'description' ist $DESC_LEN Zeichen lang (Limit 1024)"
        else
            ok "description-Länge = $DESC_LEN (Limit 1024)"
        fi
        # Platzhalter-Beschreibung (nur der Skill-Name) erkennen — häufiger Altlast-Fehler.
        if [[ -n "${NAME_VAL:-}" ]] && [[ "$DESC_VAL" == "$NAME_VAL" ]]; then
            fail "'description' ist nur der Skill-Name — beschreibe, was der Skill leistet UND wann er triggert"
        fi
        # Trigger-Formulierung (Repo-Konvention; EN + DE). Fehlt sie -> WARN.
        TRIGGER_RE='Use (when|before|during|after|while)|Invoke (before|after)|Apply when|Run (when|before)|Verwenden? (wenn|vor|während|nach|Sie)|Nutze[n]? (wenn|bei|vor)|Trigger (bei|when|for)|getriggert|wann sie'
        if printf '%s' "$DESC_VAL" | grep -qiE "$TRIGGER_RE"; then
            ok "description nennt einen Trigger ('wann')"
        else
            warn "description nennt keinen erkennbaren Trigger ('Use when …' / 'Verwenden wenn …' / 'Trigger bei …')"
        fi
    fi
fi

# --- 4. Body-H1 ------------------------------------------------------------
# Der Body braucht eine H1-Überschrift ('# …'). Ein fehlendes H1 hat das
# Repo-Test-Setup schon einmal spät gefangen — deshalb hier als harter Check.
if printf '%s\n' "$BODY" | grep -qE '^#[[:space:]]+\S'; then
    ok "Body enthält eine H1-Überschrift"
else
    fail "Body enthält keine H1-Überschrift ('# Titel')"
fi

# --- 5. Zeilen-Limit (weich) ----------------------------------------------
LINE_COUNT="$(printf '%s\n' "$CONTENT" | wc -l | tr -d ' ')"
if [[ "$LINE_COUNT" -gt 500 ]]; then
    warn "SKILL.md hat $LINE_COUNT Zeilen (Richtwert < 500) — lange Inhalte nach references/ auslagern"
else
    ok "Zeilenzahl = $LINE_COUNT (Richtwert < 500)"
fi

# --- 6. Keine Platzhalter im Body -----------------------------------------
# Marker als Großbuchstaben-GANZWÖRTER (case-sensitive), damit legitime Wörter
# wie "todos" oder "Fixme-Anleitung" nicht fälschlich anschlagen. Platzhalter
# zusätzlich nur in spitzen Klammern oder als "lorem ipsum".
if printf '%s\n' "$BODY" | grep -qE '\b(TODO|FIXME|XXX)\b' \
   || printf '%s\n' "$BODY" | grep -qiE 'lorem ipsum|<[^>]*(placeholder|platzhalter)[^>]*>'; then
    fail "Body enthält noch Platzhalter (TODO/FIXME/XXX/<platzhalter>) — vor dem Finalisieren entfernen"
else
    ok "Keine Platzhalter im Body"
fi

# --- Zusammenfassung -------------------------------------------------------
echo ""
echo "=== Ergebnis: $FAILS FAIL, $WARNS WARN ==="
if [[ "$FAILS" -eq 0 ]]; then
    echo "✅ Struktur-Prüfung bestanden${WARNS:+ (mit $WARNS Hinweis(en))}"
    exit 0
else
    echo "❌ Struktur-Prüfung fehlgeschlagen: $FAILS FAIL"
    exit 1
fi
