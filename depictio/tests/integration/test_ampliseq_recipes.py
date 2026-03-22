"""
Integration tests for the nf-core/ampliseq recipe system.

Verifies that all bundled ampliseq recipes are discoverable, loadable, and
structurally valid. For each new pipeline template, add a similar
TestXxxRecipeDiscovery class here — no per-recipe transform() tests needed.

Requires the ampliseq recipes to be present in depictio/projects/nf-core/ampliseq/.
"""

from depictio.recipes import list_recipes, load_recipe

AMPLISEQ_RECIPES = [
    "nf-core/ampliseq/alpha_diversity.py",
    "nf-core/ampliseq/alpha_rarefaction.py",
    "nf-core/ampliseq/ancombc.py",
    "nf-core/ampliseq/taxonomy_composition.py",
    "nf-core/ampliseq/taxonomy_rel_abundance.py",
]

AMPLISEQ_VERSIONS = ["2.14.0", "2.16.0"]


class TestAmpliseqRecipeDiscovery:
    """Verify ampliseq recipes are discoverable and loadable."""

    def test_all_ampliseq_recipes_listed(self) -> None:
        """All known ampliseq shared recipes appear in list_recipes()."""
        recipes = list_recipes()
        for recipe in AMPLISEQ_RECIPES:
            assert recipe in recipes, f"Missing recipe: {recipe}"

    def test_version_overrides_not_listed(self) -> None:
        """Version-specific overrides (2.14.0, 2.16.0) are not in list_recipes()."""
        recipes = list_recipes()
        for version in AMPLISEQ_VERSIONS:
            assert not any(f"/{version}/" in r for r in recipes)

    def test_all_ampliseq_recipes_load(self) -> None:
        """Every bundled ampliseq recipe loads with valid SOURCES, EXPECTED_SCHEMA, transform."""
        for recipe_name in AMPLISEQ_RECIPES:
            module = load_recipe(recipe_name)
            assert hasattr(module, "SOURCES"), f"{recipe_name}: missing SOURCES"
            assert hasattr(module, "EXPECTED_SCHEMA"), f"{recipe_name}: missing EXPECTED_SCHEMA"
            assert callable(module.transform), f"{recipe_name}: transform not callable"
            assert isinstance(module.SOURCES, list) and len(module.SOURCES) > 0
            assert isinstance(module.EXPECTED_SCHEMA, dict) and len(module.EXPECTED_SCHEMA) > 0

    def test_version_override_loads_for_taxonomy_rel_abundance(self) -> None:
        """v2.14.0 has an override for taxonomy_rel_abundance."""
        module_v14 = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py", "2.14.0")
        module_shared = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        assert callable(module_v14.transform)
        assert callable(module_shared.transform)

    def test_version_fallback_for_alpha_diversity(self) -> None:
        """alpha_diversity has no version override; versioned load falls back to shared."""
        module_versioned = load_recipe("nf-core/ampliseq/alpha_diversity.py", "2.14.0")
        module_shared = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        assert module_versioned.SOURCES == module_shared.SOURCES

    def test_locate_ampliseq_template(self) -> None:
        """nf-core/ampliseq/2.16.0 template.yaml is discoverable."""
        from depictio.cli.cli.utils.templates import locate_template

        path = locate_template("nf-core/ampliseq/2.16.0")
        assert path.is_file()
        assert path.name in ("template.yaml", "project.yaml")
