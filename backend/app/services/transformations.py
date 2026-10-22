from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import hashlib
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import UserModel
from app.control_room.postgres_repository import PostgresControlRoomRepository
from app.control_room.service import ControlRoomService
from app.knowledge.postgres_repository import PostgresKnowledgeRepository
from app.knowledge.db_models import KnowledgeItemModel
from app.knowledge.models import KnowledgeType
from app.knowledge.service import KnowledgeService
from app.schemas.transformations import TransformationChatRequest, TransformationExecuteRequest, TransformationFeedbackRequest, TemplateToolsRequest
from app.transformations import template_tools
from app.transformations.diagnostics import suggest, findings
from app.schemas.transformations import TransformationTestRequest
from app.transformations.json_validation import strict_json
from app.transformations.runtime_client import FreeMarkerRuntimeClient
from app.transformations.workbench import generate, normalize, xml_root, leaves, path_name



@_log_traced('app.services.transformations.test_template', level=20)
def test_template(request: TransformationTestRequest,
                  current_user: UserModel, db: Session):
    """Return failed-test evidence as data; unavailable infrastructure stays an HTTP error."""
    output, error, stage = '', '', 'input'
    try:
        payload = normalize(request.input_payload, request.source_format)
        stage = 'runtime'
        runtime_payload = request.input_payload if request.source_format == 'XML' and 'JsonUtils.getJsonAsMap(input)' not in request.template else payload
        rendered = FreeMarkerRuntimeClient().execute(request.template, runtime_payload, request.direction, request.additionalProperties, request.headers)
        output = rendered.get('output', '')
        if not rendered.get('success'):
            raise ValueError(rendered.get('error') or rendered.get('message') or 'Rendering failed.')
        stage = 'output'
        if request.target_format == 'XML':
            xml_root(output)
        elif request.target_format == 'JSON':
            strict_json(output)
        else:
            normalize(output, 'ISO')
        stage = 'passed'
    except httpx.RequestError as exc:
        _log_exception('app.services.transformations:46', handled=True)
        raise HTTPException(503, 'Java execution service unavailable or timed out. Check the configured service connection.') from exc
    except httpx.HTTPStatusError as exc:
        _log_exception('app.services.transformations:48', handled=True)
        if exc.response.status_code >= 500:
            raise HTTPException(503, 'FreeMarker runtime failed. Check the Java service logs.') from exc
        try:
            detail = exc.response.json()
            error = str(detail.get('error') or detail.get('message') or 'Runtime rejected the template.')
        except ValueError:
            _log_exception('app.services.transformations:54', handled=True)
            error = 'Runtime rejected the template.'
    except (ValueError, TypeError, KeyError) as exc:
        _log_exception('app.services.transformations:56', handled=True)
        error = str(exc)
    except Exception as exc:
        # XML parsers expose their own syntax exceptions.
        _log_exception('app.services.transformations:58', handled=True)
        error = str(exc)
    data = {'passed': stage == 'passed', 'stage': stage, 'error': error, 'output': output,
            'suggestions': suggest(request.template, request.input_payload, request.source_format, request.target_format, error, request.direction, request.additionalProperties, request.headers) if error and stage in ('runtime','output') else [],
            'findings': findings(request.template,error,stage) if error else [],
            'guidance': ('FreeMarker execution and output syntax checks passed. No repair is needed for this sample; verify business correctness with representative inputs.' if stage == 'passed' else
                         'FreeMarker executed successfully, but the output format is invalid. Review output-format fixes below.' if stage == 'output' else
                         'FreeMarker failed. Review its actual error and the proposed fixes, then test your selected changes. No fixes are applied automatically.' if stage == 'runtime' else
                         'Input could not be parsed. Correct the input before running FreeMarker.')}
    save_run(db, current_user, 'TRANSFORMATION_TEST', 'Template test ' + ('passed.' if data['passed'] else 'failed.'),
             {'request': request.model_dump(), **data})
    return {'success': True, 'data': data}


