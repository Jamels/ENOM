"""Small CLI for manifest integrity checks."""

from pathlib import Path

import typer

from twinworld.records import read_jsonl, validate_records

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate_manifest(manifest: Path, root: Path = Path(".")) -> None:
    """Validate JSONL provenance fields and patch-file presence."""
    records = read_jsonl(manifest)
    errors = validate_records(records, root)
    if errors:
        for error in errors:
            typer.echo(error, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"valid: {len(records)} records")
