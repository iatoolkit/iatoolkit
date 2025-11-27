# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import click
import logging
import datetime
import json
import jwt
from .iatoolkit import IAToolkit
from iatoolkit.services.profile_service import ProfileService
from flask.cli import AppGroup
import os


# CLI group for license management
license_cli = AppGroup('license')

@license_cli.command("generate")
@click.argument("client_name")
@click.option("--plan", default="enterprise", help="Plan name (enterprise, pro, community)")
@click.option("--max-companies", default=10, help="Max companies allowed (-1 for unlimited)")
@click.option("--max-tools", default=50, help="Max tools per company allowed (-1 for unlimited)")
@click.option("--days", default=365, help="Validity in days")
@click.option("--private-key", default="private_key.pem", help="Path to RSA private key")
def generate_license(client_name, plan, max_companies, max_tools, days, private_key):
    """Generates a signed Enterprise license token."""

    # 1. check that we have the private key
    if not os.path.exists(private_key):
        click.echo(f"❌ Error: can't found private key: '{private_key}'.")
        click.echo("   This command can only be executed by the administrator with the RSA private key.")
        return

    try:
        with open(private_key, 'r') as f:
            priv_key_content = f.read()

        # 2. build the payload
        payload = {
            "client_name": client_name,
            "plan": plan,
            "limits": {
                "max_companies": int(max_companies),
                "max_tools": int(max_tools)
            },
            "iat": datetime.datetime.utcnow(),
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=days)
        }

        # 3. sign the payload with the private key
        token = jwt.encode(payload, priv_key_content, algorithm="ES256")

        click.echo("\n✅ License Generated Successfully\n")
        click.echo(f"Client: {client_name}")
        click.echo(f"Plan: {plan}")
        click.echo(f"Limits: Companies={max_companies}, Tools={max_tools}")
        click.echo(f"Expires: {payload['exp']} (in {days} days)\n")
        click.echo("👇 Copy this token and send it to the client (Variable: IAT_LICENSE_KEY) 👇")
        click.echo("-" * 60)
        click.echo(token)
        click.echo("-" * 60)

    except Exception as e:
        click.echo(f"❌ Error generating license: {str(e)}")


@license_cli.command("verify")
@click.argument("token")
def verify_license(token):
    """Verifies a license using the internal public key."""
    # Use the real service to validate as the app would
    from iatoolkit.services.license_service import LicenseService

    # Mock the environment so LicenseService reads this token
    os.environ['IAT_LICENSE_KEY'] = token

    try:
        # Get instance via injector to ensure correct configuration
        svc = IAToolkit.get_instance().get_injector().get(LicenseService)

        # Force load/validation
        limits = svc.limits

        click.echo("\n✅ License is Valid")
        click.echo(json.dumps(limits, indent=2, default=str))
    except Exception as e:
        click.echo(f"\n❌ License invalid: {str(e)}")


def register_core_commands(app):
    """Registra los comandos CLI del núcleo de IAToolkit."""

    app.cli.add_command(license_cli)

    @app.cli.command("api-key")
    @click.argument("company_short_name")
    def api_key(company_short_name: str):
        """⚙️ Genera una nueva API key para una compañía ya registrada."""
        try:
            profile_service = IAToolkit.get_instance().get_injector().get(ProfileService)
            click.echo(f"🔑 Generating API-KEY for company: '{company_short_name}'...")
            result = profile_service.new_api_key(company_short_name)

            if 'error' in result:
                click.echo(f"❌ Error: {result['error']}")
                click.echo("👉 Make sure the company is registered and valid.")
            else:
                click.echo("✅ ¡Api-key is ready! add this variable to your environment:")
                click.echo(f"IATOOLKIT_API_KEY='{result['api-key']}'")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ unexpectd error during the configuration: {e}")

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

    @app.cli.command("exec-tasks")
    @click.argument("company_short_name")
    def exec_pending_tasks(company_short_name: str):
        from iatoolkit.services.tasks_service import TaskService
        task_service = IAToolkit.get_instance().get_injector().get(TaskService)

        try:
            result = task_service.trigger_pending_tasks(company_short_name)
            click.echo(result['message'])
        except Exception as e:
            logging.exception(e)
            click.echo(f"Error: {str(e)}")


