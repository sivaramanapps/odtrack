BEGIN;

ALTER TABLE transactions
    ALTER COLUMN type TYPE VARCHAR(32);

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
            'incidental_charge',
            'debit',
            'credit'
        )
    );

COMMIT;
