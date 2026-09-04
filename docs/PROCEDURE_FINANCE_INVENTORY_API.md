# Procedure Finance + Inventory Integration Contract

## Ownership
- **Aastha CRM owns:** patient identity/UHID, visits, procedure order, procedure execution/session, clinical completion, rendering branch.
- **External Procedure Finance owns:** procedure price, bill, payment, packages, dues, discounts, refund/tax logic.
- **External Inventory owns:** stock, lots/batches, receipts/issues, consumable rules, stock adjustments.
- External systems never write directly to CRM tables.

## Security
All external procedure endpoints require `X-Integration-Key` and an integration client with explicit scopes. Integration clients are organization-scoped and credentials are stored hashed.

Development keys only:
- Procedure Finance: `dev-procedure-finance-key`
- Inventory: `dev-inventory-key`

Replace/rotate these before any real deployment.

## Procedure flow
1. Doctor creates Procedure Order in CRM.
2. CRM writes `PROCEDURE_ORDER_CREATED` to its transactional outbox for `PROCEDURE_FINANCE`.
3. Finance polls `/external/procedures/finance-events` and reads order details.
4. Finance bills/collects externally.
5. Finance posts only a clearance projection back to CRM: `NOT_BILLED`, `PAYMENT_PENDING`, `PARTIALLY_PAID`, `CLEARED`, `COMPLIMENTARY`, `FINANCIAL_HOLD`, `CANCELLED`.
6. CRM permits a session only when projection is `CLEARED` or `COMPLIMENTARY`.
7. A real Procedure Visit is required for every performed session.
8. Session completion moves that Visit to `COMPLETED` and writes `PROCEDURE_COMPLETED` to the Inventory outbox.
9. Inventory consumes stock from the **Rendering Branch**, then acknowledges the event.
10. Session completion marks the order `PARTIALLY_COMPLETED`; Doctor explicitly closes the order when the treatment order itself is finished. This supports future multi-session packages.

## Finance event feed
`GET /api/v1/external/procedures/finance-events`

Returns pending `PROCEDURE_ORDER_CREATED` and `PROCEDURE_ORDER_CANCELLED` events for the authenticated Finance client.

`POST /api/v1/external/procedures/finance-events/{event_id}/ack`

## Read a Procedure Order
`GET /api/v1/external/procedures/orders/{order_id}`

Returns billing-safe identity/service information. It does not expose doctor notes, visit notes or clinical history.

## Financial status callback
`POST /api/v1/external/procedures/orders/{order_id}/financial-status`

Example:
```json
{
  "external_event_id": "finance-event-9821",
  "financial_status": "CLEARED",
  "external_reference": "PF-2026-000491"
}
```

`external_event_id` is idempotent per integration client. Concurrent duplicate callbacks are reserved with PostgreSQL `ON CONFLICT DO NOTHING`; reuse for another Procedure Order is rejected.

Financial callbacks cannot rewrite completed/partially-completed clinical history. Finance state and clinical state remain separate.

## Inventory event feed
`GET /api/v1/external/procedures/inventory-events`

Payload intentionally contains no Patient name/UHID. It contains only stock-consumption context:
- `procedure_execution_id`
- `procedure_order_id`
- `service_id` / `service_code`
- `rendering_branch_id`
- `performed_by_doctor_id`
- `performed_at`

`POST /api/v1/external/procedures/inventory-events/{event_id}/ack`

Inventory must deduct stock only after `PROCEDURE_COMPLETED`, never merely because an order/bill/appointment exists.

## Development sandbox adapters
With CRM running:
```bash
python tools/procedure_finance_sandbox.py
python tools/inventory_sandbox.py
```
The Finance sandbox automatically marks newly ordered procedures `CLEARED`; the Inventory sandbox consumes/acks completion events.