@_log_traced('app.services.transformations.existing_template_tools', level=20)
def existing_template_tools(request: TemplateToolsRequest,
                            current_user: UserModel, db: Session):
    try:
        if request.action == 'generate_payload':
            from app.transformations.payload_generator import generate_payload
            data = generate_payload(request.template,request.source_format,request.direction,request.xml_root)
        elif request.action == 'inspect':
            data = template_tools.inspect(request.template)
        elif request.action == 'compare':
            if not request.other_template.strip():
                raise ValueError('Paste the second transformation to compare.')
            data = template_tools.compare(request.template, request.other_template)
        else:
            data = template_tools.revise(request.template, request.instructions, request.replacements)
    except ValueError as exc:
        _log_exception('app.services.transformations:87', handled=True)
        raise HTTPException(422, str(exc)) from exc
    save_run(db, current_user, 'TRANSFORMATION_TOOLS', f'Template {request.action} completed.',
             {'request':request.model_dump(), **data})
    return {'success':True, 'data':data}


@_log_traced('app.services.transformations.learning_memory', level=20)
def learning_memory(current_user: UserModel, db: Session):
    rows = db.query(KnowledgeItemModel).filter_by(user_id=current_user.id,
        knowledge_type='TRANSFORMATION_PATTERN').order_by(KnowledgeItemModel.id.desc()).limit(100).all()
    return {'success': True, 'data': [{'id': r.id, 'source': r.source,
        'scenario': r.metadata_json.get('scenario', 'Previously confirmed scenario'),
        'status': r.metadata_json.get('status', 'confirmed'),
        'renders': r.metadata_json.get('renders', 0), 'comment': r.metadata_json.get('comment', ''),
        'mappings': r.value.get('mappings', {}), 'validations': r.value.get('validations', [])} for r in rows]}


@_log_traced('app.services.transformations.learning_feedback', level=20)
def learning_feedback(item_id: int, request: TransformationFeedbackRequest,
                      current_user: UserModel, db: Session):
    row = db.query(KnowledgeItemModel).filter_by(id=item_id, user_id=current_user.id,
        knowledge_type='TRANSFORMATION_PATTERN').first()
    if not row:
        raise HTTPException(404, 'Learning example not found.')
    if request.approved and not row.metadata_json.get('renders', 0):
        raise HTTPException(422, 'Render this generated scenario successfully before confirming its correctness.')
    row.source = 'user-feedback'
    row.metadata_json = {**row.metadata_json, 'status': 'confirmed' if request.approved else 'rejected',
                         'comment': request.comment, 'feedback_at': datetime.now(timezone.utc).isoformat()}
    db.commit()
    return {'success': True, 'message': 'Feedback saved. Rejected scenarios are excluded from reuse.'}


@_log_traced('app.services.transformations.pattern_key', level=20)
def pattern_key(request):
    shape = [request.direction, request.source.format, request.target.format]
    for payload in (request.source, request.target):
        shape.append(sorted({path_name(tuple('*' if isinstance(part,int) else part for part in p))
                             for p, _ in leaves(normalize(payload.payload, payload.format))}))
    if request.additionalProperties or request.headers:
        shape.append(sorted(path_name(p) for p,_ in leaves({'addProps':request.additionalProperties,'header':request.headers})))
    return 'workbench:' + hashlib.sha256(json.dumps(shape).encode()).hexdigest()


@_log_traced('app.services.transformations.memory_context', level=20)
def memory_context(request):
    return {'direction':request.direction.upper(), 'source_format':request.source.format.upper(),
            'target_format':request.target.format.upper(),
            'source_paths':sorted({path_name(tuple('*' if isinstance(p,int) else p for p in path))
                for path,_ in list(leaves(normalize(request.source.payload,request.source.format))) + list(leaves({'addProps':request.additionalProperties,'header':request.headers}))}),
            'target_paths':sorted({path_name(tuple('*' if isinstance(p,int) else p for p in path))
                for path,_ in leaves(normalize(request.target.payload,request.target.format))})}


