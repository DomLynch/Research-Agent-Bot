from __future__ import annotations

from pathlib import Path

import pytest

from agent.topic_pack import load_topic_pack

ROOT = Path(__file__).resolve().parent.parent

REQUESTED_LONGEVITY_TOPICS = (
    "urolithin_a",
    "taurine",
    "glynac",
    "alpha_ketoglutarate_akg",
    "glp_1_longevity",
    "retatrutide_triple_agonists",
    "sglt2_inhibitors",
    "acarbose",
    "epigenetic_clocks",
    "organ_specific_aging_clocks",
    "partial_epigenetic_reprogramming",
    "cellular_reprogramming_safety",
    "therapeutic_plasma_exchange",
    "young_plasma_parabiosis",
    "exosomes_extracellular_vesicles",
    "mesenchymal_stem_cells_mscs",
    "klotho",
    "gdf11",
    "mitochondrial_peptides",
    "nad_iv_therapy",
    "hydrogen_water",
    "deuterium_depleted_water",
    "microbiome_longevity",
    "akkermansia_muciniphila",
    "oral_microbiome_periodontal_aging",
    "sauna_heat_therapy",
    "photobiomodulation_red_light",
    "hyperbaric_oxygen_hbot",
    "hormone_optimization_hrt",
    "sarcopenia_muscle_preservation",
    "plasma_proteomic_age_clocks",
    "metabolomic_age_clocks",
    "glycomic_age_clocks",
    "retinal_age_ai",
    "brain_age_mri",
    "immune_age",
    "vascular_age",
    "digital_frailty_index",
    "allostatic_load",
    "composite_biomarker_age_panels",
    "aspirin_geroprotection",
    "statins_longevity",
    "ace_inhibitors_aging",
    "arbs_longevity",
    "colchicine_inflammaging",
    "pcsk9_inhibitors_longevity",
    "bempedoic_acid_longevity",
    "low_dose_lithium",
    "melatonin_aging",
    "low_dose_naltrexone_inflammation",
    "omega_3_longevity",
    "vitamin_d_healthspan",
    "vitamin_k2_vascular_aging",
    "magnesium_longevity",
    "coenzyme_q10_ubiquinol",
    "ergothioneine",
    "carnosine_anti_glycation",
    "sulforaphane_nrf2",
    "curcumin_inflammaging",
    "egcg_green_tea_longevity",
    "inflammaging",
    "immunosenescence",
    "sasp_secretome",
    "proteostasis_chaperones",
    "glycation_ages",
    "mitochondrial_dna_damage",
    "mitochondrial_biogenesis_pgc1a",
    "extracellular_matrix_stiffening",
    "stem_cell_exhaustion",
    "epigenome_editing_longevity",
    "vo2max_longevity",
    "grip_strength_longevity",
    "gait_speed_longevity",
    "sleep_architecture_deep_sleep",
    "circadian_light_timing",
    "cgm_glucose_variability",
    "hrv_autonomic_aging",
    "cold_exposure_brown_fat",
    "plant_based_diet_biological_age",
    "blue_zones_diet_lifestyle",
)


def test_requested_longevity_topic_set_has_expected_size() -> None:
    assert len(REQUESTED_LONGEVITY_TOPICS) == 80
    assert len(set(REQUESTED_LONGEVITY_TOPICS)) == 80


@pytest.mark.parametrize("slug", REQUESTED_LONGEVITY_TOPICS)
def test_requested_longevity_topic_is_loadable_and_discoverable(slug: str) -> None:
    pack_path = ROOT / "topic_packs" / f"{slug}.toml"
    corpus_dir = ROOT / "docs" / "quality-reference" / slug

    assert pack_path.exists(), slug
    if not corpus_dir.is_dir():
        pytest.skip(f"{slug}: corpus not seeded in this environment")

    pack = load_topic_pack(pack_path)
    assert pack.topic == slug
    assert pack.aliases
    assert pack.target_journal == "GeroScience"
    assert pack.corpus_search_queries or pack.retrieval is not None
