import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from tests.unit.support import load_module, module_stub, package_stub


class FakeJsonResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status


class FakeRequest:
    method = 'POST'

    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')
        self.user = SimpleNamespace(is_authenticated=True, username='tester')


def _parse_date(value, default='yesterday'):
    if not value:
        return None if default is None else datetime.now().date()
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def load_api(get_report, send_report, get_recipients):
    package = 'apps.dx.dx_layer4.collection_status'
    return load_module(
        'apps/dx/dx_layer4/collection_status/api.py',
        f'{package}.api_send_guard_under_test',
        stubs={
            'django': package_stub('django'),
            'django.http': module_stub(
                'django.http', JsonResponse=FakeJsonResponse,
            ),
            'django.views': package_stub('django.views'),
            'django.views.decorators': package_stub('django.views.decorators'),
            'django.views.decorators.http': module_stub(
                'django.views.decorators.http',
                require_POST=lambda function: function,
            ),
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.response': module_stub(
                'apps.common.response', safe_error=lambda error: error,
            ),
            'apps.common.params': module_stub(
                'apps.common.params', parse_date=_parse_date,
            ),
            'apps.common.email_config': module_stub(
                'apps.common.email_config',
                get_recipients_with_name=get_recipients,
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer4': package_stub('apps.dx.dx_layer4'),
            package: package_stub(package),
            f'{package}.services': module_stub(
                f'{package}.services',
                VALID_COLLECTION_CATEGORIES=frozenset({'tv'}),
                check_email_sent=lambda *_args: {},
                get_collection_status=lambda *_args: {},
                get_null_detail=lambda *_args: {},
                send_email_report=send_report,
            ),
            f'{package}.email_services': module_stub(
                f'{package}.email_services',
                get_email_report_data=get_report,
            ),
        },
    )


def request():
    return FakeRequest({
        'subject': 'monitoring subject',
        'html': '<div>email body</div>',
        'date': '2026-08-11',
    })


class EmailSendGuardTests(unittest.TestCase):
    def test_incomplete_report_blocks_smtp(self):
        sender = Mock()
        recipients = Mock(return_value=[{'email': 'ops@example.invalid'}])
        api = load_api(
            lambda _date: {
                'complete': False,
                'errors': [{'source': 'siel_tv', 'message': 'failed'}],
            },
            sender,
            recipients,
        )

        response = api.send_email_report(request())

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.data['complete'])
        self.assertEqual(response.data['errors'][0]['source'], 'siel_tv')
        sender.assert_not_called()
        recipients.assert_not_called()

    def test_complete_report_sends_with_normalized_date(self):
        sender = Mock(return_value={'success': True})
        recipient_rows = [{'name': 'Ops', 'email': 'ops@example.invalid'}]
        recipients = Mock(return_value=recipient_rows)
        report = Mock(return_value={'complete': True, 'errors': []})
        api = load_api(report, sender, recipients)

        response = api.send_email_report(request())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])
        report.assert_called_once()
        self.assertEqual(str(report.call_args.args[0]), '2026-08-11')
        recipients.assert_called_once_with('collection_status_receiver')
        sender.assert_called_once_with(
            'monitoring subject', '<div>email body</div>', '2026-08-11',
            recipient_rows, 'tester',
        )


if __name__ == '__main__':
    unittest.main()
