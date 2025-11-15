-- Enforce unique case numbers on the judgments table
ALTER TABLE public.judgments
    ADD CONSTRAINT judgments_case_number_key UNIQUE (case_number);
