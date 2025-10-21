# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import render_template, redirect, flash, url_for,send_from_directory, current_app, abort
from iatoolkit.common.session_manager import SessionManager
from flask import jsonify
from iatoolkit.views.history_view import HistoryView
import os


def logout(company_short_name: str):
    SessionManager.clear()
    flash("Has cerrado sesión correctamente", "info")
    return redirect(url_for('index', company_short_name=company_short_name))


# this function register all the views
def register_views(injector, app):

    from iatoolkit.views.index_view import IndexView
    from iatoolkit.views.init_context_view import InitContextView
    from iatoolkit.views.llmquery_view import LLMQueryView
    from iatoolkit.views.tasks_view import TaskView
    from iatoolkit.views.tasks_review_view import TaskReviewView
    from iatoolkit.views.login_test_view import LoginTest
    from iatoolkit.views.login_view import LoginView, InitiateLoginView
    from iatoolkit.views.external_login_view import InitiateExternalChatView, ExternalChatLoginView
    from iatoolkit.views.signup_view import SignupView
    from iatoolkit.views.verify_user_view import VerifyAccountView
    from iatoolkit.views.forgot_password_view import ForgotPasswordView
    from iatoolkit.views.change_password_view import ChangePasswordView
    from iatoolkit.views.file_store_view import FileStoreView
    from iatoolkit.views.user_feedback_view import UserFeedbackView
    from iatoolkit.views.prompt_view import PromptView
    from iatoolkit.views.chat_token_request_view import ChatTokenRequestView

    # iatoolkit home page
    app.add_url_rule('/<company_short_name>', view_func=IndexView.as_view('index'))

    # init (reset) the company context (with api-key)
    app.add_url_rule('/<company_short_name>//init-context',
                         view_func=InitContextView.as_view('init-context'))

    # this functions are for login external users (with api-key)
    # only the first one should be used from an external app
    app.add_url_rule('/<company_short_name>/initiate_external_chat',
                     view_func=InitiateExternalChatView.as_view('initiate_external_chat'))
    app.add_url_rule('/<company_short_name>/external_login',
                     view_func=ExternalChatLoginView.as_view('external_login'))

    # this endpoint is for requesting a chat token for external users
    app.add_url_rule('/auth/chat_token',
                     view_func=ChatTokenRequestView.as_view('chat-token'))

    # login for the iatoolkit integrated frontend
    # this is the main login endpoint for the frontend
    app.add_url_rule('/<company_short_name>/chat', view_func=InitiateLoginView.as_view('chat'))
    app.add_url_rule('/<company_short_name>/login', view_func=LoginView.as_view('login'))

    # register new user, account verification and forgot password
    app.add_url_rule('/<company_short_name>/signup',view_func=SignupView.as_view('signup'))
    app.add_url_rule('/<company_short_name>/logout', 'logout', logout)
    app.add_url_rule('/logout', 'logout', logout)
    app.add_url_rule('/<company_short_name>/verify/<token>', view_func=VerifyAccountView.as_view('verify_account'))
    app.add_url_rule('/<company_short_name>/forgot-password', view_func=ForgotPasswordView.as_view('forgot_password'))
    app.add_url_rule('/<company_short_name>/change-password/<token>', view_func=ChangePasswordView.as_view('change_password'))

    # main chat query, used by the JS in the browser (with credentials)
    # can be used also for executing iatoolkit prompts
    app.add_url_rule('/<company_short_name>/llm_query', view_func=LLMQueryView.as_view('llm_query'))

    # chat buttons are here

    # open the promt directory
    app.add_url_rule('/<company_short_name>/prompts', view_func=PromptView.as_view('prompt'))

    # feedback and history
    app.add_url_rule('/<company_short_name>/feedback', view_func=UserFeedbackView.as_view('feedback'))
    app.add_url_rule('/<company_short_name>/history', view_func=HistoryView.as_view('history'))

    # tasks management endpoints: create task, and review answer
    app.add_url_rule('/tasks', view_func=TaskView.as_view('tasks'))
    app.add_url_rule('/tasks/review/<int:task_id>', view_func=TaskReviewView.as_view('tasks-review'))

    # this endpoint is for upload documents into the vector store (api-key)
    app.add_url_rule('/load', view_func=FileStoreView.as_view('load'))


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

    # login testing (old home page)
    app.add_url_rule('/login_test', view_func=LoginTest.as_view('login_test'))

    app.add_url_rule(
        '/about',  # URL de la ruta
        view_func=lambda: render_template('about.html'))

    app.add_url_rule('/version', 'version',
                     lambda: jsonify({"iatoolkit_version": current_app.config.get('VERSION', 'N/A')}))


    # hacer que la raíz '/' vaya al home de iatoolkit
    @app.route('/')
    def root_redirect():
        return redirect(url_for('index', company_short_name='sample_company'))


