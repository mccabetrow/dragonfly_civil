-- Create RPC to submit judgments from website leads
CREATE OR REPLACE FUNCTION public.submit_website_lead(
    in_plaintiff_name TEXT,
    in_defendant_name TEXT,
    in_judgment_amount NUMERIC,
    in_contact_email TEXT
)
RETURNS public.JUDGMENTS
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    inserted_record public.judgments;
BEGIN
    INSERT INTO public.judgments (
        plaintiff_name,
        defendant_name,
        judgment_amount,
        defendant_email,
        source_file,
        status
    )
    VALUES (
        in_plaintiff_name,
        in_defendant_name,
        in_judgment_amount,
        in_contact_email,
        'Website Form',
        'New'
    )
    RETURNING *
    INTO inserted_record;

    RETURN inserted_record;
END;
$$;

GRANT EXECUTE ON FUNCTION public.submit_website_lead(
    TEXT,
    TEXT,
    NUMERIC,
    TEXT
) TO anon, authenticated;

