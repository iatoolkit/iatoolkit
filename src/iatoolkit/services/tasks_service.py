# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.models import Task, TaskStatus
from iatoolkit.services.query_service import QueryService
from iatoolkit.repositories.tasks_repo import TaskRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.common.exceptions import IAToolkitException
from datetime import datetime
from werkzeug.utils import secure_filename


class TaskService:
    @inject
    def __init__(self,
                 task_repo: TaskRepo,
                 query_service: QueryService,
                 profile_repo: ProfileRepo,
                 call_service: CallServiceClient):
        self.task_repo = task_repo
        self.query_service = query_service
        self.profile_repo = profile_repo
        self.call_service = call_service

    def create_task(self,
                    company_short_name: str,
                    task_type_name: str,
                    client_data: dict,
                    company_task_id: int= 0,
                    execute_at: datetime = None,
                    files: list = []
                    ) -> Task:

        # validate company
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                               f'No existe la empresa: {company_short_name}')

        # validate task_type
        task_type = self.task_repo.get_task_type(task_type_name)
        if not task_type:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                               f'No existe el task_type: {task_type_name}')

        # process the task files
        task_files = self.get_task_files(files)

        # create Task object
        new_task = Task(
            company_id=company.id,
            task_type_id=task_type.id,
            company_task_id=company_task_id,
            client_data=client_data,
            execute_at=execute_at,
            files=task_files
        )
        new_task = self.task_repo.create_task(new_task)
        if execute_at and execute_at > datetime.now():
            self.execute_task(new_task)

        return new_task

    def review_task(self, task_id: int, review_user: str, approved: bool, comment: str):
        # get the task
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise IAToolkitException(IAToolkitException.ErrorType.TASK_NOT_FOUND,
                               f'No existe la tarea: {task_id}')

        if task.status != TaskStatus.ejecutado:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_STATE,
                               f'La tarea debe estar en estado ejecutada: {task_id}')

        # update the task
        task.approved = approved
        task.status = TaskStatus.aprobada if approved else TaskStatus.rechazada
        task.review_user = review_user
        task.comment = comment
        task.review_date = datetime.now()
        self.task_repo.update_task(task)
        return task

    def execute_task(self, task: Task):
        # in this case do nothing
        if (task.status != TaskStatus.pendiente or
                (task.execute_at and task.execute_at > datetime.now())):
            return task

        # get the Task template prompt
        if not task.task_type.prompt_template:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                               f'No existe el prompt_template para el task_type: {task.task_type.name}')

        template_dir = f'companies/{task.company.short_name}/prompts'

        # call the IA
        response = self.query_service.llm_query(
            task=task,
            user_identifier='task-monitor',
            company_short_name=task.company.short_name,
            prompt_name=task.task_type.name,
            client_data=task.client_data,
            files=task.files
        )
        if 'error' in response:
            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR,
                                     response.get('error'))

        # update the Task with the response from llm_query
        task.llm_query_id = response.get('query_id', 0)

        # update task status
        if not response.get('valid_response'):
            task.status = TaskStatus.fallida
        else:
            task.status = TaskStatus.ejecutado
        self.task_repo.update_task(task)

        # call the callback url
        if task.callback_url:
            self.notify_callback(task, response)

        return task

    def notify_callback(self, task: Task, response: dict):
        response_data = {
            'task_id': task.id,
            'company_task_id': task.company_task_id,
            'status': task.status.name,
            'answer': response.get('answer', ''),
            'additional_data': response.get('additional_data', {}),
            'client_data': task.client_data,
        }
        try:
            response, status_code = self.call_service.post(task.callback_url, response_data)
        except Exception as e:
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"Error al notificar callback {task.callback_url}: {str(e)}"
            )

    def get_task_files(self, uploaded_files):
        files_info = []

        for file in uploaded_files:
            filename = secure_filename(file.filename)

            try:
                # the file is already in base64
                file_content = file.read().decode('utf-8')
            except Exception as e:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.FILE_IO_ERROR,
                    f"Error al extraer el contenido del archivo {filename}: {str(e)}"
                )

            files_info.append({
                'filename': filename,
                'content': file_content,  # file in base64
                'type': file.content_type
            })

        return files_info

    def trigger_pending_tasks(self, company_short_name: str):
        n_tasks = 0
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            pending_tasks = self.task_repo.get_pending_tasks(company.id)
            for task in pending_tasks:
                self.execute_task(task)
                n_tasks += 1
        except Exception as e:
            raise IAToolkitException(
                IAToolkitException.ErrorType.TASK_EXECUTION_ERROR,
                f"Error ejecutando tareas pendientes: {str(e)}"
            )

        return {'message': f'{n_tasks} tareas ejecutadas.'}




