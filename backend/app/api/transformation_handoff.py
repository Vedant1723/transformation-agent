"""Public controllers: validate, resolve identity/session, delegate to services."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.auth import get_current_user
from app.database.session import get_db
from app.models.user import UserModel
from app.schemas.feedback import Feedback
from app.schemas.transformations import TransformationChatRequest, TransformationTestRequest, TemplateToolsRequest
from app.services import transformations
from app.services.feedback import submit_feedback
from app.transformations import local_model

router = APIRouter(prefix='/api/v1/transformations', tags=['Transformations'])


@router.post('/generate')
@_log_traced('app.api.transformation_handoff.generate', level=10)
def generate(request: TransformationChatRequest, user: UserModel = Depends(get_current_user),
             db: Session = Depends(get_db)):
    return transformations.transformation_chat(request, user, db)


@router.post('/test')
@_log_traced('app.api.transformation_handoff.test', level=10)
def test(request: TransformationTestRequest, user: UserModel = Depends(get_current_user),
         db: Session = Depends(get_db)):
    return transformations.test_template(request, user, db)


@router.post('/tools')
@_log_traced('app.api.transformation_handoff.tools', level=10)
def tools(request: TemplateToolsRequest, user: UserModel = Depends(get_current_user),
          db: Session = Depends(get_db)):
    return transformations.existing_template_tools(request, user, db)


@router.post('/feedback', status_code=201)
@_log_traced('app.api.transformation_handoff.feedback', level=10)
def feedback(request: Feedback, user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    return submit_feedback(request, user, db)


@router.get('/model')
@_log_traced('app.api.transformation_handoff.model_status', level=10)
def model_status(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.feedback_retraining import status
    return {'success': True, 'data': {**local_model.status(), 'retraining': status(user, db)}}
