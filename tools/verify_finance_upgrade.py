"""CI-only populated money-row comparison across the additive Module 6 migration."""
import json,os,sys
from pathlib import Path
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['DATABASE_URL'])
assert engine.url.database=='aastha_ci','Only the isolated CI database may run this migration probe'
path=Path('/tmp/aastha-finance-upgrade.json')
with engine.connect() as c:
    data={}
    for table in ('consultation_bills','payments','entitlements','entitlement_usages','consultation_clearances','complimentary_authorizations','fee_versions','policy_versions'):
        exclude=" - ARRAY['payment_request_id','payment_request_hash','receipt_number']" if table=='payments' else " - 'organization_id'" if table=='policy_versions' else ''
        data[table]=c.execute(text(f'SELECT to_jsonb(t){exclude} FROM consultation_finance.{table} t ORDER BY to_jsonb(t){exclude}')).scalars().all()
    data['counters']=c.execute(text('SELECT to_jsonb(t) FROM core.number_series t ORDER BY number_series_id')).scalars().all()
    encoded=json.dumps(data,sort_keys=True)
    if sys.argv[1]=='snapshot':
        assert data['consultation_bills'] and data['payments'] and data['entitlements']
        path.write_text(encoded)
    else:
        assert path.read_text()==encoded,'Existing financial history or counter changed'
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0010_consultation_payments'
print('Financial migration preserved bills, collections, entitlements and counters')
