# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import render_template, redirect, url_for,send_from_directory, current_app, abort
from flask import jsonify


# this function register all the views
def register_views(app):

    from iatoolkit.views.index_view import IndexView
    from iatoolkit.views.init_context_api_view import InitContextApiView
    from iatoolkit.views.llmquery_api_view import LLMQueryApiView
    from iatoolkit.views.tasks_api_view import TaskApiView
    from iatoolkit.views.tasks_review_api_view import TaskReviewApiView
    from iatoolkit.views.login_simulation_view import LoginSimulationView
    from iatoolkit.views.signup_view import SignupView
    from iatoolkit.views.verify_user_view import VerifyAccountView
    from iatoolkit.views.forgot_password_view import ForgotPasswordView
    from iatoolkit.views.change_password_view import ChangePasswordView
    from iatoolkit.views.load_document_api_view import LoadDocumentApiView
    from iatoolkit.views.user_feedback_api_view import UserFeedbackApiView
    from iatoolkit.views.prompt_api_view import PromptApiView
    from iatoolkit.views.history_api_view import HistoryApiView
    from iatoolkit.views.help_content_api_view import HelpContentApiView
    from iatoolkit.views.profile_api_view import UserLanguageApiView
    from iatoolkit.views.embedding_api_view import EmbeddingApiView
    from iatoolkit.views.login_view import LoginView, FinalizeContextView
    from iatoolkit.views.external_login_view import ExternalLoginView, RedeemTokenApiView
    from iatoolkit.views.logout_api_view import LogoutApiView
    from iatoolkit.views.home_view import HomeView
    from iatoolkit.views.static_page_view import StaticPageView

    # iatoolkit home page
    app.add_url_rule('/', view_func=IndexView.as_view('index'))

    # company home view
    app.add_url_rule('/<company_short_name>/home', view_func=HomeView.as_view('home'))

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

    app.add_url_rule(
        '/api/profile/language',
        view_func=UserLanguageApiView.as_view('user_language_api')
    )

    # logout
    app.add_url_rule('/<company_short_name>/api/logout',
                     view_func=LogoutApiView.as_view('logout'))

    # this endpoint is called by the JS for changing the token for a session
    app.add_url_rule('/<string:company_short_name>/api/redeem_token',
                     view_func = RedeemTokenApiView.as_view('redeem_token'))

    # init (reset) the company context
    app.add_url_rule('/<company_short_name>/api/init-context',
                     view_func=InitContextApiView.as_view('init-context'),
                     methods=['POST', 'OPTIONS'])

    # register new user, account verification and forgot password
    app.add_url_rule('/<company_short_name>/signup',view_func=SignupView.as_view('signup'))
    app.add_url_rule('/<company_short_name>/verify/<token>', view_func=VerifyAccountView.as_view('verify_account'))
    app.add_url_rule('/<company_short_name>/forgot-password', view_func=ForgotPasswordView.as_view('forgot_password'))
    app.add_url_rule('/<company_short_name>/change-password/<token>', view_func=ChangePasswordView.as_view('change_password'))

    # main chat query, used by the JS in the browser (with credentials)
    # can be used also for executing iatoolkit prompts
    app.add_url_rule('/<company_short_name>/api/llm_query', view_func=LLMQueryApiView.as_view('llm_query_api'))

    # open the promt directory
    app.add_url_rule('/<company_short_name>/api/prompts', view_func=PromptApiView.as_view('prompt'))

    # toolbar buttons
    app.add_url_rule('/<company_short_name>/api/feedback', view_func=UserFeedbackApiView.as_view('feedback'))
    app.add_url_rule('/<company_short_name>/api/history', view_func=HistoryApiView.as_view('history'))
    app.add_url_rule('/<company_short_name>/api/help-content', view_func=HelpContentApiView.as_view('help-content'))

    # tasks management endpoints: create task, and review answer
    app.add_url_rule('/tasks', view_func=TaskApiView.as_view('tasks'))
    app.add_url_rule('/tasks/review/<int:task_id>', view_func=TaskReviewApiView.as_view('tasks-review'))

    # this endpoint is for upload documents into the vector store (api-key)
    app.add_url_rule('/api/load-document', view_func=LoadDocumentApiView.as_view('load-document'), methods=['POST'])

    # this endpoint is for generating embeddings for a given text
    app.add_url_rule('/<company_short_name>/api/embedding',
                     view_func=EmbeddingApiView.as_view('embedding_api'))

    # static pages
    # url: /pages/foundation o /pages/implementation_plan
    static_view = StaticPageView.as_view('static_pages')
    app.add_url_rule('/pages/<page_name>', view_func=static_view, methods=['GET'])

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

    app.add_url_rule('/version', 'version',
                     lambda: jsonify({"iatoolkit_version": current_app.config.get('VERSION', 'N/A')}))


    # make the root '/' goes to index
    @app.route('/')
    def root_redirect():
        return redirect(url_for('index'))


