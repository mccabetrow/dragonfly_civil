-- Enable row level security and allow public read-only access
ALTER TABLE public.judgments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read-only access"
ON public.judgments
FOR SELECT
USING (true);
