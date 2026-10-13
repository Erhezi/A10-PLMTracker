-- Unified access (2026-10-12): give everyone the PLM role matching today's users.user_role.
-- Run on O2, database PLM, AFTER 02_user_module_role.sql and BEFORE deploy #1.
--
-- Everyone keeps exactly the access they have today:
--   user_role 'admin'     -> stays admin + PLM editor
--   user_role 'user'      -> PLM editor
--   user_role 'view-only' -> PLM viewer
--
-- users.user_role becomes the app-level role, 'admin' or 'user'. 'view-only' is left in
-- place for now, because the release still on the server reads it; 04_after_deploy.sql
-- renames it to 'user' once the new release is live.
--
-- Safe to re-run: PLM roles are copied only while nobody has one yet, so a re-run never
-- brings back a role an admin has since changed in User Control.

SET NOCOUNT ON;

-- Modules asked for at registration, e.g. 'plm,fillkill'. Grants nothing by itself.
IF COL_LENGTH(N'PLM.users', N'requested_modules') IS NULL
BEGIN
    ALTER TABLE [PLM].[users] ADD [requested_modules] VARCHAR(100) NULL;
    PRINT 'Added users.requested_modules';
END;
GO

IF NOT EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] WHERE [module] = 'plm')
BEGIN
    INSERT INTO [PLM].[UserModuleRole] ([user_id], [module], [role], [granted_by], [granted_at])
    SELECT u.[user_id], 'plm',
           CASE u.[user_role] WHEN 'view-only' THEN 'viewer' ELSE 'editor' END,
           'migrated: 03_unify_roles.sql', GETDATE()
    FROM [PLM].[users] AS u
    WHERE u.[user_role] IN ('admin', 'user', 'view-only');
    PRINT CONCAT('PLM roles: ', @@ROWCOUNT);
END
ELSE
    PRINT 'PLM roles already present; nothing copied.';
GO