@_log_traced('app.services.transformations.select_memory', level=20)
def select_memory(db, user_id, request):
    context, key = memory_context(request), pattern_key(request)
    rows = db.query(KnowledgeItemModel).filter_by(user_id=user_id,source='user-feedback',
        knowledge_type='TRANSFORMATION_PATTERN').all()
    compatible = []
    for row in rows:
        metadata = row.metadata_json
        same_scope = all(metadata.get(k) == context[k] for k in ('direction','source_format','target_format','target_paths'))
        if row.key == key or (same_scope and metadata.get('source_paths') and set(metadata['source_paths']) <= set(context['source_paths'])):
            compatible.append(row)
    if not compatible:
        return None
    # Feedback order, not generation order; later renders must not change which correction wins.
    return max(compatible, key=lambda row:(row.metadata_json.get('feedback_at') or row.created_at.isoformat(), row.id))


@_log_traced('app.services.transformations.confirm_pattern', level=20)
def confirm_pattern(request: TransformationChatRequest,
                    current_user: UserModel, db: Session):
    try:
        data = generate(request)
        KnowledgeService(PostgresKnowledgeRepository(db)).learn_from_feedback(
            KnowledgeType.TRANSFORMATION_PATTERN, pattern_key(request),
            {'mappings': {row['target_field']: row['source_field'] for row in data['mappings']},
             'validations': data['validations']}, current_user.id,
            metadata={**memory_context(request),'feedback_at':datetime.now(timezone.utc).isoformat(),'status':'confirmed'})
    except (ValueError, TypeError) as exc:
        _log_exception('app.services.transformations:163', handled=True)
        raise HTTPException(422, str(exc)) from exc
    return {'success': True, 'message': 'Confirmed mappings and validation rules saved for this direction and payload shape.'}


@_log_traced('app.services.transformations.save_run', level=20)
def save_run(db, user, event, message, data):
    return ControlRoomService(PostgresControlRoomRepository(db)).record_turn(
        user_id=user.id, message=message, agent_name='Transformation Agent',
        result_message=message, task_type=event, success=True,
        confidence=data.get('confidence'), result_data=data,
    )


