-- 0212_cases_title_default.sql
-- Ensure judgments.cases.title is non-null with a safe default so older RPCs keep working.
-- Uses a trigger to coalesce NULL title values to a default, since RPCs may explicitly insert NULL.
BEGIN;
-- Backfill existing NULL titles
UPDATE judgments.cases
SET title = COALESCE(title, case_number, 'Untitled Case')
WHERE title IS NULL;
-- Create trigger function to default title on insert/update
CREATE OR REPLACE FUNCTION judgments.default_case_title() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN IF NEW.title IS NULL
    OR NEW.title = '' THEN NEW.title := COALESCE(NEW.case_number, 'Untitled Case');
END IF;
RETURN NEW;
END;
$$;
-- Drop if exists and create trigger
DROP TRIGGER IF EXISTS trg_cases_default_title ON judgments.cases;
CREATE TRIGGER trg_cases_default_title BEFORE
INSERT
    OR
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION judgments.default_case_title();
-- Now enforce NOT NULL (trigger ensures it's never null)
ALTER TABLE judgments.cases
ALTER COLUMN title
SET NOT NULL;
COMMIT;