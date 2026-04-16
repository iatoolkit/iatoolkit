# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from io import BytesIO
import mimetypes
from flask import render_template, redirect, url_for, current_app, abort, send_file
from flask import jsonify
from iatoolkit.common.exceptions import IAToolkitException


# this function register all the views
def register_views(app):

    from iatoolkit.views.init_context_api_view import InitContextApiView
    from iatoolkit.views.llmquery_api_view import LLMQueryApiView
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
    from iatoolkit.views.configuration_api_view import ConfigurationApiView, ValidateConfigurationApiView
    from iatoolkit.views.logout_api_view import LogoutApiView
    from iatoolkit.views.home_view import HomeView
    from iatoolkit.views.chat_view import ChatView
    from iatoolkit.views.static_page_view import StaticPageView
    from iatoolkit.views.root_redirect_view import RootRedirectView
    from iatoolkit.views.users_api_view import UsersApiView
    from iatoolkit.views.rag_api_view import RagApiView
    from iatoolkit.views.categories_api_view import CategoriesApiView
    from iatoolkit.views.connectors_api_view import ConnectorsApiView
    from iatoolkit.views.tool_api_view import ToolApiView
    from iatoolkit.views.api_key_api_view import ApiKeyApiView

    # assign root '/' to our new redirect logic
    app.add_url_rule('/home', view_func=RootRedirectView.as_view('root_redirect'))

    # company home view
    app.add_url_rule('/<company_short_name>/home', view_func=HomeView.as_view('home'))

    # login for the iatoolkit integrated frontend
    app.add_url_rule('/<company_short_name>/login', view_func=LoginView.as_view('login'))

    # Chat Route (Direct Access)
    app.add_url_rule('/<company_short_name>/chat',
                     view_func=ChatView.as_view('chat'))

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

    # init (reset) the company context
    app.add_url_rule('/<company_short_name>/api/init-context',
                     view_func=InitContextApiView.as_view('init-context'),
                     methods=['POST', 'OPTIONS'])

    # register new user, account verification and forgot password
    app.add_url_rule('/<company_short_name>/signup',view_func=SignupView.as_view('signup'))
    app.add_url_rule('/<company_short_name>/verify/<token>', view_func=VerifyAccountView.as_view('verify_account'))
    app.add_url_rule('/<company_short_name>/forgot-password', view_func=ForgotPasswordView.as_view('forgot_password'))
    app.add_url_rule('/<company_short_name>/change-password/<token>', view_func=ChangePasswordView.as_view('change_password'))
    app.add_url_rule(
        '/<string:company_short_name>/api/company-users',
        view_func=UsersApiView.as_view('company-users')
    )

    # main chat query, used by the JS in the browser (with credentials)
    # can be used also for executing iatoolkit prompts
    app.add_url_rule('/<company_short_name>/api/llm_query', view_func=LLMQueryApiView.as_view('llm_query_api'))

    # Categories Endpoint
    app.add_url_rule('/<company_short_name>/api/categories',
                     view_func=CategoriesApiView.as_view('categories_api'),
                     methods=['GET', 'POST'])

    # open the promt directory and specific prompt management
    prompt_view = PromptApiView.as_view('prompt')
    app.add_url_rule('/<company_short_name>/api/prompts',
                     view_func=prompt_view,
                     methods=['GET', 'POST'],
                     defaults={'prompt_name': None})

    app.add_url_rule('/<company_short_name>/api/prompts/<prompt_name>',
                     view_func=prompt_view,
                     methods=['GET', 'POST','PUT', 'DELETE'])
    # toolbar buttons
    app.add_url_rule('/<company_short_name>/api/feedback', view_func=UserFeedbackApiView.as_view('feedback'))
    app.add_url_rule('/<company_short_name>/api/history', view_func=HistoryApiView.as_view('history'))
    app.add_url_rule('/<company_short_name>/api/help-content', view_func=HelpContentApiView.as_view('help-content'))

    # --- Tool Management API ---
    tool_view = ToolApiView.as_view('tool_api')

    app.add_url_rule(
        '/<company_short_name>/api/tools',
        view_func=tool_view,
        methods=['GET', 'POST']
    )
    app.add_url_rule(
        '/<company_short_name>/api/tools/<int:tool_id>',
        view_func=tool_view,
        methods=['GET', 'PUT', 'DELETE']
    )
    app.add_url_rule(
        '/<company_short_name>/api/tools/execute',
        view_func=tool_view,
        methods=['POST'],
        defaults={'action': 'execute'}
    )

    # --- API Keys Management API ---
    api_key_view = ApiKeyApiView.as_view('api_key_api')
    app.add_url_rule(
        '/<company_short_name>/api/api-keys',
        view_func=api_key_view,
        methods=['GET', 'POST']
    )
    app.add_url_rule(
        '/<company_short_name>/api/api-keys/<int:api_key_id>',
        view_func=api_key_view,
        methods=['GET', 'PUT', 'DELETE']
    )

    # --- RAG API Routes ---
    rag_view = RagApiView.as_view('rag_api')

    # 1. List Files (POST for filters)
    app.add_url_rule('/api/rag/<company_short_name>/files',
                     view_func=rag_view,
                     methods=['POST'],
                     defaults={'action': 'list_files'})

    # 2. Delete File
    app.add_url_rule('/api/rag/<company_short_name>/files/<int:document_id>',
                     view_func=rag_view,
                     methods=['DELETE'],
                     defaults={'action': 'delete_file'})

    # 3. Search Lab
    app.add_url_rule('/<company_short_name>/api/rag/search',
                     view_func=rag_view,
                     methods=['POST'],
                     defaults={'action': 'search'})

    # 3.1 Direct vector text search (no LLM orchestration)
    app.add_url_rule('/<company_short_name>/api/rag/search/text',
                     view_func=rag_view,
                     methods=['POST'],
                     defaults={'action': 'search_text'})

    # 3.2 Direct vector image search from text (no LLM orchestration)
    app.add_url_rule('/<company_short_name>/api/rag/search/image',
                     view_func=rag_view,
                     methods=['POST'],
                     defaults={'action': 'search_image'})

    # 3.3 Direct visual search from one image (no LLM orchestration)
    app.add_url_rule('/api/rag/<company_short_name>/search/visual',
                     view_func=rag_view,
                     methods=['POST'],
                     defaults={'action': 'search_visual'})

    # 4. Get File Content (View/Download)
    app.add_url_rule('/api/rag/<company_short_name>/files/<int:document_id>/content',
                     view_func=rag_view,
                     methods=['GET'],
                     defaults={'action': 'get_file_content'})

    # this endpoint is for upload documents into the vector store (api-key)
    app.add_url_rule('/api/load-document', view_func=LoadDocumentApiView.as_view('load-document'), methods=['POST'])

    # this endpoint is for generating embeddings for a given text
    app.add_url_rule('/<company_short_name>/api/embedding',
                     view_func=EmbeddingApiView.as_view('embedding_api'))

    # Connectors catalog
    app.add_url_rule(
        '/<company_short_name>/api/connectors',
        view_func=ConnectorsApiView.as_view('connectors_api_view'),
        methods=['GET']
    )

    # company configuration
    configuration_view = ConfigurationApiView.as_view('configuration')
    app.add_url_rule('/<company_short_name>/api/configuration',
                     view_func=configuration_view,
                     methods=['GET', 'POST', 'PATCH'],)

    # explicit runtime reload endpoint used by admin/dashboard integrations
    app.add_url_rule('/<company_short_name>/api/load_configuration',
                     view_func=configuration_view,
                     methods=['GET'],
                     defaults={'action': 'load_configuration'})

    app.add_url_rule('/<company_short_name>/api/configuration/validate',
                     view_func=ValidateConfigurationApiView.as_view('configuration-validate'),
                     methods=['GET'])

    # static pages
    # url: /pages/foundation o /pages/implementation_plan
    static_view = StaticPageView.as_view('static_pages')
    app.add_url_rule('/pages/<page_name>', view_func=static_view, methods=['GET'])

    @app.route('/download/<path:filename>')
    def download_file(filename):
        """
        Downloads a generated file.
        Uses StorageService + signed token.
        """
        try:
            from iatoolkit.core import current_iatoolkit
            from iatoolkit.services.storage_service import StorageService
            storage_service = current_iatoolkit().get_injector().get(StorageService)
            token_payload = storage_service.resolve_download_token(filename)
            company_short_name = token_payload["company"]
            storage_key = token_payload["storage_key"]
            output_filename = token_payload.get("filename") or storage_key.split("/")[-1]

            try:
                signed_url = storage_service.generate_presigned_url(company_short_name, storage_key)
            except NotImplementedError:
                signed_url = None

            # Fast path: redirect to object storage when a presigned URL is available.
            if signed_url:
                return redirect(signed_url)

            # Fallback path: stream bytes from storage through Flask.
            file_bytes = storage_service.get_document_content(company_short_name, storage_key)
            guessed_mime, _ = mimetypes.guess_type(output_filename)
            return send_file(
                BytesIO(file_bytes),
                as_attachment=True,
                download_name=output_filename,
                mimetype=guessed_mime or "application/octet-stream",
            )

        except IAToolkitException as e:
            if e.error_type == IAToolkitException.ErrorType.CALL_ERROR:
                abort(404)
            abort(500, str(e))


    app.add_url_rule('/version', 'version',
                     lambda: jsonify({"iatoolkit_version": current_app.config.get('VERSION', 'N/A')}))