@_log_traced('app.services.transformations.transformation_chat', level=20)
def transformation_chat(request: TransformationChatRequest,
                        current_user: UserModel,
                        db: Session):
    repository = PostgresKnowledgeRepository(db)
    learned = {}
    for item in (repository.find_by_type('FIELD_MAPPING', current_user.id) if request.use_learned else []):
        if item.source == 'user-feedback':
            value = item.value
            learned[value.get('target_field', value.get('target', ''))] = value.get('source_field', value.get('source', ''))
    try:
        reused = False
        pattern = None
        learning_status = 'Learning reuse is off.' if not request.use_learned else 'No compatible confirmed scenario found.'
        if request.use_learned:
            pattern = select_memory(db, current_user.id, request)
            if pattern and pattern.metadata_json.get('status') != 'rejected':
                learned.update(pattern.value['mappings'])
                # Explicit edits replace remembered rules of the same field/type, never accumulate duplicates.
                merged = {(r['field'], r['type']): r for r in pattern.value['validations']}
                merged.update({(r['field'], r['type']): r for r in request.validations})
                request = request.model_copy(update={'validations': list(merged.values())})
                reused = True
                learning_status = f'Confirmed scenario #{pattern.id} loaded. Explicit review edits take priority.'
            elif pattern:
                learning_status = f'Scenario #{pattern.id} was rejected; its mappings were not reused.'
        data = generate(request, learned)
        data['learned_pattern_used'] = reused
        data['learning_status'] = learning_status
        data['learned_mapping_count'] = sum(row['reason'] == 'Confirmed mapping from feedback' for row in data['mappings'])
    except (ValueError, TypeError, KeyError) as exc:
        _log_exception('app.services.transformations:205', handled=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        _log_exception('app.services.transformations:207', handled=True)
        raise HTTPException(422, f'Could not parse the payload: {exc}') from exc
    data['request'] = request.model_dump()
    candidate = KnowledgeItemModel(knowledge_type='TRANSFORMATION_PATTERN', key=pattern_key(request),
        value={'mappings': {r['target_field']: r['source_field'] for r in data['mappings']},
               'validations': data['validations']}, confidence=data['confidence'], scope='USER',
        user_id=current_user.id, source='generated-candidate',
        metadata_json={**memory_context(request), 'status': 'candidate', 'renders': 0,
                       'scenario': f'{request.direction}: {request.source.format} → {request.target.format}',
                       'template_hash': hashlib.sha256(data['template'].encode()).hexdigest(),
                       'source_format': request.source.format, 'target_format': request.target.format})
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    data['learning_id'] = candidate.id
    conversation = save_run(db, current_user, 'TRANSFORMATION_CHAT', 'Transformation generated for review.', data)
    return {'success': True, 'message': 'Transformation generated. Review mappings and test output.',
            'data': data, 'conversation_id': conversation.id}


@_log_traced('app.services.transformations.execute_approved_transformation', level=20)
def execute_approved_transformation(request: TransformationExecuteRequest,
                                   current_user: UserModel,
                                   db: Session):
    if not request.approved:
        raise HTTPException(422, 'Approve the template before rendering.')
    try:
        payload = normalize(request.input_payload, request.source_format)
        # New XML templates use the DOM model. Keep map-based saved templates renderable.
        if request.source_format.upper() == 'XML' and 'JsonUtils.getJsonAsMap(input)' not in request.template:
            payload = request.input_payload
        result = FreeMarkerRuntimeClient().execute(request.template, payload, request.direction, request.additionalProperties, request.headers)
        output = result.get('output', '')
        if not result.get('success'):
            raise ValueError(result.get('error') or result.get('message', 'Rendering failed.'))
        if request.target_format.upper() == 'JSON':
            strict_json(output)
        elif request.target_format.upper() == 'XML':
            xml_root(output)
        elif request.target_format.upper() == 'ISO':
            normalize(output, 'ISO')
    except httpx.ConnectError as exc:
        _log_exception('app.services.transformations:247', handled=True)
        raise HTTPException(503, 'Java execution service unavailable. Check the configured service connection.') from exc
    except httpx.TimeoutException as exc:
        _log_exception('app.services.transformations:249', handled=True)
        raise HTTPException(504, 'FreeMarker rendering timed out.') from exc
    except httpx.RequestError as exc:
        _log_exception('app.services.transformations:251', handled=True)
        raise HTTPException(503, 'Java execution service connection failed.') from exc
    except httpx.HTTPStatusError as exc:
        _log_exception('app.services.transformations:253', handled=True)
        if exc.response.status_code >= 500:
            raise HTTPException(503, 'Java execution service failed or returned an incompatible response.') from exc
        try:
            error = exc.response.json()
            detail = error.get('error') or error.get('message')
        except ValueError:
            _log_exception('app.services.transformations:259', handled=True)
            detail = 'The Java runtime rejected this template.'
        raise HTTPException(422, detail) from exc
    except Exception as exc:
        _log_exception('app.services.transformations:262', handled=True)
        raise HTTPException(422, f'Output validation failed: {exc}') from exc
    data = {'output': output, 'template': request.template, 'target_format': request.target_format,
            'source_format': request.source_format, 'input_payload': request.input_payload,
            'direction':request.direction, 'additionalProperties':request.additionalProperties, 'headers':request.headers}
    if request.learning_id:
        candidate = db.query(KnowledgeItemModel).filter_by(id=request.learning_id,
            user_id=current_user.id, knowledge_type='TRANSFORMATION_PATTERN').first()
        if candidate and candidate.metadata_json.get('template_hash') == hashlib.sha256(request.template.encode()).hexdigest() and (
            candidate.metadata_json.get('source_format') == request.source_format and
            candidate.metadata_json.get('target_format') == request.target_format and
            candidate.metadata_json.get('direction', request.direction) == request.direction):
            candidate.metadata_json = {**candidate.metadata_json,
                'renders': candidate.metadata_json.get('renders', 0) + 1,
                'status': 'rendered' if candidate.source == 'generated-candidate' else candidate.metadata_json.get('status')}
            db.commit()
    save_run(db, current_user, 'TRANSFORMATION_RENDER', 'Template rendered and output format checked.', data)
    return {'success': True, 'message': 'Output rendered successfully.', 'data': data}
