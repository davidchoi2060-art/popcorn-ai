"""Pure support contract. Hashes and matching DTOs never grant authority."""
from copy import deepcopy
import base64
import json
import re

from . import commerce_contract as c

VERSION = 'commerce_support_v1'
MAX_BODY = 4000  # Representation bound, not a promised service policy.
CUSTOMER_ACTIONS = ('create_inquiry', 'append_customer_message', 'reopen')
ADMIN_ACTIONS = ('record_external_contact', 'record_reply', 'publish_customer_reply',
                 'internal_note', 'close', 'reopen')
CREATE_ACTIONS = ('create_inquiry', 'record_external_contact')
PRIVATE_ACTIONS = ('record_external_contact', 'record_reply', 'internal_note')
ORDER_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}\Z')


class SupportError(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def fail(status, code):
    raise SupportError(status, code)


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= c.MAX_INTEGER:
        fail(422, 'invalid_support_integer')
    return value


def uuid(value):
    try:
        return c.uuid_text(value)
    except c.CommerceError:
        fail(422, 'invalid_support_uuid')


def fields(value, required, optional=()):
    if (type(value) is not dict or not set(required) <= set(value)
            or not set(value) <= set(required) | set(optional)):
        fail(422, 'invalid_support_request')


def order_no(value):
    if type(value) is not str or not ORDER_PATTERN.fullmatch(value):
        fail(422, 'invalid_support_order')
    return value


def body_text(value):
    if (type(value) is not str or not value.strip() or len(value) > MAX_BODY
            or any(ord(ch) < 32 and ch not in '\n\t\r' for ch in value)
            or '<' in value or '>' in value):
        fail(422, 'invalid_support_body')
    try:
        if len(value.encode('utf-8')) > MAX_BODY * 3:
            fail(422, 'invalid_support_body')
    except UnicodeError:
        fail(422, 'invalid_support_body')
    return value.strip()


def principal(value, *, write=False):
    if value is None:
        fail(401, 'admin_authentication_required')
    if (type(value) is not dict or type(value.get('operator_id')) is not int
            or not 0 < value['operator_id'] <= c.MAX_INTEGER
            or value.get('status') != '활성'
            or value.get('role') not in ('viewer', 'operator', 'owner')
            or (write and value['role'] == 'viewer')):
        fail(403, 'support_permission_required')
    return {key: value[key] for key in ('operator_id', 'role', 'status')}


def actor(value):
    if type(value) is not dict:
        fail(403, 'support_authorization_required')
    if value.get('kind') == 'customer':
        fields(value, ('kind', 'user_id', 'owner_scope'))
        integer(value['user_id'], 1)
        try:
            c.basis_text(value['owner_scope'])
        except c.CommerceError:
            fail(403, 'support_authorization_required')
    elif value.get('kind') == 'operator':
        fields(value, ('kind', 'operator_id'))
        integer(value['operator_id'], 1)
    else:
        fail(403, 'support_authorization_required')
    return deepcopy(value)


def command(value, audience):
    choices = CUSTOMER_ACTIONS if audience == 'customer' else ADMIN_ACTIONS
    if audience not in ('customer', 'admin'):
        fail(422, 'invalid_support_audience')
    if type(value) is not dict or value.get('action') not in choices:
        fail(403, 'support_action_forbidden')
    publish = value['action'] == 'publish_customer_reply'
    fields(value, ('operation_id', 'action', 'case_id', 'expected_revision',
                   'reply_event_id' if publish else 'body'))
    result = dict(operation_id=uuid(value['operation_id']), action=value['action'],
                  case_id=None if value['case_id'] is None else uuid(value['case_id']),
                  expected_revision=integer(value['expected_revision']))
    if (result['action'] in CREATE_ACTIONS) != (result['case_id'] is None):
        fail(422, 'invalid_support_target')
    if result['case_id'] is None and result['expected_revision'] != 0:
        fail(409, 'support_revision_conflict')
    result['reply_event_id' if publish else 'body'] = (
        uuid(value['reply_event_id']) if publish else body_text(value['body']))
    return result


def identity(command_value, *, order_id, no, owner_scope, author):
    # Sessions/bindings are checked at execution, not stable author identities.
    c.basis_text(owner_scope)
    return dict(version=VERSION, order_id=integer(order_id, 1), order_no=order_no(no),
                owner_scope=owner_scope, actor=actor(author), command=deepcopy(command_value))


def transition(case, cmd, audience, *, now):
    integer(now)
    if case is None:
        if cmd['action'] not in CREATE_ACTIONS:
            fail(404, 'support_case_not_found')
        origin = 'customer' if cmd['action'] == 'create_inquiry' else 'external_record'
        visible = origin == 'customer'
        return dict(origin=origin, state='open', admin_revision=1,
                    public_revision=1 if visible else None, created_at=now,
                    updated_at=now, public_updated_at=now if visible else None), visible
    if audience == 'customer' and case['origin'] != 'customer':
        fail(404, 'support_case_not_found')
    revision = case['public_revision'] if audience == 'customer' else case['admin_revision']
    if revision != cmd['expected_revision']:
        fail(409, 'support_revision_conflict')
    action = cmd['action']
    if action in CREATE_ACTIONS:
        fail(422, 'invalid_support_target')
    if action == 'reopen':
        if case['state'] != 'closed':
            fail(409, 'support_state_conflict')
        state = 'open'
    elif action == 'close':
        if case['state'] != 'open':
            fail(409, 'support_state_conflict')
        state = 'closed'
    else:
        if action != 'internal_note' and case['state'] != 'open':
            fail(409, 'support_state_conflict')
        state = case['state']
    if action == 'publish_customer_reply' and case['origin'] != 'customer':
        fail(409, 'support_publication_forbidden')
    visible = case['origin'] == 'customer' and action not in PRIVATE_ACTIONS
    result = deepcopy(case)
    result.update(state=state, admin_revision=integer(case['admin_revision'] + 1, 1),
                  updated_at=now)
    if visible:
        result.update(public_revision=integer(case['public_revision'] + 1, 1),
                      public_updated_at=now)
    return result, visible


def case_view(case, audience):
    if audience == 'customer' and case['origin'] != 'customer':
        fail(404, 'support_case_not_found')
    revision = case['public_revision'] if audience == 'customer' else case['admin_revision']
    return dict(case_id=case['case_id'], origin=case['origin'], state=case['state'],
                revision=revision, recorded_at=case['created_at'],
                updated_at=case['public_updated_at'] if audience == 'customer' else case['updated_at'])


def event_view(event, audience):
    if audience == 'customer' and not event['visible']:
        fail(404, 'support_event_not_found')
    result = dict(event_id=event['event_id'], case_id=event['case_id'], action=event['action'],
                  author_kind=event['actor']['kind'], body=event['body'],
                  recorded_at=event['recorded_at'],
                  revision=event['public_revision'] if audience == 'customer' else event['admin_revision'])
    if audience == 'admin':
        result.update(visible=event['visible'], actor=deepcopy(event['actor']),
                      reply_event_id=event['reply_event_id'])
    return result


def cursor_scope(no, audience, mode, case_id):
    return dict(version=VERSION, order_no=no, audience=audience, mode=mode, case_id=case_id)


def encode_cursor(scope, upper, after):
    raw = json.dumps(dict(scope=scope, upper=upper, after=after), sort_keys=True,
                     separators=(',', ':')).encode('ascii')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def decode_cursor(value, scope):
    try:
        if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,1400}', value):
            raise ValueError()
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        record = json.loads(raw)
        fields(record, ('scope', 'upper', 'after'))
        if record['scope'] != scope or encode_cursor(scope, record['upper'], record['after']) != value:
            raise ValueError()
        upper, after = record['upper'], record['after']
        if scope['mode'] == 'cases':
            if uuid(upper) != upper or uuid(after) != after or not after <= upper:
                raise ValueError()
        elif not 1 <= integer(after, 1) <= integer(upper, 1):
            raise ValueError()
        return upper, after
    except (ValueError, TypeError, KeyError, UnicodeError):
        fail(422, 'invalid_support_cursor')
