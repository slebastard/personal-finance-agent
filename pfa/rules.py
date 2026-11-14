"""French envelope rules used for deterministic checks.

!! These change. Each value carries the date it was last verified; the agent must re-check
!! anything older than ~6 months (see reference/fr_envelopes_and_tax.md) and update here.
"""
VERIFIED_ON = "2026-10-10"

LIVRET_A_CEILING = 22_950.0          # plafond de versements (hors intérêts capitalisés)
LDDS_CEILING = 12_000.0
LEP_CEILING = 10_000.0
REGULATED_RATES = {                  # since 2026-08-01 (info.gouv.fr)
    "livret_a": 0.017,
    "ldds": 0.017,
    "lep": 0.025,
}
PEA_CONTRIB_CEILING = 150_000.0      # versements, PEA classique
PEA_PME_COMBINED_CEILING = 225_000.0
PEA_TAX_MATURITY_YEARS = 5
AV_TAX_MATURITY_YEARS = 8
AV_ANNUAL_ALLOWANCE = {"single": 4_600.0, "couple": 9_200.0}   # abattement sur gains après 8 ans
SOCIAL_CHARGES = {                    # prélèvements sociaux
    "default_2026": 0.186,            # CTO, PEA (rate at withdrawal date), PEA <5y, PER...
    "assurance_vie": 0.172,           # excluded from the 2026 CSG increase
}
PFU_IR = 0.128
