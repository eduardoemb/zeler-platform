import importlib


def test_top_level_packages_are_importable() -> None:
    module_names = [
        "zeler_gateway",
        "zeler_platform_core",
        "zeler_bootstrap",
        "zeler_repricer",
        "zeler_sheets",
        "zeler_publicador",
        "zeler_autoreply",
        "zeler_fulldock",
    ]

    imported = [importlib.import_module(module_name).__name__ for module_name in module_names]

    assert imported == module_names


def test_core_models_namespace_is_importable() -> None:
    module = importlib.import_module("zeler_platform_core.models")

    assert module.__name__ == "zeler_platform_core.models"
