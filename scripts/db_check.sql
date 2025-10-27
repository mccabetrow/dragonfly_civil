select 'cases' as t, count(*) from information_schema.tables where table_schema='judgments' and table_name='cases'
union all
select 'judgments', count(*) from information_schema.tables where table_schema='judgments' and table_name='judgments'
union all
select 'parties', count(*) from information_schema.tables where table_schema='judgments' and table_name='parties'
union all
select 'contacts', count(*) from information_schema.tables where table_schema='judgments' and table_name='contacts'
union all
select 'runs', count(*) from information_schema.tables where table_schema='ingestion' and table_name='runs';
