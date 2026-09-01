import unittest
from datetime import date

from apps.common import inspection_dates
from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


services = load_module(
    'apps/dx/dx_layer3/field_missing/services.py',
    'layer3_sea_field_missing_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_missing_exclude_conditions=lambda *_args: [],
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda: 'TRUE',
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
        'apps.dx.dx_layer3.dashboard': package_stub(
            'apps.dx.dx_layer3.dashboard'
        ),
        'apps.dx.dx_layer3.dashboard.services': module_stub(
            'apps.dx.dx_layer3.dashboard.services',
            validate_exclude_condition=lambda _condition: True,
        ),
    },
)

api = load_module(
    'apps/dx/dx_layer3/field_missing/api.py',
    'apps.dx.dx_layer3.field_missing.api',
    {
        'django': package_stub('django'),
        'django.http': module_stub('django.http', JsonResponse=dict),
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_connection=lambda: None
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns', get_editable_columns=lambda *_: []
        ),
        'apps.common.response': module_stub(
            'apps.common.response',
            safe_error=lambda error: {'error': str(error)},
            log_error=lambda _error: None,
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
        'apps.dx.dx_layer3.field_missing': package_stub(
            'apps.dx.dx_layer3.field_missing'
        ),
        'apps.dx.dx_layer3.field_missing.services': services,
    },
)


class SeaFieldMissingDateTests(unittest.TestCase):
    def test_api_keeps_inspection_date_and_passes_source_date_to_queries(self):
        inspection_date, source_date, contract = api._resolve_request_dates(
            '2026-09-01', 'tv'
        )

        self.assertEqual(date(2026, 9, 1), inspection_date)
        self.assertEqual(date(2026, 8, 31), source_date)
        self.assertEqual('2026-09-01', contract['inspection_date'])
        self.assertEqual('2026-08-31', contract['source_date'])

    def test_tv_maps_inspection_date_to_previous_source_date(self):
        contract = services.resolve_field_missing_date_contract(
            date(2026, 9, 1), 'tv'
        )

        self.assertEqual('2026-09-01', contract['inspection_date'])
        self.assertEqual('2026-08-31', contract['source_date'])
        self.assertEqual(-1, contract['offset_days'])
        self.assertEqual('sea_tv', contract['source_key'])

    def test_detection_uses_source_date_but_reviews_use_inspection_date(self):
        cursor = ScriptedCursor([
            {'fetchall': [('TV-1', 1, 1)]},
            {'fetchone': (1,)},
            {'fetchall': []},
        ])

        result = services.field_missing_detection(
            cursor,
            date(2026, 8, 31),
            'tv',
            'Amazon',
            {'Amazon': ['sku']},
            inspection_date=date(2026, 9, 1),
        )

        detection_params = cursor.calls[0][1]
        self.assertEqual(
            (
                'Amazon', date(2026, 8, 30), date(2026, 8, 29),
                date(2026, 8, 31),
            ),
            detection_params,
        )
        self.assertEqual(
            ('tv_retail_com', '2026-09-01', 'Amazon'),
            cursor.calls[2][1],
        )
        self.assertEqual('2026-08-31', result['date'])
        self.assertEqual(
            ['2026-08-30', '2026-08-29'], result['prev_dates']
        )
        self.assertEqual(1, result['summary']['total_missing_cases'])


if __name__ == '__main__':
    unittest.main()
