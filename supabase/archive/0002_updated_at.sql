create or replace function public.set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='cases' and column_name='updated_at') then
    alter table judgments.cases add column updated_at timestamptz default now();
    create trigger t_cases_updated before update on judgments.cases
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='judgments' and column_name='updated_at') then
    alter table judgments.judgments add column updated_at timestamptz default now();
    create trigger t_judgments_updated before update on judgments.judgments
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='parties' and column_name='updated_at') then
    alter table judgments.parties add column updated_at timestamptz default now();
    create trigger t_parties_updated before update on judgments.parties
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='contacts' and column_name='updated_at') then
    alter table judgments.contacts add column updated_at timestamptz default now();
    create trigger t_contacts_updated before update on judgments.contacts
      for each row execute function public.set_updated_at();
  end if;
end $$;-- 0002_updated_at.sql
-- Adds updated_at columns and triggers to core tables if missing

create or replace function public.set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='cases' and column_name='updated_at') then
    alter table judgments.cases add column updated_at timestamptz default now();
    create trigger t_cases_updated before update on judgments.cases
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='judgments' and column_name='updated_at') then
    alter table judgments.judgments add column updated_at timestamptz default now();
    create trigger t_judgments_updated before update on judgments.judgments
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='parties' and column_name='updated_at') then
    alter table judgments.parties add column updated_at timestamptz default now();
    create trigger t_parties_updated before update on judgments.parties
      for each row execute function public.set_updated_at();
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='judgments' and table_name='contacts' and column_name='updated_at') then
    alter table judgments.contacts add column updated_at timestamptz default now();
    create trigger t_contacts_updated before update on judgments.contacts
      for each row execute function public.set_updated_at();
  end if;
end $$;
