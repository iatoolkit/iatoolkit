# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from flask import Blueprint, render_template, redirect, flash, url_for,send_from_directory, current_app
from common.session_manager import SessionManager
from flask import jsonify
from views.history_view import HistoryView
import os

# 1. Create a Blueprint
main_bp = Blueprint('', __name__)

def logout(company_short_name: str):
    SessionManager.clear()
    flash("Has cerrado sesión correctamente", "info")
    if company_short_name:
        return redirect(url_for('login', company_short_name=company_short_name))
    else:
        return redirect(url_for('home'))



# 2. Define a function to register all views to the Blueprint
def register_views(injector):

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

    # Get instances from the injector
    home_view = injector.get(HomeView)
    chat_view = injector.get(ChatView)
    external_chat_login_view = injector.get(ExternalChatLoginView)
    chat_token_request_view = injector.get(ChatTokenRequestView)
    login_view = injector.get(LoginView)
    signup_view = injector.get(SignupView)
    verify_account_view = injector.get(VerifyAccountView)
    forgot_password_view = injector.get(ForgotPasswordView)
    change_password_view = injector.get(ChangePasswordView)
    select_company_view = injector.get(SelectCompanyView)
    llmquery_view = injector.get(LLMQueryView)
    user_feedback_view = injector.get(UserFeedbackView)
    prompt_view = injector.get(PromptView)
    history_view = injector.get(HistoryView)
    tasks_view = injector.get(TaskView)
    task_review_view = injector.get(TaskReviewView)
    file_store_view = injector.get(FileStoreView)
    external_login_view = injector.get(ExternalLoginView)
    url_simulation_view = injector.get(URLSimulationView)
    download_file_view = injector.get(DownloadFileView)
    chat_info_view = injector.get(ChatInfoView)

    main_bp.add_url_rule('/', view_func=home_view.as_view('home'))

    # main chat for iatoolkit front
    main_bp.add_url_rule('/<company_short_name>/chat', view_func=chat_view.as_view('chat'))

    # front if the company internal portal
    main_bp.add_url_rule('/<company_short_name>/chat_login', view_func=external_chat_login_view.as_view('external_chat_login'))
    main_bp.add_url_rule('/<company_short_name>/external_login/<external_user_id>', view_func=external_login_view.as_view('external_login'))
    main_bp.add_url_rule('/auth/chat_token', view_func=chat_token_request_view.as_view('chat-token'))

    # main pages for the iatoolkit frontend
    main_bp.add_url_rule('/<company_short_name>/login', view_func=login_view.as_view('login'))
    main_bp.add_url_rule('/<company_short_name>/signup',view_func=signup_view.as_view('signup'))
    main_bp.add_url_rule('/<company_short_name>/logout', 'logout', logout)
    main_bp.add_url_rule('/logout', 'logout', logout)
    main_bp.add_url_rule('/<company_short_name>/verify/<token>', view_func=verify_account_view.as_view('verify_account'))
    main_bp.add_url_rule('/<company_short_name>/forgot-password', view_func=forgot_password_view.as_view('forgot_password'))
    main_bp.add_url_rule('/<company_short_name>/change-password/<token>', view_func=change_password_view.as_view('change_password'))
    main_bp.add_url_rule('/<company_short_name>/select_company', view_func=select_company_view.as_view('select_company'))

    # this are backend endpoints mainly
    main_bp.add_url_rule('/<company_short_name>/llm_query', view_func=llmquery_view.as_view('llm_query'))
    main_bp.add_url_rule('/<company_short_name>/feedback', view_func=user_feedback_view.as_view('feedback'))
    main_bp.add_url_rule('/<company_short_name>/prompts', view_func=prompt_view.as_view('prompt'))
    main_bp.add_url_rule('/<company_short_name>/history', view_func=history_view.as_view('history'))
    main_bp.add_url_rule('/tasks', view_func=tasks_view.as_view('tasks'))
    main_bp.add_url_rule('/tasks/review/<int:task_id>', view_func=task_review_view.as_view('tasks-review'))
    main_bp.add_url_rule('/load', view_func=file_store_view.as_view('load'))
    main_bp.add_url_rule('/chat-info', view_func=chat_info_view.as_view('chat-info'))

    # for simulation of external endpoints
    main_bp.add_url_rule(
        '/simulated-url/<company_short_name>/<object_name>',
        view_func=url_simulation_view.as_view('simulated-url')
    )

    main_bp.add_url_rule(
        '/about',  # URL de la ruta
        view_func=lambda: render_template('about.html'))

    main_bp.add_url_rule('/<company_short_name>/<external_user_id>/download-file/<path:filename>',
                     view_func=download_file_view.as_view('download-file'))



@main_bp.route('/about')
def about():
    return render_template('about.html', version=current_app.config.get('VERSION'))

@main_bp.route('/version')
def version():
    return jsonify({"version": ''})

@main_bp.route('/<company_short_name>/logout')
def logout(company_short_name: str):
    SessionManager.clear()
    flash("Has cerrado sesión correctamente", "info")
    if company_short_name:
        return redirect(url_for('login', company_short_name=company_short_name))
    else:
        return redirect(url_for('home'))

@main_bp.route('/download/<path:filename>')
def download_file(filename):
    temp_dir = os.path.join(current_app.root_path, 'static', 'temp')
    return send_from_directory(temp_dir, filename, as_attachment=True)

