-- Empties the Fill/Kill workflow: every sub, vendor item, order and history row. Only if asked (plan v2 P8):
-- by default, subs and orders entered during UAT are kept at go-live.
-- Run on O2, database PLM. To run it, change @confirm below to 'RESET'; otherwise it does nothing.

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
