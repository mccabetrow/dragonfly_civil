-- Extend judgments table with outreach tracking fields
ALTER TABLE public.judgments
    ADD COLUMN status TEXT NOT NULL DEFAULT 'New',
    ADD COLUMN notes TEXT,
    ADD COLUMN defendant_address TEXT,
    ADD COLUMN defendant_phone TEXT,
    ADD COLUMN defendant_email TEXT,
    ADD COLUMN last_contact_date TIMESTAMPTZ;
