-- Fill/Kill Management: schema for everything the app owns (design §6).
-- Run on O2 (YNBBSTVWP02\PROCDATASRVPROD), database PLM. Safe to re-run.

IF SCHEMA_ID(N'FillKill') IS NULL
    EXEC(N'CREATE SCHEMA [FillKill] AUTHORIZATION [dbo];');
GO

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the tables it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those tables. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO
