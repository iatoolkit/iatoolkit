import click
import logging
from iatoolkit import IAToolkit
from services.dispatcher_service import Dispatcher
from services.profile_service import ProfileService

def register_core_commands(app):
    """Registra los comandos CLI del núcleo de IAToolkit."""
    
    @app.cli.command("setup-all-companies")
    def setup_all_companies():
        """🗄️ Inicializa todas las compañías registradas en la base de datos."""
        try:
            dispatcher = IAToolkit.get_instance().get_injector().get(Dispatcher)
            click.echo("🚀 Inicializando base de datos y compañías...")
            dispatcher.setup_all_companies()
            click.echo("✅ Base de datos y compañías inicializadas correctamente.")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ Error: {e}")

    @app.cli.command("setup-company")
    @click.argument("company_short_name")
    def setup_company(company_short_name: str):
        """⚙️ Genera una nueva API key para una compañía ya registrada."""
        try:
            dispatcher = IAToolkit.get_instance().get_injector().get(Dispatcher)
            dispatcher.setup_all_companies()
            profile_service = IAToolkit.get_instance().get_injector().get(ProfileService)
            click.echo(f"🔑 Generando API key para '{company_short_name}'...")
            result = profile_service.new_api_key(company_short_name)

            if 'error' in result:
                click.echo(f"❌ Error: {result['error']}")
                click.echo("👉 Asegúrate de que el nombre de la compañía es correcto y está registrada.")
            else:
                click.echo("✅ ¡Configuración lista! Agrega esta variable a tu entorno:")
                click.echo(f"IATOOLKIT_API_KEY={result['api-key']}")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ Ocurrió un error inesperado durante la configuración: {e}")

    @app.cli.command("encrypt-key")
    @click.argument("key")
    def api_key(key: str):
        from common.util import Utility

        util = IAToolkit.get_instance().get_injector().get(Utility)
        try:
            encrypt_key = util.encrypt_key(key)
            click.echo(f'la clave encriptada es: {encrypt_key} \n')
        except Exception as e:
            logging.exception(e)
            click.echo(f"Error: {str(e)}")

    @app.cli.command("exec-tasks")
    @click.argument("company_short_name")
    def exec_pending_tasks(company_short_name: str):
        from services.tasks_service import TaskService
        task_service = IAToolkit.get_instance().get_injector().get(TaskService)

        try:
            result = task_service.trigger_pending_tasks(company_short_name)
            click.echo(result['message'])
        except Exception as e:
            logging.exception(e)
            click.echo(f"Error: {str(e)}")


