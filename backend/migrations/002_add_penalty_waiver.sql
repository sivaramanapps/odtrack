BEGIN;

ALTER TABLE transactions
    DROP CONSTRAINT IF EXISTS ck_transaction_type;

ALTER TABLE transactions
    ADD CONSTRAINT ck_transaction_type CHECK (
        type IN (
            'withdrawal',
            'principal_repayment',
            'interest_payment',
            'penalty_payment',
            'bank_penalty',
            'penalty_waiver',
            'incidental_charge',
            'debit',
            'credit'
        )
    );

COMMIT;
