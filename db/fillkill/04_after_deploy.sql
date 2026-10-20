-- After deploy #1 is live: users.user_role holds only the app-level role, 'admin' or 'user'.
-- Run on O2, database PLM, once the new release is serving users. Safe to re-run.
--
-- The previous release marked read-only PLM accounts 'view-only'. Since 03_unify_roles.sql
-- that is a PLM Viewer role in UserModuleRole, and the new release already treats
-- 'view-only' as 'user'; this only tidies the column.
--
-- Don't run it while the previous release is still on the server: that release reads
-- 'view-only', and would let these accounts edit.

SET NOCOUNT ON;

UPDATE [PLM].[users]
SET [user_role] = 'user'
WHERE [user_role] NOT IN ('admin', 'user');  -- 'view-only' is the only other value

PRINT CONCAT('Accounts changed to user: ', @@ROWCOUNT);
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
