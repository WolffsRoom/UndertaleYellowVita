import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# =============================================================================
# DeltaruneVita - Rebuild Data.win
#
# Toda a estrutura e resolvida RELATIVAMENTE a este arquivo:
#
# rebuild_data_win\
#   rebuild_data_win.bat
#   chapters\
#   rebuild\
#   source\
#       rebuild_data_win.py
#       texture_optimizer.py
#       UTMT_CLI\
#           UndertaleModCli.exe
# =============================================================================

SOURCE_DIR = Path(__file__).resolve().parent
ROOT_DIR = SOURCE_DIR.parent

CHAPTERS_DIR = ROOT_DIR / "chapters"
REBUILD_DIR = ROOT_DIR / "rebuild"

CLI_EXE = SOURCE_DIR / "UTMT_CLI" / "UndertaleModCli.exe"
OPTIMIZER_FILE = SOURCE_DIR / "texture_optimizer_v1_6.py"
GML_OPTIMIZER_SCRIPT = SOURCE_DIR / "apply_vita_gml_optimizations.csx"

WIDTH = 84
APP_VERSION = "1.6.0"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def rel(path):
    """Mostra caminhos relativos a pasta raiz do rebuild_data_win."""
    path = Path(path).resolve()

    try:
        return str(path.relative_to(ROOT_DIR)).replace("/", "\\")
    except ValueError:
        return path.name


def line(char="="):
    print(char * WIDTH)


def page(title, subtitle=None, step=None):
    clear()

    line("=")
    print(f" DELTARUNEVITA - REBUILD DATA.WIN  |  v{APP_VERSION}")
    line("=")

    if step:
        print(f" {step}")

    print()
    print(f" {title}")

    if subtitle:
        print(f" {subtitle}")

    print()
    line("-")
    print()


def footer(message=None):
    print()
    line("-")

    if message:
        print(f" {message}")

    print()


def fail(title, message):
    page(
        title,
        "O processo foi interrompido com seguranca.",
    )

    print(message)
    footer("Nenhum data.win original foi alterado.")

    input("Pressione ENTER para voltar...")
    return 1


