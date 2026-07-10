-- Step 5 the recommended way: audit_helper classifies the migrated mart vs the legacy output
-- (identical / added / removed / modified). Compile it and run the compiled SQL to see the summary.
-- (The hard pass/fail gate is the singular test tests/assert_customer_ltv_parity.sql.)
{{ audit_helper.compare_and_classify_relation_rows(
    a_relation=ref('mart_customer_ltv'),
    b_relation=ref('legacy_customer_ltv'),
    primary_key_columns=['customer_id']
) }}
