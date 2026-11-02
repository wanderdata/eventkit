"""Normalization of free-text fields: country, gender and sector."""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

import yaml
from unidecode import unidecode

from . import paths


def norm_text(s) -> str:
    """lowercase, accent-free, single-spaced."""
    if s is None or (isinstance(s, float) and s != s):
        return ""
    s = str(s)
    s = unidecode(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------- countries
@lru_cache
def _countries():
    data = yaml.safe_load(paths.config_file("countries.yml").read_text(encoding="utf-8"))
    index = {}
    for name, meta in data.items():
        keys = {name, meta["en"], meta["iso"]} | set(meta.get("aliases", []))
        for k in keys:
            index[norm_text(k).strip(" .")] = name
    return data, index


def country(raw) -> str | None:
    """Return canonical Spanish country name, or None if unknown/blank."""
    data, index = _countries()
    t = norm_text(raw).strip(" .")
    if not t:
        return None
    if t in index:
        return index[t]
    # "Chile, Santiago" / "Lima - Peru" / "Peru (Lima)"
    for part in re.split(r"[,;/\-()]+", t):
        p = part.strip(" .")
        if p in index:
            return index[p]
    # any known name contained as a whole word
    for k, v in sorted(index.items(), key=lambda kv: -len(kv[0])):
        if len(k) > 3 and re.search(rf"\b{re.escape(k)}\b", t):
            return v
    return None


def country_from_email(email: str) -> str | None:
    """Infer country from a country-code e-mail domain (.pe, .com.mx, ...)."""
    data, _ = _countries()
    tld = (email or "").lower().rsplit(".", 1)[-1]
    if len(tld) != 2:
        return None
    for name, meta in data.items():
        if meta["iso"].lower() == tld:
            return name
    return None


def country_meta(name: str) -> dict:
    data, _ = _countries()
    return data.get(name, {"en": name, "iso": "", "lac": False})


# ------------------------------------------------------------------- gender
_F = {"femenino", "female", "mujer", "f", "woman", "fem", "femenina", "femenino/female", "feminino"}
_M = {"masculino", "male", "hombre", "m", "man", "masc", "masculino/male", "varon"}


def gender(raw) -> str | None:
    """'F', 'M', 'O' (other / prefers not to say) or None (blank)."""
    t = norm_text(raw).strip(" .")
    if not t:
        return None
    if t in _F or t.startswith("femen") or t.startswith("mujer"):
        return "F"
    if t in _M or t.startswith("mascul") or t.startswith("hombre"):
        return "M"
    return "O"


# ------------------------------------------------------------------ sectors
@lru_cache
def sector_rules():
    return yaml.safe_load(paths.config_file("sectors.yml").read_text(encoding="utf-8"))


def _org_cache_path():
    return paths.series_config_dir() / "org_sectors.csv"


@lru_cache
def _org_cache() -> dict:
    out = {}
    for f in (paths.DEFAULTS / "org_sectors.csv", _org_cache_path()):
        if not f.exists():
            continue
        with f.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out[norm_text(row["organization"])] = row["sector"]
    return out


def save_org_cache(new: dict[str, tuple[str, str]]):
    """new: normalized_org -> (original_text, sector). Appends to the CSV."""
    path = _org_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["organization", "sector", "source"])
        for _, (orig, sec) in sorted(new.items()):
            w.writerow([orig, sec, "claude"])
    _org_cache.cache_clear()


def _kw_match(text: str, kws) -> bool:
    for kw in kws:
        k = norm_text(kw)
        if k and re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", text):
            return True
    return False


def sector_from_email(email: str) -> str | None:
    rules = sector_rules()["email_domains"]
    dom = (email or "").lower().split("@")[-1]
    if not dom:
        return None
    for d in rules["internacional"]:
        if dom == d or dom.endswith("." + d):
            return "internacional"
    for s in rules["academia_suffix"]:
        if dom.endswith(s) or ("." + dom).endswith(s):
            return "academia"
    for s in rules["publico_suffix"]:
        if dom.endswith(s) or ("." + dom).endswith(s):
            return "publico"
    labels = dom.split(".")
    if any(x in ("gob", "gov", "gub", "gouv") for x in labels[1:]) or dom.endswith(".go.cr"):
        return "publico"
    if "edu" in labels[1:] or (len(labels) > 2 and labels[-2] == "ac"):
        return "academia"
    return None


def sector_from_text(text: str) -> str | None:
    rules = sector_rules()
    t = norm_text(text)
    if not t:
        return None
    for sec in rules["order"]:
        if _kw_match(t, rules["keywords"].get(sec, [])):
            return sec
    return None


def _looks_like_noise(org) -> bool:
    """Blank-ish, numeric IDs or street addresses typed into the organization box."""
    t = norm_text(org)
    if t in ("no", "n/a", "na", "-", "ninguna", "ninguno", "x"):
        return True
    if re.fullmatch(r"[\d\-. ]+", t):
        return True
    return bool(re.match(r"(calle|carrera|avenida|av\.?|rua|pasaje|jr\.?|jiron)\b", t)) or bool(re.search(r"\b\d{2,5}\b.*\b(dr|st|street|ave)\b", t)) or bool(re.search(r"\b(n\d|no\.? ?\d|#\s?\d)", t)) or bool(re.search(r"[a-z]+ \d{3,5}$", t))


def sector(org, email="", title="") -> tuple[str, str]:
    """Return (sector_key, method)."""
    o = norm_text(org)
    cache = _org_cache()
    if o and o in cache:
        return cache[o], "manual"
    s = sector_from_email(email)
    if s:
        return s, "email"
    s = sector_from_text(o)
    if s:
        return s, "org"
    s = sector_from_text(title)
    if s:
        return s, "title"
    if o and _looks_like_noise(org):
        return "otros", "noise"
    return "sin_clasificar", "none"


def sector_label(key: str, lang="es") -> str:
    return sector_rules()["labels"].get(key, {}).get(lang, key)
