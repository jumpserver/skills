#!/usr/bin/env python3
"""Standard-library dependency bootstrap for the JumpServer CLI entry points."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


CONFIRM_INSTALL_FLAG = "--confirm-install"
HELP_FLAGS = {"-h", "--help"}
REQUIRED_IMPORT_PROBES = {
    "jumpserver-sdk-python": ("jms_client",),
}
UNSUPPORTED_REQUIREMENT_PREFIXES = ("-r", "--requirement", "-e", "--editable", "--")
UNSUPPORTED_DIRECT_REFERENCE_TOKENS = (" @ ", "git+", "hg+", "svn+", "bzr+")
SIMPLE_REQUIREMENT_RE = re.compile(
    r"""
    ^
    (?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)
    (?:\[[A-Za-z0-9_.\-,]+\])?
    (?:
        \s*
        (?:
            ===|==|~=|!=|<=|>=|<|>
        )
        \s*
        [^;\s,]+
        (?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[^;\s,]+)*
    )?
    \s*
    (?:;.+)?
    $
    """,
    re.VERBOSE,
)


class BootstrapError(RuntimeError):
    """Raised when the bootstrap cannot complete safely."""


@dataclass(frozen=True)
class RequirementSpec:
    name: str
    normalized_name: str
    raw: str
    line_number: int


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def resolve_requirements_path() -> Path:
    return Path(__file__).resolve().parent.parent / "requirements.txt"


def parse_requirement_line(line: str, line_number: int) -> RequirementSpec | None:
    candidate = re.split(r"\s+#", line.strip(), maxsplit=1)[0].strip()
    if not candidate:
        return None
    if candidate.startswith("#"):
        return None
    if candidate.startswith(UNSUPPORTED_REQUIREMENT_PREFIXES):
        raise BootstrapError(
            f"Unsupported requirement on line {line_number}: {candidate}. "
            "Only plain package requirements are supported in requirements.txt."
        )
    if "://" in candidate or any(token in candidate for token in UNSUPPORTED_DIRECT_REFERENCE_TOKENS):
        raise BootstrapError(
            f"Unsupported requirement on line {line_number}: {candidate}. "
            "Direct URL, VCS, and PEP 508 direct-reference requirements must be installed manually."
        )

    match = SIMPLE_REQUIREMENT_RE.fullmatch(candidate)
    if not match:
        raise BootstrapError(
            f"Unsupported requirement on line {line_number}: {candidate}. "
            "Only plain package requirements are supported in requirements.txt."
        )

    name = match.group("name")
    return RequirementSpec(
        name=name,
        normalized_name=normalize_distribution_name(name),
        raw=candidate,
        line_number=line_number,
    )


def parse_requirements_text(text: str) -> list[RequirementSpec]:
    requirements: list[RequirementSpec] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        requirement = parse_requirement_line(line, line_number)
        if requirement is None or requirement.normalized_name in seen:
            continue
        requirements.append(requirement)
        seen.add(requirement.normalized_name)
    return requirements


def parse_requirements_file(path: Path) -> list[RequirementSpec]:
    if not path.exists():
        raise BootstrapError(f"requirements.txt not found at {path}.")
    return parse_requirements_text(path.read_text(encoding="utf-8"))


def build_installed_distribution_map(
    distributions: list[importlib_metadata.Distribution] | None = None,
) -> dict[str, str]:
    installed: dict[str, str] = {}
    if distributions is None:
        distributions = list(importlib_metadata.distributions())
    for distribution in distributions:
        name = distribution.metadata.get("Name") or getattr(distribution, "name", None)
        if not name:
            continue
        installed[normalize_distribution_name(str(name))] = str(distribution.version)
    return installed


def find_missing_requirements(
    requirements: list[RequirementSpec],
    installed: dict[str, str],
) -> list[RequirementSpec]:
    return [
        requirement
        for requirement in requirements
        if requirement.normalized_name not in installed
    ]


def find_unhealthy_requirements(
    requirements: list[RequirementSpec],
    installed: dict[str, str],
    probe_finder=None,
) -> list[RequirementSpec]:
    if probe_finder is None:
        probe_finder = importlib_util.find_spec

    unhealthy: list[RequirementSpec] = []
    for requirement in requirements:
        if requirement.normalized_name not in installed:
            unhealthy.append(requirement)
            continue

        required_modules = REQUIRED_IMPORT_PROBES.get(requirement.normalized_name, ())
        if any(probe_finder(module_name) is None for module_name in required_modules):
            unhealthy.append(requirement)
    return unhealthy


def strip_confirm_install_flag(argv: list[str]) -> tuple[list[str], bool]:
    cleaned: list[str] = []
    confirmed = False
    for arg in argv:
        if arg == CONFIRM_INSTALL_FLAG:
            confirmed = True
            continue
        cleaned.append(arg)
    return cleaned, confirmed


def has_help_flag(args: list[str]) -> bool:
    return any(arg in HELP_FLAGS for arg in args)


def print_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def fail_json(message: str) -> None:
    print_json({"ok": False, "error": message})
    raise SystemExit(1)


def build_retry_command(argv: list[str]) -> str:
    if not argv:
        return shlex.join([sys.executable, CONFIRM_INSTALL_FLAG])
    return shlex.join([sys.executable, argv[0], CONFIRM_INSTALL_FLAG, *argv[1:]])


def install_requirements(requirements_path: Path) -> None:
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]
    stderr_target = sys.stderr if sys.stderr is not None else subprocess.DEVNULL
    if sys.stderr is not None:
        print(
            f"[bootstrap] Installing missing Python dependencies from {requirements_path}",
            file=sys.stderr,
        )
    completed = subprocess.run(
        command,
        stdout=stderr_target,
        stderr=stderr_target,
        check=False,
    )
    if completed.returncode != 0:
        raise BootstrapError(
            "Automatic dependency installation failed. "
            f"Re-run with a working pip environment, or install manually with "
            f"{shlex.join(command)}."
        )


def ensure_requirements_installed(argv: list[str], confirm_install: bool) -> None:
    requirements_path = resolve_requirements_path()
    requirements = parse_requirements_file(requirements_path)
    installed = build_installed_distribution_map()
    unhealthy = find_unhealthy_requirements(requirements, installed)
    if not unhealthy:
        return

    unhealthy_names = ", ".join(requirement.name for requirement in unhealthy)
    if not confirm_install:
        raise BootstrapError(
            "Missing or unusable required Python packages from requirements.txt: "
            f"{unhealthy_names}. Re-run the same command with {CONFIRM_INSTALL_FLAG} to install "
            f"or repair them automatically: {build_retry_command(argv)}"
        )

    install_requirements(requirements_path)
    installed_after_install = build_installed_distribution_map()
    still_unhealthy = find_unhealthy_requirements(requirements, installed_after_install)
    if still_unhealthy:
        still_unhealthy_names = ", ".join(requirement.name for requirement in still_unhealthy)
        raise BootstrapError(
            "Automatic dependency installation completed, but required packages are still missing or unusable: "
            f"{still_unhealthy_names}. Install them manually with "
            f"{shlex.join([sys.executable, '-m', 'pip', 'install', '-r', str(requirements_path)])}."
        )


def bootstrap_runtime(argv: list[str] | None = None) -> None:
    target_argv = sys.argv if argv is None else None
    raw_argv = list(sys.argv if argv is None else argv)
    cleaned_argv, confirm_install = strip_confirm_install_flag(raw_argv)
    if target_argv is not None:
        target_argv[:] = cleaned_argv

    if has_help_flag(cleaned_argv[1:]):
        return

    try:
        ensure_requirements_installed(cleaned_argv, confirm_install)
    except Exception as exc:  # noqa: BLE001
        fail_json(str(exc))
