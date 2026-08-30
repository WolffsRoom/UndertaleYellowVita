import argparse
import builtins
import importlib.util
import json
import shutil
import sys
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = SOURCE_DIR.parent
PROJECT_DIR = SOURCE_DIR.parents[3]
LANG_ROOT = PROJECT_DIR / "mods" / "Lang"
PREPARE_SOURCE = (
    PROJECT_DIR
    / "data"
    / "deltarune_builder"
    / "prepare_texture_cache_v0_3_6_bundle"
    / "source"
    / "prepare_texture_cache_v0_3_6.py"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def discover_language_chapters(language_dir: Path):
    chapters = []
    for chapter_dir in sorted(language_dir.glob("chapter*")):
        suffix = chapter_dir.name.removeprefix("chapter")
        data_win = chapter_dir / "data.win"
        if suffix.isdigit() and data_win.is_file():
            chapters.append((chapter_dir.name, data_win))
    return chapters


def copy_overlays(source: Path, target: Path, generated_chapters: set[str]):
    for item in source.iterdir():
        # Local reference installs are useful while preparing a translation,
        # but must never be copied into a Vita language package.
        if item.name in {
            "pvr",
            "prepared_manifest.json",
            "DELTARUNE (Original)",
            "_pc_source",
        }:
            continue
        if item.name in generated_chapters:
            chapter_target = target / item.name
            for child in item.iterdir():
                if child.name in {
                    "data.win",
                    "game.win",
                    "pvr",
                    "texture-cache",
                    "texture_manifest.json",
                }:
                    continue
                destination = chapter_target / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(child, destination)
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("language")
    parser.add_argument("--skip-rebuild", action="store_true")
    args = parser.parse_args()

    language = args.language
    language_dir = LANG_ROOT / language
    if not language_dir.is_dir():
        raise SystemExit(f"Idioma ausente: {language_dir}")

    chapters = discover_language_chapters(language_dir)
    if not chapters:
        raise SystemExit(f"Nenhum data.win encontrado em {language_dir}")

    controller = load_module(
        "deltarune_rebuild_controller",
        SOURCE_DIR / "rebuild_data_win_v1_6.py",
    )
    optimizer = controller.load_optimizer()
    build_root = BUNDLE_DIR / "rebuild" / "_language_build" / language
    controller.REBUILD_DIR = build_root
    controller.clear = lambda: None
    controller.ask_yes_no = lambda _message: True

    named_inputs = [(name, source) for name, source in chapters]
    if not args.skip_rebuild:
        original_input = builtins.input
        builtins.input = lambda _prompt="": ""
        try:
            result = controller.run_batch(optimizer, named_inputs)
        finally:
            builtins.input = original_input
        if result != 0:
            raise SystemExit(result)

    prepared_root = BUNDLE_DIR / "rebuild" / "_language_ready" / language
    prepare = load_module("deltarune_prepare_texture", PREPARE_SOURCE)
    prepare.PREPARED_DIR = prepared_root
    # A language may have been built previously with a different source
    # layout. Reusing that directory leaves obsolete chapterN_windows, PC
    # binaries and old cache pages mixed into the new Vita package.
    if prepared_root.exists():
        shutil.rmtree(prepared_root)
    prepared_root.mkdir(parents=True, exist_ok=True)

    manifests = []
    for chapter_name, _source in chapters:
        rebuilt = build_root / chapter_name / "data.win"
        if not rebuilt.is_file():
            raise RuntimeError(f"Rebuild ausente: {rebuilt}")
        manifests.append(
            prepare.prepare_chapter(
                chapter_name.removeprefix("chapter"), rebuilt
            )
        )

    manifest = {
        "tool_version": prepare.APP_VERSION,
        "language": language,
        "chapters": manifests,
    }
    (prepared_root / "prepared_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    copy_overlays(
        language_dir,
        prepared_root,
        {name for name, _source in chapters},
    )
    print(f"LANGUAGE_BUILD_DONE={language}")
    print(f"READY_DIR={prepared_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
