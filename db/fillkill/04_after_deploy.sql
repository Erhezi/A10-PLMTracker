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
