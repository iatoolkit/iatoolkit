# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from flask import Blueprint, render_template, redirect, flash, url_for,send_from_directory, current_app
from common.session_manager import SessionManager
from flask import jsonify
from views.history_view import HistoryView
import os


def logout(company_short_name: str):
    SessionManager.clear()
    flash("Has cerrado sesión correctamente", "info")
    if company_short_name:
        return redirect(url_for('login', company_short_name=company_short_name))
    else:
        return redirect(url_for('home'))


# 2. Define a function to register all views to the Blueprint
def register_views(injector, app):

    from views.llmquery_view import LLMQueryView
    from views.tasks_view import TaskView
    from views.tasks_review_view import TaskReviewView
    from views.home_view import HomeView
    from views.chat_view import ChatView
    from views.login_view import LoginView
    from views.external_chat_login_view import ExternalChatLoginView
    from views.select_company_view import SelectCompanyView
    from views.signup_view import SignupView
    from views.verify_user_view import VerifyAccountView
    from views.forgot_password_view import ForgotPasswordView
    from views.change_password_view import ChangePasswordView
    from views.file_store_view import FileStoreView
    from views.url_simulation_view import URLSimulationView
    from views.user_feedback_view import UserFeedbackView
    from views.prompt_view import PromptView
    from views.chat_token_request_view import ChatTokenRequestView
    from views.chat_info_view import ChatInfoView
    from views.external_login_view import ExternalLoginView
    from views.download_file_view import DownloadFileView

    app.add_url_rule('/', view_func=HomeView.as_view('home'))

    # main chat for iatoolkit front
    app.add_url_rule('/<company_short_name>/chat', view_func=ChatView.as_view('chat'))

    # front if the company internal portal
    app.add_url_rule('/<company_short_name>/chat_login', view_func=ExternalChatLoginView.as_view('external_chat_login'))
    app.add_url_rule('/<company_short_name>/external_login/<external_user_id>', view_func=ExternalLoginView.as_view('external_login'))
    app.add_url_rule('/auth/chat_token', view_func=ChatTokenRequestView.as_view('chat-token'))

    # main pages for the iatoolkit frontend
    app.add_url_rule('/<company_short_name>/login', view_func=LoginView.as_view('login'))
    app.add_url_rule('/<company_short_name>/signup',view_func=SignupView.as_view('signup'))
    app.add_url_rule('/<company_short_name>/logout', 'logout', logout)
    app.add_url_rule('/logout', 'logout', logout)
    app.add_url_rule('/<company_short_name>/verify/<token>', view_func=VerifyAccountView.as_view('verify_account'))
    app.add_url_rule('/<company_short_name>/forgot-password', view_func=ForgotPasswordView.as_view('forgot_password'))
    app.add_url_rule('/<company_short_name>/change-password/<token>', view_func=ChangePasswordView.as_view('change_password'))
    app.add_url_rule('/<company_short_name>/select_company', view_func=SelectCompanyView.as_view('select_company'))

    # this are backend endpoints mainly
    app.add_url_rule('/<company_short_name>/llm_query', view_func=LLMQueryView.as_view('llm_query'))
    app.add_url_rule('/<company_short_name>/feedback', view_func=UserFeedbackView.as_view('feedback'))
    app.add_url_rule('/<company_short_name>/prompts', view_func=PromptView.as_view('prompt'))
    app.add_url_rule('/<company_short_name>/history', view_func=HistoryView.as_view('history'))
    app.add_url_rule('/tasks', view_func=TaskView.as_view('tasks'))
    app.add_url_rule('/tasks/review/<int:task_id>', view_func=TaskReviewView.as_view('tasks-review'))
    app.add_url_rule('/load', view_func=FileStoreView.as_view('load'))
    app.add_url_rule('/chat-info', view_func=ChatInfoView.as_view('chat-info'))

    # for simulation of external endpoints
    app.add_url_rule(
        '/simulated-url/<company_short_name>/<object_name>',
        view_func=URLSimulationView.as_view('simulated-url')
    )

    app.add_url_rule(
        '/about',  # URL de la ruta
        view_func=lambda: render_template('about.html'))

    app.add_url_rule('/version', 'version',
                     lambda: jsonify({"version": app.config['VERSION']}))

    app.add_url_rule('/<company_short_name>/<external_user_id>/download-file/<path:filename>',
                     view_func=DownloadFileView.as_view('download-file'))

    @app.route('/download/<path:filename>')
    def download_file(filename):
        temp_dir = os.path.join(current_app.root_path, 'static', 'temp')
        return send_from_directory(temp_dir, filename, as_attachment=True)


