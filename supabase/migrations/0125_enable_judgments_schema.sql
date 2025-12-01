do $$ begin if exists (
    begin;
create schema if not exists judgments;
commit;