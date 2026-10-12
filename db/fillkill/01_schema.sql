-- Fill/Kill Management: schema for everything the app owns (design §6).
-- Run on O2 (YNBBSTVWP02\PROCDATASRVPROD), database PLM. Safe to re-run.

IF SCHEMA_ID(N'FillKill') IS NULL
    EXEC(N'CREATE SCHEMA [FillKill] AUTHORIZATION [dbo];');
GO
