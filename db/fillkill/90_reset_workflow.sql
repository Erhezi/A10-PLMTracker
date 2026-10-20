-- Empties the Fill/Kill workflow: every sub, vendor item, order and history row, and 12's copy of
-- Sub from before vendor items if it's still there. New ones number from 1 again (2026-10-20).
-- Only if asked (plan v2 P8): by default, subs and orders entered during UAT are kept at go-live.
-- Run on O2, database PLM. To run it, change @confirm below to 'RESET'; otherwise it does nothing.
--
-- Not TRUNCATE TABLE: SQL Server refuses it on Sub and SubVendorItem, which other tables' foreign
-- keys point at; DELETE in this order works.

SET NOCOUNT ON;

DECLARE @confirm VARCHAR(10) = 'no';

IF @confirm <> 'RESET'
BEGIN
    PRINT 'Nothing deleted. Set @confirm to ''RESET'' to empty Sub, SubVendorItem, SubOrder and History.';
    RETURN;
END;

SET XACT_ABORT ON;  -- an error rolls the transaction back instead of leaving it open

BEGIN TRANSACTION;
DELETE FROM [FillKill].[History];
PRINT CONCAT('History rows deleted: ', @@ROWCOUNT);
DELETE FROM [FillKill].[SubOrder];
PRINT CONCAT('Orders deleted: ', @@ROWCOUNT);
DELETE FROM [FillKill].[SubVendorItem];
PRINT CONCAT('Vendor items deleted: ', @@ROWCOUNT);
DELETE FROM [FillKill].[Sub];
PRINT CONCAT('Subs deleted: ', @@ROWCOUNT);

-- Numbered from 1 again. Only a table that has had rows: one never used starts at 1 already, and
-- reseeding it would start it at 0.
IF (SELECT [last_value] FROM sys.identity_columns WHERE [object_id] = OBJECT_ID(N'[FillKill].[History]')) IS NOT NULL
    DBCC CHECKIDENT ('[FillKill].[History]', RESEED, 0) WITH NO_INFOMSGS;
IF (SELECT [last_value] FROM sys.identity_columns WHERE [object_id] = OBJECT_ID(N'[FillKill].[SubOrder]')) IS NOT NULL
    DBCC CHECKIDENT ('[FillKill].[SubOrder]', RESEED, 0) WITH NO_INFOMSGS;
IF (SELECT [last_value] FROM sys.identity_columns WHERE [object_id] = OBJECT_ID(N'[FillKill].[SubVendorItem]')) IS NOT NULL
    DBCC CHECKIDENT ('[FillKill].[SubVendorItem]', RESEED, 0) WITH NO_INFOMSGS;
IF (SELECT [last_value] FROM sys.identity_columns WHERE [object_id] = OBJECT_ID(N'[FillKill].[Sub]')) IS NOT NULL
    DBCC CHECKIDENT ('[FillKill].[Sub]', RESEED, 0) WITH NO_INFOMSGS;

-- 12's copy of the subs as they were before vendor items: nothing left to look up in it.
IF OBJECT_ID(N'[FillKill].[Sub_before_vendor_items]', N'U') IS NOT NULL
BEGIN
    DROP TABLE [FillKill].[Sub_before_vendor_items];
    PRINT 'Dropped FillKill.Sub_before_vendor_items';
END;
COMMIT TRANSACTION;
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
