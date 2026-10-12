-- Checks for the Fill/Kill database objects. Read-only; run after every script run.
-- Every row should say PASS. Deploy #2 checks are added when its scripts are written.

SET NOCOUNT ON;

-- Deploy #1 -------------------------------------------------------------------

SELECT 'schema FillKill exists' AS [check],
       CASE WHEN SCHEMA_ID(N'FillKill') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
SELECT 'table PLM.UserModuleRole exists',
       CASE WHEN OBJECT_ID(N'[PLM].[UserModuleRole]', N'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'UserModuleRole cascades on user delete',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.foreign_keys
           WHERE name = N'FK_UserModuleRole_users' AND delete_referential_action_desc = N'CASCADE'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'every admin holds at least one Fill/Kill role',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[users] AS u
           WHERE u.[user_role] = 'admin'
             AND NOT EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS r
                             WHERE r.[user_id] = u.[user_id] AND r.[module] = 'fillkill')
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'no non-admin holds both B (clinical) and C (materials)',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[users] AS u
           JOIN [PLM].[UserModuleRole] AS r ON r.[user_id] = u.[user_id] AND r.[module] = 'fillkill'
           WHERE u.[user_role] <> 'admin' AND r.[role] IN ('clinical', 'materials')
           GROUP BY u.[user_id]
           HAVING COUNT(DISTINCT r.[role]) = 2
       ) THEN 'PASS' ELSE 'FAIL' END;

-- Who holds what, for a quick eyeball.
SELECT u.[email], u.[user_role],
       STRING_AGG(r.[role], ', ') WITHIN GROUP (ORDER BY r.[role]) AS [fillkill_roles]
FROM [PLM].[users] AS u
JOIN [PLM].[UserModuleRole] AS r ON r.[user_id] = u.[user_id] AND r.[module] = 'fillkill'
GROUP BY u.[email], u.[user_role]
ORDER BY u.[email];
