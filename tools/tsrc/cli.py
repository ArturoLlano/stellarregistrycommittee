from __future__ import annotations

import argparse
import sys

from tools.tsrc.config import get_paths
from tools.tsrc.entries.io import read_entry_from_public
from tools.tsrc.entries.validate import validate_entry_or_raise
from tools.tsrc.certificates.generate import (
    generate_certificate_pdf_for_id,
    generate_all_certificates,
)


def _cmd_validate(args: argparse.Namespace) -> int:
    _ = get_paths()  # ensure paths resolve early
    entry = read_entry_from_public(args.id)
    validate_entry_or_raise(entry, strict_qr=True)
    print(f"OK: entry is valid: {args.id}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    pdf_path = generate_certificate_pdf_for_id(
        entry_id=args.id,
        force=args.force,
        open_after=not args.no_open,
    )
    print(str(pdf_path))
    return 0


def _cmd_generate_all(args: argparse.Namespace) -> int:
    results = generate_all_certificates(
        force=args.force,
        open_after=False,  # generating many files; do not auto-open
        only_missing=not args.all,
    )

    print(f"Generated: {len(results.generated)}")
    print(f"Skipped:   {len(results.skipped)}")
    print(f"Failed:    {len(results.failed)}")

    if results.failed:
        print("\nFailures:")
        for item in results.failed:
            print(f"- {item.entry_id}: {item.error}")

        # Non-zero exit code if any failures
        return 2

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tsrc",
        description=(
            "TSRC local tool (Phase 1): validate entry JSON and generate PDF certificates.\n\n"
            "Run from repo root, for example:\n"
            "  python -m tools.tsrc.cli generate SAO-12345-AB12\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate one entry JSON.")
    p_val.add_argument("id", help="Entry ID, e.g. SAO-12345-AB12")
    p_val.set_defaults(func=_cmd_validate)

    p_gen = sub.add_parser("generate", help="Generate a PDF certificate for one entry.")
    p_gen.add_argument("id", help="Entry ID, e.g. SAO-12345-AB12")
    p_gen.add_argument("--force", action="store_true", help="Regenerate even if PDF exists.")
    p_gen.add_argument("--no-open", action="store_true", help="Do not auto-open the PDF.")
    p_gen.set_defaults(func=_cmd_generate)

    p_all = sub.add_parser("generate-all", help="Generate certificates for entries in /public/data/entries.")
    p_all.add_argument("--force", action="store_true", help="Regenerate even if PDF exists.")
    p_all.add_argument(
        "--all",
        action="store_true",
        help="Generate for all entries (default: only missing).",
    )
    p_all.set_defaults(func=_cmd_generate_all)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
