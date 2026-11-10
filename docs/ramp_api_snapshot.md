# Ramp developer API snapshot (for the payload preview)

Retrieved 2026-11-10 from https://docs.ramp.com/llms-api.txt and the OpenAPI spec at https://docs.ramp.com/openapi/developer-api.json. This is a docs read, not an API call. Tempo never calls Ramp; `tempo/ramp/payloads.py` only builds previews, and `tests/unit/test_ramp_payloads.py` checks every key and enum it emits against the lists below.

## Bill (response, `GET /developer/v1/bills/{bill_id}`)
- `id`
- `vendor`: `id`, `name`, `remote_code?`, `remote_id?`, `remote_name?`, `type?` (`BUSINESS` | `INDIVIDUAL`)
- `invoice_number?`
- `amount`: `amount` (smallest currency unit), `currency_code`, `minor_unit_conversion_rate` (number | null)
- `issued_at`, `due_at`, `paid_at?`
- `status`: `OPEN` | `PAID`
- `approval_status`: `APPROVED` | `INITIALIZED` | `PENDING` | `REJECTED` | `TERMINATED` | null
- `payment` (object | null): `amount`, `payment_date`, `effective_date`, `payment_method`, `details`, `id`, `trace_id`, ...
- No top-level `payment_date` or `payment_arrival_date` on the bill response.

### `status_summary` values
`APPROVAL_PENDING`, `APPROVAL_REJECTED`, `ARCHIVED`, `AWAITING_PAYMENT`, `AWAITING_RELEASE`, `BLOCKED`, `HELD_BY_PROVIDER`, `ON_HOLD`, `PAYMENT_COMPLETED`, `PAYMENT_DETAILS_MISSING`, `PAYMENT_ERROR`, `PAYMENT_NOT_INSTRUCTED`, `PAYMENT_PROCESSING`, `PAYMENT_READY`, `PAYMENT_SCHEDULED`, `PENDING_VENDOR_APPROVAL`, `WAITING_FOR_TRANSACTION_MATCH`, `WAITING_FOR_TRANSFER_MATCH`, `WAITING_FOR_VENDOR`

### `payment_method` in responses
`ACH`, `AUTOMATIC_CARD_PAYMENT`, `CARD`, `CHECK`, `CRYPTO_WALLET_TRANSFER`, `DIRECT_DEBIT`, `DOMESTIC_WIRE`, `EARLY_PAYMENT_DISCOUNT`, `FED_NOW`, `INTERNATIONAL`, `LOCAL_BANK_TRANSFER`, `ONE_TIME_CARD`, `ONE_TIME_CARD_DELIVERY`, `PAID_MANUALLY`, `RTP`, `SWIFT`, `UNSPECIFIED`, or null.
`EARLY_PAYMENT_DISCOUNT` appears only in responses (`Bill.payment.payment_method` and a vendor's `default_payment_method`), described in the spec as "A noncash contribution from an early payment discount."

## `payment_method` accepted in create and PATCH requests
`ACH`, `CARD`, `CHECK`, `CRYPTO_WALLET_TRANSFER`, `DOMESTIC_WIRE`, `INTERNATIONAL`, `LOCAL_BANK_TRANSFER`, `ONE_TIME_CARD`, `ONE_TIME_CARD_DELIVERY`, `PAID_MANUALLY`, `SWIFT`. (`RTP` and `EARLY_PAYMENT_DISCOUNT` are not accepted.)

## Endpoints Tempo previews
- `PATCH /developer/v1/bills/{bill_id}`: "Only approved bills can be updated." Accepts `payment_date?` (date | null; "Set to null to unschedule the payment"; unavailable dates roll to the next one) and `payment_method?`, plus `due_at`, `issued_at`, `invoice_number`, `memo`, `vendor_id`, `vendor_contact_id`, `vendor_memo`, `line_items`, `posting_date`, `purchase_order_ids`, `remote_id`, `entity_id`. Does not accept `payment_details`.
- `POST /developer/v1/bills/{bill_id}/hold` (body `reason?`), beta (`x-beta: true`).
- `POST /developer/v1/bills/{bill_id}/release`, beta (`x-beta: true`).
- Create bill (not previewed) also takes `payment_date?`, `payment_details{payment_arrival_date, source_bank_account_id, vendor_account_id, is_same_day?}`, `target_payment_arrival_date?`.

## Vendors, purchase orders, custom records
- Vendor: `net_payment_terms?` (number | null, "Number of days after receipt that payment is due"), `default_payment_method`, `custom_record_fields`. No discount-terms field.
- Purchase order: `net_payment_terms` (number | null).
- Custom Records API (beta): `/developer/v1/custom-records/...` (custom tables; native tables including `bills` and `vendors`). Tempo's `DiscountTerms` would live here.
- Payments API (beta): `PATCH /developer/v1/payments/{payment_id}` takes `scheduled_date` and `payment_method`.

## What this means for Tempo
- RTP is a rail Ramp chooses when funding from Ramp Checking; the request enum has no `RTP`, so the preview sends `ACH` and notes "RTP when funded from Ramp Checking".
- Card bills: `CARD` is a request value, but the preview notes that card scheduling uses the card's own flow; `payment_date` applies to non-card bills.
- Flex-style financing has no public API; the preview says so.
- The `EARLY_PAYMENT_DISCOUNT` response value is a question for the judges, never a claim about Ramp's roadmap.
