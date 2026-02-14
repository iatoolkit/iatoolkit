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
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpectd error during the configuration: {e}")

    @app.cli.command("init-company")
    @click.argument("company_short_name")
    def init_company(company_short_name: str):
        """⚙️ Bootstrap a new company."""
        try:
            current_iatoolkit().bootstrap_company(company_short_name)
            click.echo(f"✅ Company {company_short_name} initialized successfully!")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpected error during bootstrap: {e}")

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


