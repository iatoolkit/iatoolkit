# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import click
import logging
from iatoolkit.core import IAToolkit
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.tool_service import ToolService


def register_core_commands(app):
    """Registra los comandos CLI del núcleo de IAToolkit."""

    @app.cli.command("api-key")
    @click.argument("company_short_name")
    @click.argument("key_name")
    def api_key(company_short_name: str, key_name: str):
        """⚙️ Genera una nueva API key para una compañía ya registrada."""
        try:
            profile_service = IAToolkit.get_instance().get_injector().get(ProfileService)
            click.echo(f"🔑 Generating API-KEY for company: '{company_short_name}'...")
            result = profile_service.new_api_key(company_short_name, key_name)

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
            prompt_service = IAToolkit.get_instance().get_injector().get(PromptService)
            click.echo(f"🔑 Bootstrap company: '{company_short_name}'...")
            result = prompt_service.register_system_prompts(company_short_name)

            if result:
                click.echo("✅ System Prompts registered successfully!")

            tool_service = IAToolkit.get_instance().get_injector().get(ToolService)
            result = tool_service.register_system_tools()
            if result:
                click.echo("✅ System Tools registered successfully!")


        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpected error during the configuration: {e}")

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



