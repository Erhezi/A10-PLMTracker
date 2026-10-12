-- Checks for the app's access tables and the Fill/Kill database objects.
-- Read-only; run after every script run. Every row should say PASS, except
-- 'users.user_role is admin or user', which says PENDING until 04 runs after the deploy.
-- Deploy #2 checks are added when its scripts are written.

SET NOCOUNT ON;

-- Deploy #1 -------------------------------------------------------------------

WITH admins AS (
    -- Admin is the app-level role in users.user_role.
    SELECT [user_id] FROM [PLM].[users] WHERE [user_role] = 'admin'
)
SELECT 'schema FillKill exists' AS [check],
       CASE WHEN SCHEMA_ID(N'FillKill') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
SELECT 'table PLM.UserModuleRole exists',
       CASE WHEN OBJECT_ID(N'[PLM].[UserModuleRole]', N'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- Checked by what the key does, whatever it is called.
SELECT 'deleting a user deletes their UserModuleRole rows',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.foreign_keys
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND referenced_object_id = OBJECT_ID(N'[PLM].[users]')
             AND delete_referential_action_desc = N'CASCADE'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'UserModuleRole accepts only known roles for plm and fillkill',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND definition LIKE '%editor%' AND definition LIKE '%clinical%'
             AND definition NOT LIKE '%''app''%'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'a user holds at most one PLM role',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.indexes
           WHERE object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND name = N'UX_UserModuleRole_one_plm_role' AND is_unique = 1
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- Not system-generated names: if this fails, the app created the table before
-- 02_user_module_role.sql ran; re-running 02 renames them.
SELECT 'UserModuleRole constraints have their standard names',
       CASE WHEN (
           SELECT COUNT(*) FROM sys.objects
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND name IN (N'PK_UserModuleRole', N'FK_UserModuleRole_users',
                          N'CK_UserModuleRole_role', N'DF_UserModuleRole_granted_at')
       ) = 4 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'users.requested_modules exists',
       CASE WHEN COL_LENGTH(N'PLM.users', N'requested_modules') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'admin lives in users.user_role, not in UserModuleRole',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[UserModuleRole] WHERE [module] = 'app'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- 'view-only' stays until 04_after_deploy.sql runs, after the new release is live.
SELECT 'users.user_role is admin or user',
       CASE
           WHEN NOT EXISTS (SELECT 1 FROM [PLM].[users] WHERE [user_role] NOT IN ('admin', 'user'))
               THEN 'PASS'
           WHEN NOT EXISTS (SELECT 1 FROM [PLM].[users] WHERE [user_role] NOT IN ('admin', 'user', 'view-only'))
               THEN 'PENDING: run 04 after the deploy'
           ELSE 'FAIL'
       END
UNION ALL
SELECT 'every admin holds at least one Fill/Kill role',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM admins AS a
           WHERE NOT EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS r
                             WHERE r.[user_id] = a.[user_id] AND r.[module] = 'fillkill')
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'no non-admin holds both B (clinical) and C (materials)',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[UserModuleRole] AS r
           WHERE r.[module] = 'fillkill' AND r.[role] IN ('clinical', 'materials')
             AND r.[user_id] NOT IN (SELECT [user_id] FROM admins)
           GROUP BY r.[user_id]
           HAVING COUNT(DISTINCT r.[role]) = 2
       ) THEN 'PASS' ELSE 'FAIL' END;

-- Who holds what, for a quick eyeball.
SELECT u.[email],
       CASE WHEN u.[is_active] = 1 THEN 'active' ELSE 'pending/disabled' END AS [account],
       u.[user_role] AS [app_role],
       MAX(CASE WHEN r.[module] = 'plm' THEN r.[role] ELSE '' END) AS [plm],
       STRING_AGG(CASE WHEN r.[module] = 'fillkill' THEN r.[role] END, ', ')
           WITHIN GROUP (ORDER BY r.[role]) AS [fillkill]
FROM [PLM].[users] AS u
LEFT JOIN [PLM].[UserModuleRole] AS r ON r.[user_id] = u.[user_id]
GROUP BY u.[email], u.[is_active], u.[user_role]
ORDER BY u.[email];
