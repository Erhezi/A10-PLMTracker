-- Empties the Fill/Kill workflow: every sub, order and history row. Only if asked (plan v2 P8):
-- by default, subs and orders entered during UAT are kept at go-live.
-- Run on O2, database PLM. To run it, change @confirm below to 'RESET'; otherwise it does nothing.

SET NOCOUNT ON;

DECLARE @confirm VARCHAR(10) = 'no';

IF @confirm <> 'RESET'
BEGIN
    PRINT 'Nothing deleted. Set @confirm to ''RESET'' to empty Sub, SubOrder and History.';
    RETURN;
END;

BEGIN TRANSACTION;
DELETE FROM [FillKill].[History];
PRINT CONCAT('History rows deleted: ', @@ROWCOUNT);
DELETE FROM [FillKill].[SubOrder];
PRINT CONCAT('Orders deleted: ', @@ROWCOUNT);
DELETE FROM [FillKill].[Sub];
PRINT CONCAT('Subs deleted: ', @@ROWCOUNT);
COMMIT TRANSACTION;
GO
