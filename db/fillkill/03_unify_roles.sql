-- Unified access (2026-10-12): move today's users.user_role into PLM.UserModuleRole.
-- Run on O2, database PLM, AFTER 02_user_module_role.sql and BEFORE deploy #1.
--
-- Everyone keeps exactly the access they have today:
--   user_role 'admin'     -> app admin + PLM editor   (Fill/Kill roles already seeded by 02)
--   user_role 'user'      -> PLM editor
--   user_role 'view-only' -> PLM viewer
--
-- users.user_role stays: the new release no longer reads it but keeps it in step,
-- so the previous release still works if it has to be redeployed.
--
-- Safe to re-run: the role move happens only while no app/PLM roles exist yet, so a
-- re-run never brings back a role an admin has since changed in User Control.

SET NOCOUNT ON;

-- Modules asked for at registration, e.g. 'plm,fillkill'. Grants nothing by itself.
IF COL_LENGTH(N'PLM.users', N'requested_modules') IS NULL
BEGIN
    ALTER TABLE [PLM].[users] ADD [requested_modules] VARCHAR(100) NULL;
    PRINT 'Added users.requested_modules';
END;
GO

IF NOT EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] WHERE [module] IN ('app', 'plm'))
BEGIN
    BEGIN TRANSACTION;

    INSERT INTO [PLM].[UserModuleRole] ([user_id], [module], [role], [granted_by], [granted_at])
    SELECT u.[user_id], 'app', 'admin', 'migrated: 03_unify_roles.sql', GETDATE()
    FROM [PLM].[users] AS u
    WHERE u.[user_role] = 'admin';
    PRINT CONCAT('App admins: ', @@ROWCOUNT);

    INSERT INTO [PLM].[UserModuleRole] ([user_id], [module], [role], [granted_by], [granted_at])
    SELECT u.[user_id], 'plm',
           CASE u.[user_role] WHEN 'view-only' THEN 'viewer' ELSE 'editor' END,
           'migrated: 03_unify_roles.sql', GETDATE()
    FROM [PLM].[users] AS u
    WHERE u.[user_role] IN ('admin', 'user', 'view-only');
    PRINT CONCAT('PLM roles: ', @@ROWCOUNT);

    COMMIT TRANSACTION;
END
ELSE
    PRINT 'App/PLM roles already present; nothing moved.';
GO
