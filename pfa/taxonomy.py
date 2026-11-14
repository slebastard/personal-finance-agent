"""Normalize free-text buckets (FR/EN, Boursorama/justETF wording) to a fixed taxonomy."""
from __future__ import annotations

import unicodedata

GICS = [
    "Information Technology", "Financials", "Health Care", "Consumer Discretionary",
    "Industrials", "Communication Services", "Consumer Staples", "Energy",
    "Materials", "Utilities", "Real Estate",
]

_SECTOR_ALIASES = {
    "information technology": "Information Technology", "technology": "Information Technology",
    "it": "Information Technology", "technologie": "Information Technology",
    "technologies de l'information": "Information Technology", "technologie de l'information": "Information Technology",
    "financials": "Financials", "financial": "Financials", "finance": "Financials", "services financiers": "Financials",
    "financial services": "Financials", "banques": "Financials", "assurance": "Financials",
    "health care": "Health Care", "healthcare": "Health Care", "sante": "Health Care", "soins de sante": "Health Care",
    "consumer discretionary": "Consumer Discretionary", "consommation discretionnaire": "Consumer Discretionary",
    "biens de consommation cycliques": "Consumer Discretionary", "consumer cyclical": "Consumer Discretionary",
    "industrials": "Industrials", "industrie": "Industrials", "industriels": "Industrials", "industries": "Industrials",
    "communication services": "Communication Services", "communication": "Communication Services",
    "telecommunications": "Communication Services",
    "services de communication": "Communication Services", "telecommunication": "Communication Services",
    "consumer staples": "Consumer Staples", "biens de consommation de base": "Consumer Staples",
    "consommation de base": "Consumer Staples", "consumer defensive": "Consumer Staples",
    "energy": "Energy", "energie": "Energy",
    "materials": "Materials", "basic materials": "Materials", "materiaux": "Materials", "matieres premieres": "Materials",
    "utilities": "Utilities", "services aux collectivites": "Utilities", "services publics": "Utilities",
    "real estate": "Real Estate", "immobilier": "Real Estate",
}

REGIONS = ["France", "Europe ex-France", "North America", "Japan", "Asia-Pacific developed",
           "Emerging markets", "Other"]

_COUNTRY_ALIASES = {
    "etats-unis": "United States", "usa": "United States", "us": "United States", "united states of america": "United States",
    "royaume-uni": "United Kingdom", "uk": "United Kingdom", "grande-bretagne": "United Kingdom",
    "united kingdom of great britain and northern ireland": "United Kingdom",
    "allemagne": "Germany", "suisse": "Switzerland", "pays-bas": "Netherlands", "espagne": "Spain",
    "italie": "Italy", "belgique": "Belgium", "suede": "Sweden", "danemark": "Denmark", "norvege": "Norway",
    "finlande": "Finland", "irlande": "Ireland", "autriche": "Austria", "japon": "Japan", "chine": "China",
    "inde": "India", "coree du sud": "South Korea", "korea": "South Korea", "coree": "South Korea",
    "taiwan": "Taiwan", "taïwan": "Taiwan", "bresil": "Brazil", "mexique": "Mexico", "australie": "Australia",
    "nouvelle-zelande": "New Zealand", "singapour": "Singapore", "hong kong": "Hong Kong", "afrique du sud": "South Africa",
    "arabie saoudite": "Saudi Arabia", "emirats arabes unis": "United Arab Emirates", "israel": "Israel",
    "pologne": "Poland", "luxembourg": "Luxembourg", "portugal": "Portugal", "indonesie": "Indonesia",
    "thailande": "Thailand", "malaisie": "Malaysia", "chili": "Chile", "turquie": "Turkey", "grece": "Greece",
    "autres": "Other", "autre": "Other", "others": "Other", "divers": "Other",
}

_REGION_OF = {
    "France": "France",
    **{c: "Europe ex-France" for c in [
        "Germany", "United Kingdom", "Switzerland", "Netherlands", "Spain", "Italy", "Belgium", "Sweden",
        "Denmark", "Norway", "Finland", "Ireland", "Austria", "Luxembourg", "Portugal"]},
    "United States": "North America", "Canada": "North America",
    "Japan": "Japan",
    **{c: "Asia-Pacific developed" for c in ["Australia", "New Zealand", "Singapore", "Hong Kong", "Israel"]},
    **{c: "Emerging markets" for c in [
        "China", "India", "Taiwan", "South Korea", "Brazil", "Mexico", "South Africa", "Saudi Arabia",
        "United Arab Emirates", "Indonesia", "Thailand", "Malaysia", "Chile", "Turkey", "Poland", "Greece",
        "Qatar", "Kuwait", "Philippines", "Peru", "Colombia", "Hungary", "Czech Republic", "Egypt"]},
}

_REGION_ALIASES = {
    "europe": "Europe ex-France", "europe ex france": "Europe ex-France", "zone euro": "Europe ex-France",
    "amerique du nord": "North America", "north america": "North America",
    "emerging markets": "Emerging markets", "marches emergents": "Emerging markets", "emergents": "Emerging markets",
    "japon": "Japan", "japan": "Japan", "france": "France",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(s.replace("’", "'").split())


def sector(name: str) -> str:
    f = _fold(name)
    if f in ("other", "autre", "autres", "divers", "cash", "liquidites"):
        return "Other"
    return _SECTOR_ALIASES.get(f, name if name in GICS else "Other")


def country(name: str) -> str:
    f = _fold(name)
    if f in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[f]
    return " ".join(w.capitalize() for w in name.strip().split()) if name.strip() else "Other"


def region_of_country(c: str) -> str:
    return _REGION_OF.get(c, "Other")


def region(name: str) -> str:
    f = _fold(name)
    if f in _REGION_ALIASES:
        return _REGION_ALIASES[f]
    return name if name in REGIONS else "Other"


def is_unknown_sector(name: str) -> bool:
    f = _fold(name)
    return f not in _SECTOR_ALIASES and name not in GICS and f not in ("other", "autre", "autres", "divers")
