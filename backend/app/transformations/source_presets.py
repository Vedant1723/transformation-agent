"""Editable synthetic examples, not the organisation's actual gateway contracts."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy

PRESETS = {
    'LookupDetails': {'transactionId': 'DEMO-LOOKUP-001', 'partnerCode': 'DEMO_PARTNER', 'customer': {'msisdn': 'DEMO-MSISDN', 'accountNumber': 'DEMO-ACCOUNT'}, 'lookup': {'reference': 'DEMO-REF', 'serviceCode': 'BILL_PAYMENT'}},
    'ProcessTxn': {'transactionId': 'DEMO-TXN-001', 'partnerCode': 'DEMO_PARTNER', 'customer': {'msisdn': 'DEMO-MSISDN', 'accountNumber': 'DEMO-ACCOUNT'}, 'payment': {'amount': 125.5, 'currency': 'KES', 'reference': 'DEMO-REF'}, 'items': [{'bundleId': 'DEMO-BUNDLE-A', 'quantity': 1, 'unitPrice': 25.5}, {'bundleId': 'DEMO-BUNDLE-B', 'quantity': 2, 'unitPrice': 50}]},
    'TxnStatus': {'transactionId': 'DEMO-STATUS-001', 'partnerCode': 'DEMO_PARTNER', 'originalTransactionId': 'DEMO-TXN-001', 'partnerReference': 'DEMO-PARTNER-REF'},
    'CreateAccount': {'transactionId': 'DEMO-CREATE-001', 'partnerCode': 'DEMO_PARTNER', 'customer': {'firstName': 'Demo', 'lastName': 'Customer', 'msisdn': 'DEMO-MSISDN'}, 'account': {'type': 'WALLET', 'currency': 'KES', 'externalReference': 'DEMO-ACCOUNT'}},
    'AccountStatus': {'transactionId': 'DEMO-ACCOUNT-STATUS-001', 'partnerCode': 'DEMO_PARTNER', 'account': {'accountNumber': 'DEMO-ACCOUNT', 'type': 'WALLET'}, 'customer': {'msisdn': 'DEMO-MSISDN'}},
}
ALIASES = {'lookup': 'LookupDetails', 'lookupdetails': 'LookupDetails', 'processtxn': 'ProcessTxn', 'txnstatus': 'TxnStatus', 'createaccount': 'CreateAccount', 'accountstatus': 'AccountStatus'}


@_log_traced('app.transformations.source_presets.preset_payload', level=10)
def preset_payload(name, direction='REQUEST'):
    payload = copy.deepcopy(PRESETS[name])
    if direction == 'RESPONSE':
        return {'transactionId': payload['transactionId'], 'status': 'SUCCESS', 'code': '00',
                'message': 'Synthetic response', 'data': payload}
    return payload
