# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import click
import logging
from iatoolkit.core import IAToolkit, current_iatoolkit
from iatoolkit.services.api_key_service import ApiKeyService


def register_core_commands(app):
    """Registra los comandos CLI del núcleo de IAToolkit."""

    @app.cli.command("api-key")
    @click.argument("company_short_name")
    @click.argument("key_name")
    def api_key(company_short_name: str, key_name: str):
        """⚙️ Genera una nueva API key para una compañía ya registrada."""
        try:
            api_key_service = IAToolkit.get_instance().get_injector().get(ApiKeyService)
            click.echo(f"🔑 Generating API-KEY for company: '{company_short_name}'...")
            result = api_key_service.new_api_key(company_short_name, key_name)

            if 'error' in result:
                click.echo(f"❌ Error: {result['error']}")
                click.echo("👉 Make sure the company is registered and valid.")
            else:
                click.echo("✅ ¡Api-key is ready! add this variable to your environment:")
                click.echo(f"IATOOLKIT_API_KEY='{result['api-key']}'")
                click.echo("⚠️  Copy it now: only its hash is stored, it will not be shown again.")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpectd error during the configuration: {e}")

    @app.cli.command("init-company")
    @click.argument("company_short_name")
    def init_company(company_short_name: str):
        """⚙️ Bootstrap or repair an installation for a company."""
        try:
            click.echo(f"⚙️ Bootstrapping installation for '{company_short_name}'...")
            result = current_iatoolkit().bootstrap_defaults(company_short_name)
            errors = result.get("errors", [])
            if errors:
                click.echo("⚠️ Configuration validation reported issues:")
                for error in errors:
                    click.echo(f" - {error}")
                raise click.ClickException(
                    f"bootstrap completed with configuration errors for '{company_short_name}'"
                )

            click.echo(f"✅ Company {company_short_name} initialized successfully!")
        except click.ClickException:
            raise
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpected error during bootstrap: {e}")

    @app.cli.command("privacy-erase")
    @click.argument("company_short_name")
    @click.argument("identifier")
    @click.option("--requested-by", required=True, help="Who asked for the erasure (kept in the receipt).")
    @click.option("--dry-run", is_flag=True, help="Count what would change and change nothing.")
    @click.option("--yes", is_flag=True, help="Erase without asking for confirmation.")
    def privacy_erase(company_short_name: str, identifier: str, requested_by: str, dry_run: bool, yes: bool):
        """🧹 Erase a person from a company: their content goes, records keep a pseudonym (BL-034, R9)."""
        from iatoolkit.services.privacy.erasure_service import PrivacyErasureService
        service = IAToolkit.get_instance().get_injector().get(PrivacyErasureService)
        preview = service.erase(company_short_name, identifier, requested_by=requested_by, dry_run=True)
        _echo_erasure(preview)
        if dry_run:
            return
        if not preview["rows"]:
            click.echo("Nothing to erase.")
            return
        if not yes:
            click.confirm(f"Erase this person from '{company_short_name}'? This cannot be undone", abort=True)
        result = service.erase(company_short_name, identifier, requested_by=requested_by)
        click.echo(f"✅ Erased. Receipt #{result.get('receipt_id')}, pseudonym {result['pseudonym']}, "
                   f"{result['rows']} rows, {result['files']} files.")

    @app.cli.command("privacy-retention")
    @click.argument("company_short_name", required=False)
    @click.option("--dry-run", is_flag=True, help="Count what would change and change nothing.")
    def privacy_retention(company_short_name: str | None, dry_run: bool):
        """🧹 Apply each company's privacy.retention: old conversations go, old audit is pseudonymized (BL-034, R9)."""
        from iatoolkit.repositories.profile_repo import ProfileRepo
        from iatoolkit.services.privacy.retention_service import PrivacyRetentionService
        injector = IAToolkit.get_instance().get_injector()
        service = injector.get(PrivacyRetentionService)
        names = [company_short_name] if company_short_name else [
            company.short_name for company in injector.get(ProfileRepo).get_companies()]
        for name in names:
            result = service.apply(name, dry_run=dry_run)
            click.echo(f"{name}: {result['status']}, {result['rows']} rows, {result['files']} files")
            for key, count in result["summary"].items():
                click.echo(f"  {key}: {count}")

    @app.cli.command("encrypt-key")
    @click.argument("key")
    def encrypt_llm_api_key(key: str):
        from iatoolkit.common.util import Utility

        util = IAToolkit.get_instance().get_injector().get(Utility)
        try:
            encrypt_key = util.encrypt_key(key)
            click.echo(f'la api-key del LLM encriptada es: {encrypt_key} \n')
        except Exception as e:
            logging.exception(e)
            click.echo(f"Error: {str(e)}")


def _echo_erasure(result: dict) -> None:
    verb = "would change" if result.get("dry_run") else "changed"
    click.echo(f"{result['company_short_name']}: {verb} {result['rows']} rows, "
               f"{result['files']} files; account: {result['account']}; pseudonym {result['pseudonym']}")
    for key, count in result["summary"].items():
        click.echo(f"  {key}: {count}")
