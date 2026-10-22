"""Coordinate correction capture and explicit approval; never activate weights."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.schemas.feedback import Feedback
from app.services import transformation_sessions as sessions


@_log_traced('app.services.feedback.submit_feedback', level=20)
def submit_feedback(request: Feedback, user: UserModel, db: Session):
    session = sessions.create(sessions.NewSession(title='Gateway transformation feedback'), user, db)['data']
    session = sessions.turn(session['id'], sessions.Turn(
        version=session['version'], action='context', context=request.context), user, db)['data']
    session = sessions.turn(session['id'], sessions.Turn(
        version=session['version'], action='template', template=request.template), user, db)['data']
    correction = sessions.submit_correction(session['id'], sessions.Correction(
        version=session['version'], revision=session['state']['current'],
        corrected_template=request.template, expected_output=request.expected_output,
        feedback=request.comment, validation_cases=request.validation_cases), user, db)['data']
    if request.approved and correction['test']['mapping_passed']:
        result = sessions.review_correction(session['id'], correction['revision'],
            sessions.CorrectionReview(version=correction['version'], decision='approved',
                                     sanitized=request.sanitized, feedback=request.comment), user, db)
        from app.services.feedback_retraining import schedule_safely
        result['data']['retraining'] = schedule_safely(user, db)
        return result
    return {'success': True, 'data': correction}
