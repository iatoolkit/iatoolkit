# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import render_template, redirect, flash, url_for,send_from_directory, current_app, abort
from iatoolkit.common.session_manager import SessionManager
from flask import jsonify
from iatoolkit.views.history_api_view import HistoryApiView
import os


def logout(company_short_name: str):
    SessionManager.clear()
    flash("Has cerrado sesión correctamente", "info")
    return redirect(url_for('index', company_short_name=company_short_name))


# this function register all the views
def register_views(injector, app):

    from iatoolkit.views.index_view import IndexView
    from iatoolkit.views.init_context_api_view import InitContextApiView
    from iatoolkit.views.llmquery_api_view import LLMQueryApiView
    from iatoolkit.views.tasks_view import TaskView
    from iatoolkit.views.tasks_review_view import TaskReviewView
    from iatoolkit.views.login_simulation_view import LoginSimulationView
    from iatoolkit.views.signup_view import SignupView
    from iatoolkit.views.verify_user_view import VerifyAccountView
    from iatoolkit.views.forgot_password_view import ForgotPasswordView
    from iatoolkit.views.change_password_view import ChangePasswordView
    from iatoolkit.views.file_store_api_view import FileStoreApiView
    from iatoolkit.views.user_feedback_api_view import UserFeedbackApiView
    from iatoolkit.views.prompt_api_view import PromptApiView
    from iatoolkit.views.chat_token_request_view import ChatTokenRequestView
    from iatoolkit.views.login_view import LoginView, FinalizeContextView
    from iatoolkit.views.external_login_view import ExternalLoginView, RedeemTokenApiView

    # iatoolkit home page
    app.add_url_rule('/<company_short_name>', view_func=IndexView.as_view('index'))

    # login for the iatoolkit integrated frontend
    app.add_url_rule('/<company_short_name>/login', view_func=LoginView.as_view('login'))

    # this is the login for external users
    app.add_url_rule('/<company_short_name>/external_login',
                     view_func=ExternalLoginView.as_view('external_login'))

    # this endpoint is called when onboarding_shell finish the context load
    app.add_url_rule(
        '/<company_short_name>/finalize',
        view_func=FinalizeContextView.as_view('finalize_no_token')
    )

    app.add_url_rule(
        '/<company_short_name>/finalize/<token>',
        view_func=FinalizeContextView.as_view('finalize_with_token')
    )

    # this endpoint is called by the JS for changing the token for a session
    app.add_url_rule('/<string:company_short_name>/api/redeem_token',
                     view_func = RedeemTokenApiView.as_view('redeem_token'))

    # this endpoint is for requesting a chat token for external users
    app.add_url_rule('/auth/chat_token',
                     view_func=ChatTokenRequestView.as_view('chat-token'))

    # init (reset) the company context (with api-key)
    app.add_url_rule('/<company_short_name>/api/init-context',
                     view_func=InitContextApiView.as_view('init-context'))

    # register new user, account verification and forgot password
    app.add_url_rule('/<company_short_name>/signup',view_func=SignupView.as_view('signup'))
    app.add_url_rule('/<company_short_name>/logout', 'logout', logout)
    app.add_url_rule('/logout', 'logout', logout)
    app.add_url_rule('/<company_short_name>/verify/<token>', view_func=VerifyAccountView.as_view('verify_account'))
    app.add_url_rule('/<company_short_name>/forgot-password', view_func=ForgotPasswordView.as_view('forgot_password'))
    app.add_url_rule('/<company_short_name>/change-password/<token>', view_func=ChangePasswordView.as_view('change_password'))

    # main chat query, used by the JS in the browser (with credentials)
    # can be used also for executing iatoolkit prompts
    app.add_url_rule('/<company_short_name>/api/llm_query', view_func=LLMQueryApiView.as_view('llm_query_api'))

    # open the promt directory
    app.add_url_rule('/<company_short_name>/api/prompts', view_func=PromptApiView.as_view('prompt'))

    # feedback and history
    app.add_url_rule('/<company_short_name>/api/feedback', view_func=UserFeedbackApiView.as_view('feedback'))
    app.add_url_rule('/<company_short_name>/api/history', view_func=HistoryApiView.as_view('history'))

    # tasks management endpoints: create task, and review answer
    app.add_url_rule('/tasks', view_func=TaskView.as_view('tasks'))
    app.add_url_rule('/tasks/review/<int:task_id>', view_func=TaskReviewView.as_view('tasks-review'))

    # this endpoint is for upload documents into the vector store (api-key)
    app.add_url_rule('/api/load', view_func=FileStoreApiView.as_view('load_api'))


    @app.route('/download/<path:filename>')
    def download_file(filename):
        """
        Esta vista sirve un archivo previamente generado desde el directorio
        configurado en IATOOLKIT_DOWNLOAD_DIR.
        """
        # Valida que la configuración exista
        if 'IATOOLKIT_DOWNLOAD_DIR' not in current_app.config:
            abort(500, "Error de configuración: IATOOLKIT_DOWNLOAD_DIR no está definido.")

        download_dir = current_app.config['IATOOLKIT_DOWNLOAD_DIR']

        try:
            return send_from_directory(
                download_dir,
                filename,
                as_attachment=True  # Fuerza la descarga en lugar de la visualización
            )
        except FileNotFoundError:
            abort(404)

    # login testing
    app.add_url_rule('/<company_short_name>/login_test',
                     view_func=LoginSimulationView.as_view('login_test'))

    app.add_url_rule(
        '/about',  # URL de la ruta
        view_func=lambda: render_template('about.html'))

    app.add_url_rule('/version', 'version',
                     lambda: jsonify({"iatoolkit_version": current_app.config.get('VERSION', 'N/A')}))


    # hacer que la raíz '/' vaya al home de iatoolkit
    @app.route('/')
    def root_redirect():
        return redirect(url_for('index', company_short_name='sample_company'))