def load_optimizer():
    if not OPTIMIZER_FILE.exists():
        raise RuntimeError(
            "Arquivo ausente: source\\texture_optimizer_v1_6.py"
        )

    spec = importlib.util.spec_from_file_location(
        "texture_optimizer",
        OPTIMIZER_FILE,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Nao foi possivel carregar texture_optimizer.py."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def discover_chapters():
    CHAPTERS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = []

    for data_win in CHAPTERS_DIR.rglob("data.win"):
        if not data_win.is_file():
            continue
        relative_folder = data_win.parent.relative_to(CHAPTERS_DIR)
        name = str(relative_folder).replace("\\", "/")
        result.append((name, data_win))

    def natural_key(item):
        name = item[0]

        return [
            (0, int(part)) if part.isdigit() else (1, part.lower())
            for part in re.split(r"(\d+)", name)
        ]

    return sorted(
        result,
        key=natural_key,
    )


def choose_chapter(chapters):
    while True:
        page(
            "Selecionar arquivo",
            "Escolha qual data.win sera analisado.",
            "PAGINA 1/5  |  SELECAO",
        )

        print(" Arquivos encontrados em chapters\\:")
        print()

        longest = max(
            [len(name) for name, _ in chapters] + [8]
        )

        for name, data_win in chapters:
            size_mib = (
                data_win.stat().st_size
                / (1024 * 1024)
            )

            print(
                f"   {name:<{longest}}"
                f"   {size_mib:>9.2f} MiB"
                f"   {rel(data_win)}"
            )

        print()
        print(" Digite A para reconstruir todos os arquivos.")
        print(" Digite o nome da pasta desejada.")
        print(" Exemplo: 2")
        print()
        print(" Digite Q para sair.")
        print()

        choice = input(" > ").strip()

        if choice.lower() in (
            "q",
            "quit",
            "sair",
        ):
            return None

        if choice.lower() in (
            "a",
            "all",
            "todos",
        ):
            return "__ALL__", None

        for name, data_win in chapters:
            if name == choice:
                return name, data_win

        print()
        print(
            f' Pasta "{choice}" nao encontrada ou sem data.win.'
        )
        input(" Pressione ENTER para tentar novamente...")


def ask_yes_no(message):
    while True:
        answer = input(
            f" {message} [Y/N]: "
        ).strip().lower()

        if answer in (
            "y",
            "yes",
            "s",
            "sim",
        ):
            return True

        if answer in (
            "n",
            "no",
            "nao",
            "não",
        ):
            return False

        print(" Resposta invalida. Digite Y ou N.")


def copy_final_win(generated_win, chapter_name):
    final_dir = REBUILD_DIR / chapter_name
    final_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    final_win = final_dir / "data.win"
    previous_win = final_dir / "data.previous.win"

    if final_win.exists():
        if previous_win.exists():
            previous_win.unlink()

        final_win.replace(previous_win)

    shutil.copy2(
        generated_win,
        final_win,
    )

    return final_win


def apply_vita_gml_optimizations(generated_win, work_dir):
    """Apply verified, semantic GML patches after the texture repack."""
    if not GML_OPTIMIZER_SCRIPT.exists():
        raise RuntimeError(
            "Arquivo ausente: source\\apply_vita_gml_optimizations.csx"
        )

    patched_win = work_dir / "data_vita_gml.win"
    report_path = work_dir / "vita_gml_optimizations.txt"

    if patched_win.exists():
        patched_win.unlink()

    env = os.environ.copy()
    env["DELTARUNE_VITA_GML_REPORT"] = str(report_path)

    command = [
        str(CLI_EXE),
        "load",
        str(generated_win),
        "-s",
        str(GML_OPTIMIZER_SCRIPT),
        "-o",
        str(patched_win),
    ]
    result = subprocess.run(
        command,
        cwd=str(CLI_EXE.parent),
        env=env,
        check=False,
    )
    if result.returncode != 0 or not patched_win.exists():
        raise RuntimeError(
            "Falha ao aplicar as otimizacoes GML do DeltaruneVita."
        )

    # Reopen and rerun the idempotent checks. A second mutation is forbidden.
    verify_report = work_dir / "vita_gml_optimizations_verify.txt"
    env["DELTARUNE_VITA_GML_REPORT"] = str(verify_report)
    verify = subprocess.run(
        [
            str(CLI_EXE),
            "load",
            str(patched_win),
            "-s",
            str(GML_OPTIMIZER_SCRIPT),
        ],
        cwd=str(CLI_EXE.parent),
        env=env,
        check=False,
    )
    if verify.returncode != 0:
        raise RuntimeError(
            "O data.win falhou ao reabrir apos os patches GML."
        )
    if verify_report.exists() and "RESULT changed=1" in verify_report.read_text(
        encoding="utf-8-sig"
    ):
        raise RuntimeError(
            "Patch GML nao idempotente detectado; o arquivo foi rejeitado."
        )

    return patched_win


def print_analysis_summary(summary_path):
    if not summary_path.exists():
        print(
            " O otimizador concluiu a analise, "
            "mas nao gerou summary_unified.txt."
        )
        return

    text = summary_path.read_text(
        encoding="utf-8-sig",
    ).strip()

    for current in text.splitlines():
        print(" " + current)


def write_batch_report(results):
    report_path = REBUILD_DIR / "batch_rebuild_report.txt"
    lines = [
        "DeltaruneVita DeltaBuilder - batch rebuild report",
        f"Pipeline: {APP_VERSION}",
        "",
    ]
    for result in results:
        lines.append(
            f"{result['status']}  {result['chapter']}  {result['message']}"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run_batch(optimizer, chapters):
    page(
        "Reconstruir todos os arquivos",
        f"{len(chapters)} data.win encontrados em chapters\\.",
        "LOTE  |  CONFIRMACAO",
    )
    print(" Ordem de processamento:")
    print()
    for index, (chapter_name, input_win) in enumerate(chapters, start=1):
        print(f"   {index:>2}. {chapter_name:<24} {rel(input_win)}")
    print()
    print(" Em caso de erro, o lote sera interrompido imediatamente.")
    print(" Os arquivos concluidos antes do erro permanecerao em rebuild\\.")
    footer("Uma confirmacao executa o lote inteiro.")

    if not ask_yes_no("Analisar e reconstruir todos os arquivos?"):
        return 0

    results = []
    total = len(chapters)

    for index, (chapter_name, input_win) in enumerate(chapters, start=1):
        chapter_rebuild = REBUILD_DIR / chapter_name
        work_dir = chapter_rebuild / "_work"

        page(
            f"[{index}/{total}] Analisando: {chapter_name}",
            rel(input_win),
            "LOTE  |  ANALISE E REBUILD",
        )
        print(" O original sera apenas lido.")
        print(" O resultado anterior sera preservado como data.previous.win.")
        print()

        try:
            analysis = optimizer.analyze_win(
                input_win=input_win,
                cli=CLI_EXE,
                work_root=work_dir,
                force_clean=True,
            )
            print_analysis_summary(Path(analysis["summary_path"]))
            print()
            print(f" [{index}/{total}] Gerando atlas e data.win...")

            generated_win = optimizer.write_optimized_win(analysis)
            generated_win = apply_vita_gml_optimizations(
                generated_win,
                work_dir,
            )
            final_win = copy_final_win(generated_win, chapter_name)
            results.append({
                "status": "OK",
                "chapter": chapter_name,
                "message": rel(final_win),
            })
        except Exception as exc:
            results.append({
                "status": "ERROR",
                "chapter": chapter_name,
                "message": str(exc).replace("\n", " "),
            })
            report_path = write_batch_report(results)
            page(
                f"Erro no arquivo: {chapter_name}",
                "O lote foi interrompido no arquivo com falha.",
                f"LOTE {index}/{total}  |  ERRO",
            )
            print(f" Entrada: {rel(input_win)}")
            print()
            print(f" Erro: {exc}")
            print()
            print(" Concluidos antes do erro:")
            completed = [item for item in results if item["status"] == "OK"]
            if completed:
                for item in completed:
                    print(f"   OK  {item['chapter']}")
            else:
                print("   Nenhum.")
            print()
            print(f" Relatorio: {rel(report_path)}")
            footer("O arquivo de entrada com erro permaneceu intacto.")
            input("Pressione ENTER para encerrar...")
            return 1

    report_path = write_batch_report(results)
    page(
        "Processamento em lote concluido",
        f"{total} de {total} arquivos reconstruidos e validados.",
        "LOTE  |  CONCLUIDO",
    )
    for item in results:
        print(f"   OK  {item['chapter']:<24} {item['message']}")
    print()
    print(f" Relatorio: {rel(report_path)}")
    footer("Todos os arquivos originais em chapters\\ permaneceram intactos.")
    input("Pressione ENTER para encerrar...")
    return 0


def main():
    # -------------------------------------------------------------------------
    # Bootstrap / environment
    # -------------------------------------------------------------------------
    page(
        "Inicializando",
        "Validando a estrutura da ferramenta.",
        "INICIALIZACAO",
    )

    print(f" Versao: {APP_VERSION}")
    print()
    print(" Estrutura utilizada:")
    print("   chapters\\")
    print("   rebuild\\")
    print("   source\\")
    print("   source\\UTMT_CLI\\UndertaleModCli.exe")
    print()

    if not CLI_EXE.exists():
        return fail(
            "UndertaleModCli nao encontrado",
            (
                "O executavel esperado nao existe em:\n\n"
                "  source\\UTMT_CLI\\UndertaleModCli.exe"
            ),
        )

    try:
        optimizer = load_optimizer()
    except Exception as exc:
        return fail(
            "Falha ao carregar o otimizador",
            str(exc),
        )

    optimizer_version = getattr(
        optimizer,
        "PIPELINE_VERSION",
        None,
    )

    if optimizer_version != APP_VERSION:
        return fail(
            "Versoes incompatíveis",
            (
                "Os arquivos da ferramenta nao pertencem ao mesmo pacote.\n\n"
                f"Controller: {APP_VERSION}\n"
                f"Optimizer:  {optimizer_version}\n\n"
                "Substitua novamente os arquivos dentro de source\\."
            ),
        )

    chapters = discover_chapters()

    if not chapters:
        return fail(
            "Nenhum data.win encontrado",
            (
                "Adicione pelo menos um arquivo seguindo:\n\n"
                "  chapters\\<nome>\\data.win\n\n"
                "Exemplo:\n\n"
                "  chapters\\2\\data.win"
            ),
        )

    # -------------------------------------------------------------------------
    # Page 1 - Chapter selection
    # -------------------------------------------------------------------------
    selected = choose_chapter(chapters)

    if selected is None:
        clear()
        return 0

    chapter_name, input_win = selected

    if chapter_name == "__ALL__":
        return run_batch(optimizer, chapters)

    chapter_rebuild = (
        REBUILD_DIR
        / chapter_name
    )

    work_dir = (
        chapter_rebuild
        / "_work"
    )

    # -------------------------------------------------------------------------
    # Page 2 - Analyze
    # -------------------------------------------------------------------------
    page(
        f"Analisando: {chapter_name}",
        rel(input_win),
        "PAGINA 2/5  |  ANALISE",
    )

    print(" O arquivo original sera apenas lido.")
    print(" Nenhuma escrita sera realizada nesta etapa.")
    print()
    print(" Etapas:")
    print("   1. Analise RAW")
    print("   2. Mapeamento Room / recursos")
    print("   3. Packing Hybrid / Density-Aware")
    print("   4. TextureGroup Probe")
    print("   5. Gate de regressao de VRAM")
    print()
    line("-")
    print()

    try:
        analysis = optimizer.analyze_win(
            input_win=input_win,
            cli=CLI_EXE,
            work_root=work_dir,
            force_clean=True,
        )
    except Exception as exc:
        return fail(
            "Analise falhou",
            str(exc),
        )

    # -------------------------------------------------------------------------
    # Page 3 - Analysis result / confirmation
    # -------------------------------------------------------------------------
    page(
        "Resultado da analise",
        f"Arquivo: {rel(input_win)}",
        "PAGINA 3/5  |  RESULTADO",
    )

    print_analysis_summary(
        Path(analysis["summary_path"])
    )

    footer(
        "O data.win original permanece intacto."
    )

    if not ask_yes_no(
        "Continuar e gerar o data.win otimizado?"
    ):
        page(
            "Operacao cancelada",
            "A analise foi mantida para consulta.",
            "ENCERRADO",
        )

        print(
            " Nenhum arquivo otimizado foi gerado."
        )
        print()
        print(
            " Artefatos da analise:"
        )
        print(
            f"   {rel(work_dir)}"
        )

        footer(
            "Pressione ENTER para encerrar."
        )
        input()
        return 0

    # -------------------------------------------------------------------------
    # Page 4 - Write
    # -------------------------------------------------------------------------
    page(
        f"Gerando data.win otimizado",
        f"Destino: rebuild\\{chapter_name}\\data.win",
        "PAGINA 4/5  |  REBUILD",
    )

    print(" O plano aprovado sera aplicado usando RAW CROP.")
    print()
    print(" Depois do write o arquivo sera reaberto")
    print(" pelo UndertaleModCLI para verificacao estrutural.")
    print()
    line("-")
    print()

    try:
        generated_win = optimizer.write_optimized_win(
            analysis
        )

        generated_win = apply_vita_gml_optimizations(
            generated_win,
            work_dir,
        )

        final_win = copy_final_win(
            generated_win,
            chapter_name,
        )

    except Exception as exc:
        return fail(
            "Geracao falhou",
            str(exc),
        )

    # -------------------------------------------------------------------------
    # Page 5 - Finished
    # -------------------------------------------------------------------------
    page(
        "Processo concluido",
        "O novo data.win foi gerado e validado.",
        "PAGINA 5/5  |  CONCLUIDO",
    )

    print(" Capitulo:")
    print(f"   {chapter_name}")
    print()
    print(" Original:")
    print(f"   {rel(input_win)}")
    print()
    print(" Otimizado:")
    print(f"   {rel(final_win)}")

    previous = (
        final_win.parent
        / "data.previous.win"
    )

    if previous.exists():
        print()
        print(" Build anterior:")
        print(f"   {rel(previous)}")

    print()
    print(" Proximo passo no Vita:")
    print(
        "   Regenere os caches de textura derivados "
        "desse capitulo antes do teste."
    )

    footer(
        "O arquivo em chapters\\ permaneceu intacto."
    )

    input("Pressione ENTER para encerrar...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
